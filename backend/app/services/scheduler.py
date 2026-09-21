"""Background jobs: model sync, monthly budget reset, scheduled reports."""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.user_media_prefs import UserMediaPreferences
from app.services.budget_service import reset_all_monthly_budgets
from app.services.model_sync import sync_connection_with_flash
from app.services.operations_service import prune_old_snapshots, record_system_snapshot
from app.services.schedule_timezone import get_server_timezone
from app.services.secret_crypto import decrypt_secret
from app.services.storage_service import get_storage_settings, purge_expired_media
from app.services.user_media_service import purge_user_media_older_than

# misfire_grace_time: APScheduler's default is 1 second. After a leader
# hand-over (the new leader starts its scheduler seconds after the old one
# died), a slow event loop or a paused container, every cron whose instant
# passed in the meantime is *skipped* silently - the monthly budget reset
# among them. Five minutes of grace with coalescing runs each missed job once.
# The timezone makes bare cron triggers (no explicit timezone=) fire in the
# server's zone instead of UTC, matching what admins configure.
scheduler = AsyncIOScheduler(
    job_defaults={"misfire_grace_time": 300, "coalesce": True, "max_instances": 1},
    timezone=get_server_timezone(),
)
logger = logging.getLogger("app.services.scheduler")


async def job_sync_all_models():
    """Auto-sync connections that are due (per sync_interval_hours), with model flash like Sync Now."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        conns = (await db.execute(select(Connection).where(Connection.sync_enabled == True))).scalars().all()  # noqa: E712
        # Decide what is due from plain values first. A rollback below expires
        # every loaded instance, and reading an expired attribute lazy-loads,
        # which an async session cannot do outside an await - so the loop
        # must not touch the ORM objects after the first failure.
        due = []
        for c in conns:
            if not c.is_active:
                continue
            hours = max(1, int(c.sync_interval_hours or 6))
            if c.last_sync_at:
                elapsed_h = (now - c.last_sync_at).total_seconds() / 3600.0
                if elapsed_h < hours:
                    continue
            due.append((int(c.id), str(c.name)))
        for connection_id, label in due:
            # One provider being down must not stop the others from syncing,
            # and must leave a line that names it.
            try:
                connection = await db.get(Connection, connection_id)
                if connection is None:
                    continue
                await sync_connection_with_flash(db, connection, decrypt_secret(connection.api_key_encrypted))
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("Model sync failed for connection %s (id=%s)", label, connection_id)


async def job_reset_budgets():
    async with AsyncSessionLocal() as db:
        try:
            count = await reset_all_monthly_budgets(db)
            await db.commit()
            logger.info("Monthly budget reset: %s users", count)
        except Exception:
            await db.rollback()
            logger.exception("Monthly budget reset failed")


async def job_expire_budget_reservations():
    from app.services.budget_reservation_service import (
        expire_stale_reservations,
        reconcile_drifted_reserved_counters,
    )

    repaired = 0
    async with AsyncSessionLocal() as db:
        try:
            await expire_stale_reservations(db)
            # Expiry only closes rows. A reserved counter that drifted above the rows
            # behind it has nothing to expire, so repair those too — otherwise the
            # gap keeps consuming budget until period rollover.
            repaired = await reconcile_drifted_reserved_counters(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Budget reservation expiry failed")
    if repaired:
        logger.warning("Repaired drifted reserved budget counters for %s subject(s)", repaired)


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
            (
                await db.execute(
                    select(Connection.id).where(
                        Connection.is_active.is_(True),
                        Connection.provider_type.in_(providers),
                    )
                )
            )
            .scalars()
            .all()
        )
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


def user_media_cleanup_due(prefs, now: datetime, tz=None) -> bool:
    """True when today's scheduled (hour, minute) has passed and was not served yet.

    The old rule ran only at minute 0 of the chosen hour and skipped when
    ``now.minute < cleanup_minute`` - so any minute other than 0 meant the
    cleanup never ran. Now the job polls every 15 minutes and this decides.

    ``now`` and ``prefs.last_cleanup_at`` are naive UTC (what the job and the
    column store). The user's (hour, minute) is a wall-clock time in the
    server's timezone - the same zone the other cron jobs use - so the slot
    is built there and converted back to UTC before comparing.
    """
    tz = tz or get_server_timezone()
    hour = int(prefs.cleanup_hour or 0)
    minute = int(prefs.cleanup_minute or 0)
    now_local = now.replace(tzinfo=UTC).astimezone(tz)
    scheduled_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_local < scheduled_local:
        return False
    scheduled_utc = scheduled_local.astimezone(UTC).replace(tzinfo=None)
    last = prefs.last_cleanup_at
    return last is None or last < scheduled_utc


async def job_user_media_cleanup():
    """Run per-user scheduled media cleanup (each user's own retention only)."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        prefs_rows = (
            (
                await db.execute(
                    select(UserMediaPreferences).where(UserMediaPreferences.cleanup_enabled == True)  # noqa: E712
                )
            )
            .scalars()
            .all()
        )
        # Plain values first: a rollback expires the loaded rows, and reading
        # an expired attribute afterwards lazy-loads, which cannot happen here.
        due = [
            (int(prefs.user_id), int(prefs.cleanup_retention_days or 30))
            for prefs in prefs_rows
            if user_media_cleanup_due(prefs, now)
        ]
        for user_id, days in due:
            # One user's storage failing must not stop everyone else's cleanup.
            try:
                await purge_user_media_older_than(db, user_id, days)
                row = await db.get(UserMediaPreferences, user_id)
                if row is not None:
                    row.last_cleanup_at = now
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("User media cleanup failed for user %s", user_id)


async def job_system_metrics_snapshot():
    async with AsyncSessionLocal() as db:
        try:
            await record_system_snapshot(db)
            await prune_old_snapshots(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("System metrics snapshot failed")


async def job_chat_stats_reconcile():
    async with AsyncSessionLocal() as db:
        from app.services.user_chat_storage_service import reconcile_session_message_stats

        try:
            await reconcile_session_message_stats(db)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Chat statistics reconcile failed")


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


async def job_request_log_retention():
    """Trim ``request_logs`` to its retention window.

    The only table in the product that never had a retention job, and the one
    that grows fastest - one row per API call. Without this the API Logs page
    gets slower forever and the database grows without bound on an installation
    nobody is watching.
    """

    async with AsyncSessionLocal() as db:
        from app.services.request_log_retention_service import purge_expired_request_logs

        try:
            result = await purge_expired_request_logs(db)
            if result["rows_deleted"]:
                logger.info(
                    "Request log retention: %s rows deleted (>%sd)",
                    result["rows_deleted"],
                    result["retention_days"],
                )
        except Exception:
            await db.rollback()
            logger.exception("Request log retention failed")


async def job_admin_log_retention():
    """Apply the administrative audit trail's two retention windows.

    The run records itself in the governance audit chain, which this job never
    prunes: a retention pass that destroys evidence must leave evidence that it
    ran, somewhere it cannot reach.
    """
    async with AsyncSessionLocal() as db:
        from app.services.admin_log_retention_service import purge_expired_admin_logs

        try:
            result = await purge_expired_admin_logs(db)
            if result["details_redacted"] or result["events_deleted"]:
                logger.info(
                    "Admin log retention: %s details redacted (>%sd), %s events deleted (>%sd)",
                    result["details_redacted"],
                    result["detail_retention_days"],
                    result["events_deleted"],
                    result["event_retention_days"],
                )
                try:
                    from app.services.agent_governance_service import append_governance_audit_event

                    await append_governance_audit_event(
                        db,
                        event_type="governance.retention.admin_logs.purged",
                        resource_type="security_audit",
                        resource_id=None,
                        actor_user_id=None,
                        outcome="success",
                        payload=dict(result),
                    )
                    await db.commit()
                except Exception:
                    # The purge already committed; failing to record it must not
                    # roll anything back or hide the run from the log above.
                    await db.rollback()
                    logger.exception("Admin log retention ran but could not be recorded in the audit chain")
        except Exception:
            await db.rollback()
            logger.exception("Admin log retention run failed")


async def job_raw_payload_retention():
    """Clear provider payloads past the window set on the API Logs page."""
    async with AsyncSessionLocal() as db:
        from app.services.log_detail_retention_service import purge_expired_raw_payloads

        try:
            result = await purge_expired_raw_payloads(db)
            await db.commit()
            if result["usage_events_cleared"] or result["video_jobs_cleared"]:
                logger.info(
                    "Raw provider payloads cleared: %s usage events, %s video jobs (older than %s days)",
                    result["usage_events_cleared"],
                    result["video_jobs_cleared"],
                    result["retention_days"],
                )
        except Exception:
            await db.rollback()
            logger.exception("Raw provider payload retention run failed")


async def job_tls_expiry_notice():
    async with AsyncSessionLocal() as db:
        from app.services.tls_expiry_service import notify_expiring_certificates

        try:
            result = await notify_expiring_certificates(db)
            await db.commit()
            if result.get("sent"):
                logger.info("Sent %s TLS expiry notices", result["sent"])
        except Exception:
            await db.rollback()
            logger.exception("TLS expiry notice job failed")


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


async def job_purge_expired_private_videos():
    from app.services.video_job_service import purge_expired_private_videos

    try:
        await purge_expired_private_videos()
    except Exception:
        logger.exception("Expired private video purge failed")


async def job_reclaim_stale_video_jobs():
    from app.services.video_job_service import reclaim_stale_video_jobs

    try:
        await reclaim_stale_video_jobs()
    except Exception:
        logger.exception("Video job reclaim failed")


def start_scheduler():
    global _shutdown_requested
    if scheduler.running:
        return
    _shutdown_requested = False
    # Check every 30 minutes which connections are due for their own sync_interval_hours
    scheduler.add_job(job_sync_all_models, "interval", minutes=30, id="model_sync")
    # Budget periods are month-of-UTC everywhere else (ensure_budget_period,
    # get_month_usage), so the reset fires at 00:05 UTC on the 1st, not local.
    scheduler.add_job(job_reset_budgets, "cron", day=1, hour=0, minute=5, id="budget_reset", timezone=UTC)
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
    # Private videos expire on a clock rather than being destroyed by the first
    # read. Without this the object behind one that is never downloaded would
    # never be deleted at all.
    scheduler.add_job(
        job_purge_expired_private_videos,
        "interval",
        minutes=5,
        id="private_video_expiry",
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
        job_raw_payload_retention,
        "cron",
        hour=4,
        minute=10,
        timezone=get_server_timezone(),
        id="api_logs_raw_payload_retention",
    )
    scheduler.add_job(
        job_admin_log_retention,
        "cron",
        hour=4,
        minute=25,
        timezone=get_server_timezone(),
        id="admin_log_retention",
    )
    # After the admin log pass, and out of hours: this is the biggest table in
    # the product and the first run on an installation that has never had
    # retention will have a lot to remove.
    scheduler.add_job(
        job_request_log_retention,
        "cron",
        hour=4,
        minute=45,
        timezone=get_server_timezone(),
        id="request_log_retention",
        max_instances=1,
        coalesce=True,
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
    # Every 15 minutes: the job itself decides per user whether their
    # (hour, minute) has passed today and has not been served yet.
    scheduler.add_job(job_user_media_cleanup, "cron", minute="*/15", id="user_media_cleanup")
    scheduler.add_job(job_system_metrics_snapshot, "interval", hours=1, id="system_metrics_snapshot")
    scheduler.add_job(
        job_tls_expiry_notice,
        "cron",
        hour=6,
        minute=0,
        timezone=get_server_timezone(),
        id="tls_expiry_notice",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_model_tool_compatibility,
        "interval",
        minutes=30,
        id="model_tool_compatibility",
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    # Admin-controlled schedules (storage cleanup, chat retention, directory
    # sync) are edited through whichever uvicorn worker serves the request,
    # which is usually not the leader. The leader re-reads them from the
    # database every minute so a change applies without a restart.
    scheduler.add_job(
        job_refresh_dynamic_schedules,
        "interval",
        minutes=1,
        id="refresh_dynamic_schedules",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


async def job_refresh_dynamic_schedules() -> None:
    from app.services.auth_sync_scheduler import refresh_auth_sync_schedules

    for refresh in (
        refresh_storage_cleanup_schedule,
        refresh_chat_retention_cleanup_schedule,
        refresh_auth_sync_schedules,
    ):
        try:
            await refresh()
        except Exception:
            logger.exception("Failed to refresh %s", getattr(refresh, "__name__", refresh))


_shutdown_requested = False


def stop_scheduler():
    """Idempotent: AsyncIOScheduler.shutdown() is deferred to the loop, so
    ``scheduler.running`` stays True until that callback runs and a second
    call in the same tick scheduled a second shutdown that raised
    SchedulerNotRunningError (seen on every worker exit: the leader's
    on_release and the lifespan both called this)."""
    global _shutdown_requested
    if scheduler.running and not _shutdown_requested:
        _shutdown_requested = True
        scheduler.shutdown(wait=False)
