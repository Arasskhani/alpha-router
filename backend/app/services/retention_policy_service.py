"""Global retention policy settings (chat history; media uses storage_service)."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.knowledge import LegalHold
from app.models.system import SystemSetting
from app.services.agent_governance_service import append_governance_audit_event
from app.services.schedule_timezone import server_timezone_label

logger = logging.getLogger(__name__)

_KEY_CHAT_RETENTION_ENABLED = "chat_retention_enabled"
_KEY_CHAT_RETENTION_DAYS = "chat_retention_days"
_KEY_CHAT_CLEAR_SCHEDULE_ENABLED = "chat_clear_schedule_enabled"
_KEY_CHAT_CLEAR_SCHEDULE_HOUR = "chat_clear_schedule_hour"
_KEY_CHAT_CLEAR_SCHEDULE_MINUTE = "chat_clear_schedule_minute"

_CHAT_SETTING_KEYS = (
    _KEY_CHAT_RETENTION_ENABLED,
    _KEY_CHAT_RETENTION_DAYS,
    _KEY_CHAT_CLEAR_SCHEDULE_ENABLED,
    _KEY_CHAT_CLEAR_SCHEDULE_HOUR,
    _KEY_CHAT_CLEAR_SCHEDULE_MINUTE,
)

_PURGE_BATCH_SIZE = 5000


def _chat_message_has_active_legal_hold():
    direct_session_hold = exists(
        select(LegalHold.id).where(
            LegalHold.resource_type == "chat_session",
            LegalHold.resource_id == ChatMessage.session_id,
            LegalHold.status == "active",
        )
    )
    held_agent_id = (
        select(ChatSession.current_agent_id)
        .where(ChatSession.id == ChatMessage.session_id)
        .correlate(ChatMessage)
        .scalar_subquery()
    )
    agent_hold = exists(
        select(LegalHold.id).where(
            LegalHold.resource_type == "agent",
            LegalHold.resource_id == held_agent_id,
            LegalHold.status == "active",
        )
    )
    agent_run_hold = and_(
        ChatMessage.agent_run_id.is_not(None),
        exists(
            select(LegalHold.id).where(
                LegalHold.resource_type == "agent_run",
                LegalHold.resource_id == ChatMessage.agent_run_id,
                LegalHold.status == "active",
            )
        ),
    )
    return or_(direct_session_hold, agent_hold, agent_run_hold)


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    return (raw or ("true" if default else "false")).lower() in ("1", "true", "yes", "on")


async def get_chat_retention_settings(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(_CHAT_SETTING_KEYS)))).scalars().all()
    kv = {r.key: (r.value or "") for r in rows}
    retention_enabled = _parse_bool(kv.get(_KEY_CHAT_RETENTION_ENABLED))
    schedule_enabled = _parse_bool(kv.get(_KEY_CHAT_CLEAR_SCHEDULE_ENABLED))
    retention_days = max(1, int(kv.get(_KEY_CHAT_RETENTION_DAYS, "180") or 180))
    schedule_hour = max(0, min(23, int(kv.get(_KEY_CHAT_CLEAR_SCHEDULE_HOUR, "4") or 4)))
    schedule_minute = max(0, min(59, int(kv.get(_KEY_CHAT_CLEAR_SCHEDULE_MINUTE, "0") or 0)))
    return {
        "retention_enabled": retention_enabled,
        "retention_days": retention_days,
        "clear_schedule_enabled": schedule_enabled,
        "clear_schedule_hour": schedule_hour,
        "clear_schedule_minute": schedule_minute,
        "cleanup_active": retention_enabled and schedule_enabled,
        "schedule_timezone": server_timezone_label(),
    }


async def set_chat_retention_settings(
    db: AsyncSession,
    *,
    retention_enabled: bool | None = None,
    retention_days: int | None = None,
    clear_schedule_enabled: bool | None = None,
    clear_schedule_hour: int | None = None,
    clear_schedule_minute: int | None = None,
) -> dict[str, Any]:
    updates: dict[str, str] = {}
    if retention_enabled is not None:
        updates[_KEY_CHAT_RETENTION_ENABLED] = "true" if retention_enabled else "false"
    if retention_days is not None:
        updates[_KEY_CHAT_RETENTION_DAYS] = str(max(1, retention_days))
    if clear_schedule_enabled is not None:
        updates[_KEY_CHAT_CLEAR_SCHEDULE_ENABLED] = "true" if clear_schedule_enabled else "false"
    if clear_schedule_hour is not None:
        updates[_KEY_CHAT_CLEAR_SCHEDULE_HOUR] = str(max(0, min(23, clear_schedule_hour)))
    if clear_schedule_minute is not None:
        updates[_KEY_CHAT_CLEAR_SCHEDULE_MINUTE] = str(max(0, min(59, clear_schedule_minute)))

    for key, val in updates.items():
        row = await db.get(SystemSetting, key)
        if row:
            row.value = val
        else:
            db.add(SystemSetting(key=key, value=val))
    await db.flush()
    return await get_chat_retention_settings(db)


async def chat_retention_stats(db: AsyncSession) -> dict[str, int]:
    session_count = (await db.execute(select(func.count()).select_from(ChatSession))).scalar() or 0
    message_count = (await db.execute(select(func.count()).select_from(ChatMessage))).scalar() or 0
    settings_data = await get_chat_retention_settings(db)
    expired_messages = 0
    held_expired_messages = 0
    if settings_data["retention_enabled"]:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=int(settings_data["retention_days"]))
        active_hold = _chat_message_has_active_legal_hold()
        expired_messages = (
            await db.execute(
                select(func.count())
                .select_from(ChatMessage)
                .where(
                    ChatMessage.created_at < cutoff,
                    ~active_hold,
                )
            )
        ).scalar() or 0
        held_expired_messages = (
            await db.execute(
                select(func.count())
                .select_from(ChatMessage)
                .where(
                    ChatMessage.created_at < cutoff,
                    active_hold,
                )
            )
        ).scalar() or 0
    return {
        "total_sessions": int(session_count),
        "total_messages": int(message_count),
        "expired_messages": int(expired_messages),
        "held_expired_messages": int(held_expired_messages),
    }


async def _sync_affected_session_stats(db: AsyncSession, session_ids: set[str]) -> None:
    if not session_ids:
        return
    conn = await db.connection()
    dialect = conn.dialect.name
    ids = list(session_ids)
    if dialect == "postgresql":
        await db.execute(
            text(
                """
                UPDATE chat_sessions AS cs SET
                    message_count = COALESCE(sub.cnt, 0),
                    last_message_at = sub.last_at
                FROM (
                    SELECT session_id, COUNT(*)::int AS cnt, MAX(created_at) AS last_at
                    FROM chat_messages
                    WHERE session_id = ANY(:ids)
                    GROUP BY session_id
                ) AS sub
                WHERE cs.id = sub.session_id
                """
            ),
            {"ids": ids},
        )
        empty_ids = set(ids) - set(
            (await db.execute(select(ChatMessage.session_id).where(ChatMessage.session_id.in_(ids)).distinct()))
            .scalars()
            .all()
        )
        if empty_ids:
            await db.execute(
                text(
                    """
                    UPDATE chat_sessions SET message_count = 0, last_message_at = NULL
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": list(empty_ids)},
            )
    else:
        for session_id in ids:
            row = await db.get(ChatSession, session_id)
            if row is None:
                continue
            count = (
                await db.execute(
                    select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id)
                )
            ).scalar() or 0
            last_at = (
                await db.execute(select(func.max(ChatMessage.created_at)).where(ChatMessage.session_id == session_id))
            ).scalar()
            row.message_count = int(count)
            row.last_message_at = last_at
    await db.flush()


async def cleanup_empty_sessions_after_purge(db: AsyncSession, session_ids: set[str]) -> int:
    """Remove chat sessions that became empty after a retention purge."""
    if not session_ids:
        return 0
    rows = (
        (
            await db.execute(
                select(ChatSession).where(
                    ChatSession.id.in_(session_ids),
                    ChatSession.message_count == 0,
                    ChatSession.archived_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    removed = 0
    for row in rows:
        await db.delete(row)
        removed += 1
    if removed:
        await db.flush()
    return removed


async def purge_expired_chat_messages(
    db: AsyncSession,
    *,
    retention_days: int | None = None,
) -> dict[str, int]:
    settings_data = await get_chat_retention_settings(db)
    if not settings_data["retention_enabled"]:
        return {"removed_messages": 0, "retention_days": int(settings_data["retention_days"])}
    days = max(1, int(retention_days if retention_days is not None else settings_data["retention_days"]))
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    removed = 0
    affected: set[str] = set()
    active_hold = _chat_message_has_active_legal_hold()

    while True:
        batch_ids = (
            await db.execute(
                select(ChatMessage.id, ChatMessage.session_id)
                .where(
                    ChatMessage.created_at < cutoff,
                    ~active_hold,
                )
                .limit(_PURGE_BATCH_SIZE)
            )
        ).all()
        if not batch_ids:
            break
        msg_ids = [row[0] for row in batch_ids]
        for _, sid in batch_ids:
            affected.add(sid)
        result = await db.execute(delete(ChatMessage).where(ChatMessage.id.in_(msg_ids)))
        removed += int(result.rowcount or 0)
        await db.flush()
        if len(batch_ids) < _PURGE_BATCH_SIZE:
            break

    if affected:
        await _sync_affected_session_stats(db, affected)
    removed_empty = await cleanup_empty_sessions_after_purge(db, affected)
    if removed or removed_empty:
        await append_governance_audit_event(
            db,
            event_type="governance.retention.chat.purged",
            resource_type="chat",
            outcome="success",
            payload={
                "retention_days": days,
                "removed_messages": removed,
                "removed_empty_sessions": removed_empty,
            },
        )
    logger.info(
        "Chat retention purge removed %s messages older than %s days; removed %s empty sessions",
        removed,
        days,
        removed_empty,
    )
    return {
        "removed_messages": removed,
        "retention_days": days,
        "removed_empty_sessions": removed_empty,
    }
