"""Audit log for provider connection lifecycle."""

from __future__ import annotations

import datetime
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection, ConnectionAuditLog
from app.models.user import User

FIELD_LABELS: dict[str, str] = {
    "name": "Name",
    "provider_type": "Provider",
    "base_url": "Base URL",
    "sync_interval_hours": "Sync interval (hours)",
    "is_active": "Active",
}


def _utc_now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _serialize_value(field: str, value: Any) -> Any:
    if field == "is_active":
        return bool(value)
    if field == "sync_interval_hours" and value is not None:
        return int(value)
    if field == "base_url" and not value:
        return "(default)"
    return value


def connection_snapshot(conn: Connection) -> dict[str, Any]:
    return {
        "name": conn.name,
        "provider_type": conn.provider_type,
        "base_url": conn.base_url or "",
        "sync_interval_hours": conn.sync_interval_hours,
        "is_active": conn.is_active,
    }


async def log_connection_audit(
    db: AsyncSession,
    *,
    conn: Connection,
    actor: User | None,
    action: str,
    changes: list[dict[str, Any]],
) -> None:
    if action == "updated" and not changes:
        return
    db.add(
        ConnectionAuditLog(
            connection_id=conn.id,
            actor_user_id=actor.id if actor else None,
            action=action,
            changes_json=json.dumps(changes, ensure_ascii=False),
            created_at=_utc_now(),
        )
    )


async def log_connection_created(db: AsyncSession, *, conn: Connection, actor: User) -> None:
    snap = connection_snapshot(conn)
    changes = [
        {"field": field, "label": FIELD_LABELS.get(field, field), "new": _serialize_value(field, snap[field])}
        for field in snap
    ]
    await log_connection_audit(db, conn=conn, actor=actor, action="created", changes=changes)


async def log_connection_updated(
    db: AsyncSession,
    *,
    conn: Connection,
    actor: User,
    before: dict[str, Any],
    after_patches: dict[str, Any],
) -> None:
    changes: list[dict[str, Any]] = []
    for field, new_val in after_patches.items():
        old_val = before.get(field)
        old_s = _serialize_value(field, old_val)
        new_s = _serialize_value(field, new_val)
        if old_s != new_s:
            changes.append(
                {
                    "field": field,
                    "label": FIELD_LABELS.get(field, field),
                    "old": old_s,
                    "new": new_s,
                }
            )
    await log_connection_audit(db, conn=conn, actor=actor, action="updated", changes=changes)


async def log_connection_status(db: AsyncSession, *, conn: Connection, actor: User, enabled: bool) -> None:
    action = "enabled" if enabled else "disabled"
    changes = [
        {
            "field": "is_active",
            "label": FIELD_LABELS["is_active"],
            "old": not enabled,
            "new": enabled,
        }
    ]
    await log_connection_audit(db, conn=conn, actor=actor, action=action, changes=changes)


async def fetch_connection_changelog(
    db: AsyncSession,
    connection_id: int,
    *,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
) -> list[dict[str, Any]]:
    stmt = (
        select(ConnectionAuditLog)
        .where(ConnectionAuditLog.connection_id == connection_id)
        .order_by(ConnectionAuditLog.created_at.desc())
    )
    if from_date is not None:
        start = datetime.datetime.combine(from_date, datetime.time.min)
        stmt = stmt.where(ConnectionAuditLog.created_at >= start)
    if to_date is not None:
        end = datetime.datetime.combine(to_date + datetime.timedelta(days=1), datetime.time.min)
        stmt = stmt.where(ConnectionAuditLog.created_at < end)
    rows = (await db.execute(stmt)).scalars().all()
    actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    actors: dict[int, User] = {}
    if actor_ids:
        actor_rows = (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
        actors = {u.id: u for u in actor_rows}

    out: list[dict[str, Any]] = []
    for r in rows:
        actor = actors.get(r.actor_user_id) if r.actor_user_id else None
        try:
            changes = json.loads(r.changes_json or "[]")
        except json.JSONDecodeError:
            changes = []
        out.append(
            {
                "id": r.id,
                "action": r.action,
                "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
                "actor": (
                    {
                        "id": actor.id,
                        "username": actor.username,
                        "email": actor.email,
                        "display_name": actor.display_name,
                    }
                    if actor
                    else None
                ),
                "changes": changes,
            }
        )
    return out


def touch_connection_modified(conn: Connection) -> None:
    conn.updated_at = _utc_now()
