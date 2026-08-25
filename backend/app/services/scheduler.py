"""Background jobs: model sync, monthly budget reset, scheduled reports."""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.config import get_settings
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.budget_service import reset_all_monthly_budgets
from app.services.model_sync import sync_connection_with_flash
from app.services.secret_crypto import decrypt_secret
from app.services.operations_service import prune_old_snapshots, record_system_snapshot
from app.services.schedule_timezone import get_server_timezone
from app.services.storage_service import get_storage_settings, purge_expired_media
from app.services.user_media_service import purge_user_media_older_than
from app.models.user_media_prefs import UserMediaPreferences

scheduler = AsyncIOScheduler()
logger = logging.getLogger("app.services.scheduler")


async def job_sync_all_models():
    """Auto-sync connections that are due (per sync_interval_hours), with model flash like Sync Now."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        conns = (await db.execute(select(Connection).where(Connection.sync_enabled == True))).scalars().all()  # noqa: E712
        for c in conns:
            if not c.is_active:
                continue
            hours = max(1, int(c.sync_interval_hours or 6))
            if c.last_sync_at:
                elapsed_h = (now - c.last_sync_at).total_seconds() / 3600.0
                if elapsed_h < hours:
                    continue
            await sync_connection_with_flash(db, c, decrypt_secret(c.api_key_encrypted))
        await db.commit()


async def job_reset_budgets():
    async with AsyncSessionLocal() as db:
        await reset_all_monthly_budgets(db)


async def job_expire_budget_reservations():
    from app.services.budget_reservation_service import expire_stale_reservations

    async with AsyncSessionLocal() as db:
        await expire_stale_reservations(db)
        await db.commit()


async def job_reconcile_provider_costs():
    from app.services.provider_reconciliation_service import (
        automatic_reconciliation_providers,
        reconcile_connection_costs,
    )

    settings = get_settings()
    if not settings.cost_reconciliation_enabled:
        return
    providers = automatic_reconciliation_providers()
    if not providers:
        return
    async with AsyncSessionLocal() as db:
        connection_ids = (
            await db.execute(
                select(Connection.id).where(
                    Connection.is_active.is_(True),
                    Connection.provider_type.in_(providers),
                )
            )
        ).scalars().all()
    for connection_id in connection_ids:
        async with AsyncSessionLocal() as db:
            connection = await db.get(Connection, connection_id)
            if connection is None:
                continue
            provider = connection.provider_type
            try:
                await reconcile_connection_costs(
                    db,
                    connection,
                    limit=settings.cost_reconciliation_batch_size,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "Cost reconciliation failed connection_id=%s provider=%s",
                    connection_id,
                    provider,
                )


async def job_storage_cleanup():
    async with AsyncSessionLocal() as db:
        settings = await get_storage_settings(db)
        await purge_expired_media(db, retention_days=int(settings["retention_days"]))


async def job_user_media_cleanup():
    """Run per-user scheduled media cleanup (each user's own retention only)."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        prefs_rows = (
            await db.execute(
                select(UserMediaPreferences).where(UserMediaPreferences.cleanup_enabled == True)  # noqa: E712
            )
        ).scalars().all()
        for prefs in prefs_rows:
            if now.hour != int(prefs.cleanup_hour or 0):
                continue
            if now.minute < int(prefs.cleanup_minute or 0):
                continue
            if prefs.last_cleanup_at and prefs.last_cleanup_at.date() == now.date():
                continue
            await purge_user_media_older_than(db, prefs.user_id, int(prefs.cleanup_retention_days or 30))
            prefs.last_cleanup_at = now
        await db.commit()


async def job_system_metrics_snapshot():
    async with AsyncSessionLocal() as db:
        await record_system_snapshot(db)
        await prune_old_snapshots(db)


async def job_chat_stats_reconcile():
    async with AsyncSessionLocal() as db:
        from app.services.user_chat_storage_service import reconcile_session_message_stats

        await reconcile_session_message_stats(db)
        await db.commit()


async def job_model_tool_compatibility():
    """Refresh a claimed, rate-limited batch of Code Interpreter capabilities."""
    from app.services.code_interpreter_probe_service import (
        claim_due_probe_model_ids,
        probe_model_compatibility,
    )
    from app.services.model_tool_compatibility_service import (
        prune_compatibility_events,
    )

    async with AsyncSessionLocal() as db:
        model_ids = await claim_due_probe_model_ids(db)
    for model_id in model_ids:
        async with AsyncSessionLocal() as db:
            model = await db.get(AIModel, model_id)
            if model is None:
                continue
            try:
                await probe_model_compatibility(db, model)
            except Exception:
                await db.rollback()
                logger.exception(
                    "Model-tool compatibility probe crashed model_id=%s",
                    model_id,
                )
    async with AsyncSessionLocal() as db:
        await prune_compatibility_events(db)
        await db.commit()


async def job_user_memory_maintenance():
    async with AsyncSessionLocal() as db:
        from app.services.memory_maintenance_service import run_user_memory_maintenance

        try:
            # Covers both the user and project scopes in one pass.
            stats = await run_user_memory_maintenance(db)
            await db.commit()
            if any(stats.values()):
                logger.info("Memory maintenance %s", stats)
        except Exception:
            await db.rollback()
            logger.exception("Memory maintenance failed")


async def job_chat_retention_cleanup():
    async with AsyncSessionLocal() as db:
        from app.services.retention_policy_service import (
            get_chat_retention_settings,
            purge_expired_chat_messages,
        )

        try:
            settings = await get_chat_retention_settings(db)
            if not settings["retention_enabled"]:
                return
            await purge_expired_chat_messages(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Chat retention cleanup failed")


async def job_purge_deleted_projects():
    async with AsyncSessionLocal() as db:
        from app.services.project_service import purge_expired_deleted_projects

        try:
            n = await purge_expired_deleted_projects(db)
            await db.commit()
            if n:
                logger.info("Purged %s deletion-pending projects", n)
        except Exception:
            await db.rollback()
            logger.exception("Project deletion-pending purge failed")


async def refresh_storage_cleanup_schedule() -> None:
    async with AsyncSessionLocal() as db:
        settings = await get_storage_settings(db)
    enabled = bool(settings["clear_schedule_enabled"])
    hour = int(settings["clear_schedule_hour"])
    minute = int(settings["clear_schedule_minute"])
    if scheduler.get_job("storage_cleanup"):
        scheduler.remove_job("storage_cleanup")
    if enabled:
        scheduler.add_job(
            job_storage_cleanup,
            "cron",
            hour=hour,
            minute=minute,
            timezone=get_server_timezone(),
            id="storage_cleanup",
        )


async def refresh_chat_retention_cleanup_schedule() -> None:
    from app.services.retention_policy_service import get_chat_retention_settings

    async with AsyncSessionLocal() as db:
        settings = await get_chat_retention_settings(db)
    enabled = bool(settings["retention_enabled"] and settings["clear_schedule_enabled"])
    hour = int(settings["clear_schedule_hour"])
    minute = int(settings["clear_schedule_minute"])
    if scheduler.get_job("chat_retention_cleanup"):
        scheduler.remove_job("chat_retention_cleanup")
    if enabled:
        scheduler.add_job(
            job_chat_retention_cleanup,
            "cron",
            hour=hour,
            minute=minute,
            timezone=get_server_timezone(),
            id="chat_retention_cleanup",
        )


async def job_reclaim_stale_video_jobs():
    from app.services.video_job_service import reclaim_stale_video_jobs

    try:
        await reclaim_stale_video_jobs()
    except Exception:
        logger.exception("Video job reclaim failed")


def start_scheduler():
    if scheduler.running:
        return
    # Check every 30 minutes which connections are due for their own sync_interval_hours
    scheduler.add_job(job_sync_all_models, "interval", minutes=30, id="model_sync")
    scheduler.add_job(job_reset_budgets, "cron", day=1, hour=0, minute=5, id="budget_reset")
    scheduler.add_job(
        job_expire_budget_reservations,
        "interval",
        minutes=5,
        id="budget_reservation_expiry",
    )
    scheduler.add_job(
        job_reclaim_stale_video_jobs,
        "interval",
        minutes=5,
        id="video_job_reclaim",
        max_instances=1,
        coalesce=True,
    )
    settings = get_settings()
    if settings.cost_reconciliation_enabled:
        scheduler.add_job(
            job_reconcile_provider_costs,
            "interval",
            minutes=max(
                5,
                int(settings.cost_reconciliation_interval_minutes or 30),
            ),
            id="cost_reconciliation",
        )
    scheduler.add_job(
        job_storage_cleanup,
        "cron",
        hour=3,
        minute=0,
        timezone=get_server_timezone(),
        id="storage_cleanup",
    )
    scheduler.add_job(
        job_chat_retention_cleanup,
        "cron",
        hour=4,
        minute=0,
        timezone=get_server_timezone(),
        id="chat_retention_cleanup",
    )
    scheduler.add_job(
        job_user_memory_maintenance,
        "cron",
        hour=3,
        minute=40,
        timezone=get_server_timezone(),
        id="user_memory_maintenance",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_purge_deleted_projects,
        "cron",
        hour=4,
        minute=20,
        timezone=get_server_timezone(),
        id="project_deletion_purge",
    )
    scheduler.add_job(job_chat_stats_reconcile, "cron", hour=3, minute=30, id="chat_stats_reconcile")
    scheduler.add_job(job_user_media_cleanup, "cron", hour="*", minute=0, id="user_media_cleanup")
    scheduler.add_job(job_system_metrics_snapshot, "interval", hours=1, id="system_metrics_snapshot")
    scheduler.add_job(
        job_model_tool_compatibility,
        "interval",
        minutes=30,
        id="model_tool_compatibility",
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
