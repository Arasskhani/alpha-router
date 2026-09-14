"""Scheduled maintenance for automatic user memory."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import UserMemory, UserMemoryEvent, UserMemorySuppression
from app.models.project import (
    ProjectMemory,
    ProjectMemoryEvent,
    ProjectMemorySuppression,
)
from app.services.memory_settings_service import get_memory_settings, update_memory_settings
from app.services.user_memory_service import record_memory_event

logger = logging.getLogger(__name__)

REINDEX_BATCH = 500
PENDING_STATUSES = ("pending", "failed")


async def run_user_memory_maintenance(db: AsyncSession) -> dict[str, int]:
    settings = await get_memory_settings(db)
    now = dt.datetime.utcnow()
    stats = {
        "expired": 0,
        "archived": 0,
        "purged": 0,
        "suppressions_purged": 0,
        "reembedded": 0,
        "events_pruned": 0,
    }

    expired = (
        (
            await db.execute(
                select(UserMemory).where(
                    UserMemory.deleted_at.is_(None),
                    UserMemory.expires_at.is_not(None),
                    UserMemory.expires_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in expired:
        row.enabled = False
        row.deleted_at = now
        row.updated_at = now
        await record_memory_event(
            db,
            user_id=row.user_id,
            event_type="expired",
            actor="system",
            memory_id=row.id,
        )
        stats["expired"] += 1

    stale_days = int(settings.get("stale_archive_days") or 0)
    if stale_days > 0:
        cutoff = now - dt.timedelta(days=stale_days)
        stale = (
            (
                await db.execute(
                    select(UserMemory).where(
                        UserMemory.deleted_at.is_(None),
                        UserMemory.enabled.is_(True),
                        UserMemory.last_used_at.is_not(None),
                        UserMemory.last_used_at <= cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in stale:
            row.enabled = False
            row.updated_at = now
            await record_memory_event(
                db,
                user_id=row.user_id,
                event_type="disabled",
                actor="system",
                memory_id=row.id,
                detail={"reason": "stale_archive"},
            )
            stats["archived"] += 1

    purge_days = int(settings.get("soft_delete_purge_days") or 30)
    purge_cutoff = now - dt.timedelta(days=purge_days)
    doomed = (
        (
            await db.execute(
                select(UserMemory).where(
                    UserMemory.deleted_at.is_not(None),
                    UserMemory.deleted_at <= purge_cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if doomed:
        try:
            from app.services.memory_vector_service import MemoryVectorService

            service = MemoryVectorService()
            collection = await service.resolve_target_collection()
            await service.delete_ids(collection_name=collection, point_ids=[row.id for row in doomed])
        except Exception:
            logger.exception("Failed to delete purged memory vectors")
        for row in doomed:
            await record_memory_event(
                db,
                user_id=row.user_id,
                event_type="purged",
                actor="system",
                memory_id=row.id,
            )
            await db.delete(row)
        stats["purged"] = len(doomed)

    supp_result = await db.execute(
        delete(UserMemorySuppression).where(
            UserMemorySuppression.expires_at.is_not(None),
            UserMemorySuppression.expires_at <= now,
        )
    )
    stats["suppressions_purged"] = int(supp_result.rowcount or 0)

    pending = (
        (
            await db.execute(
                select(UserMemory)
                .where(
                    UserMemory.deleted_at.is_(None),
                    UserMemory.embedding_status.in_(("pending", "failed")),
                )
                .order_by(UserMemory.updated_at.desc())
                .limit(REINDEX_BATCH)
            )
        )
        .scalars()
        .all()
    )
    from app.services.user_memory_service import _index_memory_vector

    for row in pending:
        await _index_memory_vector(db, row)
        if row.embedding_status == "indexed":
            stats["reembedded"] += 1

    event_cutoff = now - dt.timedelta(days=365)
    pruned = await db.execute(delete(UserMemoryEvent).where(UserMemoryEvent.created_at < event_cutoff))
    stats["events_pruned"] = int(pruned.rowcount or 0)

    project_stats = await _run_project_memory_maintenance(db, settings=settings, now=now, event_cutoff=event_cutoff)
    for key, value in project_stats.items():
        stats[f"project_{key}"] = value

    remaining = int(
        (
            await db.execute(
                select(func.count())
                .select_from(UserMemory)
                .where(
                    UserMemory.deleted_at.is_(None),
                    UserMemory.embedding_status.in_(PENDING_STATUSES),
                )
            )
        ).scalar_one()
        or 0
    ) + int(
        (
            await db.execute(
                select(func.count())
                .select_from(ProjectMemory)
                .where(
                    ProjectMemory.deleted_at.is_(None),
                    ProjectMemory.embedding_status.in_(PENDING_STATUSES),
                )
            )
        ).scalar_one()
        or 0
    )
    try:
        from app.services.observability import set_memory_embedding_backlog

        set_memory_embedding_backlog(remaining)
    except Exception:
        pass
    await db.flush()
    return stats


async def _run_project_memory_maintenance(
    db: AsyncSession,
    *,
    settings: dict,
    now: dt.datetime,
    event_cutoff: dt.datetime,
) -> dict[str, int]:
    """Expire, archive, purge and re-embed project facts in the same pass."""
    from app.services.project_memory_service import (
        SOURCE_MANUAL,
        index_project_memory_vector,
        record_project_memory_event,
        sync_project_vector_enabled,
    )

    stats = {
        "expired": 0,
        "archived": 0,
        "purged": 0,
        "suppressions_purged": 0,
        "reembedded": 0,
        "events_pruned": 0,
    }

    expired = (
        (
            await db.execute(
                select(ProjectMemory).where(
                    ProjectMemory.deleted_at.is_(None),
                    ProjectMemory.expires_at.is_not(None),
                    ProjectMemory.expires_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    for row in expired:
        row.enabled = False
        row.deleted_at = now
        row.updated_at = now
        await sync_project_vector_enabled(db, row, enabled=False)
        await record_project_memory_event(
            db,
            project_id=row.project_id,
            event_type="expired",
            actor="system",
            memory_id=row.id,
        )
        stats["expired"] += 1

    stale_days = int(settings.get("stale_archive_days") or 0)
    if stale_days > 0:
        cutoff = now - dt.timedelta(days=stale_days)
        stale = (
            (
                await db.execute(
                    select(ProjectMemory).where(
                        ProjectMemory.deleted_at.is_(None),
                        ProjectMemory.enabled.is_(True),
                        # Owner-authored facts never go stale on their own.
                        ProjectMemory.source_type != SOURCE_MANUAL,
                        ProjectMemory.last_used_at.is_not(None),
                        ProjectMemory.last_used_at <= cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in stale:
            row.enabled = False
            row.updated_at = now
            await sync_project_vector_enabled(db, row, enabled=False)
            await record_project_memory_event(
                db,
                project_id=row.project_id,
                event_type="disabled",
                actor="system",
                memory_id=row.id,
                detail={"reason": "stale_archive"},
            )
            stats["archived"] += 1

    purge_days = int(settings.get("soft_delete_purge_days") or 30)
    purge_cutoff = now - dt.timedelta(days=purge_days)
    doomed = (
        (
            await db.execute(
                select(ProjectMemory).where(
                    ProjectMemory.deleted_at.is_not(None),
                    ProjectMemory.deleted_at <= purge_cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    if doomed:
        try:
            from app.services.memory_vector_service import MemoryVectorService

            service = MemoryVectorService()
            collection = await service.resolve_target_collection()
            await service.delete_ids(collection_name=collection, point_ids=[row.id for row in doomed])
        except Exception:
            logger.exception("Failed to delete purged project memory vectors")
        for row in doomed:
            await record_project_memory_event(
                db,
                project_id=row.project_id,
                event_type="purged",
                actor="system",
            )
            await db.delete(row)
        stats["purged"] = len(doomed)

    supp_result = await db.execute(
        delete(ProjectMemorySuppression).where(
            ProjectMemorySuppression.expires_at.is_not(None),
            ProjectMemorySuppression.expires_at <= now,
        )
    )
    stats["suppressions_purged"] = int(supp_result.rowcount or 0)

    pending = (
        (
            await db.execute(
                select(ProjectMemory)
                .where(
                    ProjectMemory.deleted_at.is_(None),
                    ProjectMemory.embedding_status.in_(PENDING_STATUSES),
                )
                .order_by(ProjectMemory.updated_at.desc())
                .limit(REINDEX_BATCH)
            )
        )
        .scalars()
        .all()
    )
    for row in pending:
        await index_project_memory_vector(db, row)
        if row.embedding_status == "indexed":
            stats["reembedded"] += 1

    pruned = await db.execute(delete(ProjectMemoryEvent).where(ProjectMemoryEvent.created_at < event_cutoff))
    stats["events_pruned"] = int(pruned.rowcount or 0)
    await db.flush()
    return stats


async def reindex_all_memories(db: AsyncSession) -> dict[str, int]:
    from app.services.memory_embedding_service import memory_embedding_config
    from app.services.memory_vector_service import (
        memory_collection_name,
        MemoryVectorService,
    )
    from app.services.project_memory_service import index_project_memory_vector
    from app.services.user_memory_service import _index_memory_vector

    cfg = await memory_embedding_config(db)
    if cfg is None:
        raise RuntimeError("Memory embedding model is not configured")
    _, _, dims = cfg
    settings = await get_memory_settings(db)
    current = int(settings.get("qdrant_collection_version") or 1)
    nxt = current + 1
    service = MemoryVectorService()
    new_name = memory_collection_name(version=nxt)
    await service.ensure_collection(collection_name=new_name, dims=dims)
    rows = (
        (
            await db.execute(
                select(UserMemory).where(
                    UserMemory.deleted_at.is_(None),
                    UserMemory.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    indexed = 0
    for row in rows:
        row.embedding_status = "pending"
        # Explicit collection: reads keep hitting the old alias target until the
        # new collection is fully populated.
        await _index_memory_vector(db, row, collection=new_name)
        if row.embedding_status == "indexed":
            indexed += 1
    project_rows = (
        (
            await db.execute(
                select(ProjectMemory).where(
                    ProjectMemory.deleted_at.is_(None),
                    ProjectMemory.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in project_rows:
        row.embedding_status = "pending"
        await index_project_memory_vector(db, row, collection=new_name)
        if row.embedding_status == "indexed":
            indexed += 1
    await service.activate_alias(collection_name=new_name)
    await update_memory_settings(db, {"qdrant_collection_version": nxt})
    # Suppression content is never stored, so those vectors cannot be rebuilt.
    # Hash suppression still blocks re-learning; drop the stale indexed claim.
    await db.execute(
        update(UserMemorySuppression).where(UserMemorySuppression.vector_indexed.is_(True)).values(vector_indexed=False)
    )
    await db.execute(
        update(ProjectMemorySuppression)
        .where(ProjectMemorySuppression.vector_indexed.is_(True))
        .values(vector_indexed=False)
    )
    old_name = memory_collection_name(version=current)
    if old_name != new_name:
        await service.delete_collection(collection_name=old_name)
    return {"indexed": indexed, "version": nxt}
