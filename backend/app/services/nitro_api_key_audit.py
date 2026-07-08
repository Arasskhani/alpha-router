"""Audit log for admin gateway API key lifecycle."""

from __future__ import annotations

import datetime
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import NitroApiKey, NitroApiKeyAuditLog
from app.models.user import User

FIELD_LABELS: dict[str, str] = {
    "name": "Name",
    "owner_user_id": "Owner",
    "credit_limit_usd": "Credit limit (USD)",
    "reset_period": "Reset period",
    "expires_at": "Expiration",
    "is_active": "Active",
}


def _utc_now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _serialize_value(field: str, value: Any, owner_labels: dict[int, str] | None = None) -> Any:
    if field == "owner_user_id" and value is not None and owner_labels:
        return owner_labels.get(int(value), str(value))
    if field == "expires_at" and value is not None:
        if isinstance(value, datetime.datetime):
            return value.isoformat() + "Z"
        return str(value)
    if field == "expires_at" and value is None:
        return "Never"
    if field == "is_active":
        return bool(value)
    if field == "credit_limit_usd" and value is not None:
        return round(float(value), 4)
    return value


async def _owner_label_map(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    out: dict[int, str] = {}
    for u in rows:
        out[u.id] = u.email or u.username or str(u.id)
    return out


async def log_api_key_audit(
    db: AsyncSession,
    *,
    key: NitroApiKey,
    actor: User,
    action: str,
    changes: list[dict[str, Any]],
) -> None:
    if action == "updated" and not changes:
        return
    db.add(
        NitroApiKeyAuditLog(
            nitro_api_key_id=key.id,
            actor_user_id=actor.id,
            action=action,
            changes_json=json.dumps(changes, ensure_ascii=False),
            created_at=_utc_now(),
        )
    )


async def log_api_key_created(db: AsyncSession, *, key: NitroApiKey, actor: User, owner: User) -> None:
    owner_label = owner.email or owner.username
    changes = [
        {"field": "name", "label": FIELD_LABELS["name"], "new": key.name},
        {"field": "owner_user_id", "label": FIELD_LABELS["owner_user_id"], "new": owner_label},
        {
            "field": "credit_limit_usd",
            "label": FIELD_LABELS["credit_limit_usd"],
            "new": _serialize_value("credit_limit_usd", key.credit_limit_usd),
        },
        {"field": "reset_period", "label": FIELD_LABELS["reset_period"], "new": key.reset_period},
        {
            "field": "expires_at",
            "label": FIELD_LABELS["expires_at"],
            "new": _serialize_value("expires_at", key.expires_at),
        },
    ]
    await log_api_key_audit(db, key=key, actor=actor, action="created", changes=changes)


async def log_api_key_updated(
    db: AsyncSession,
    *,
    key: NitroApiKey,
    actor: User,
    before: dict[str, Any],
    after_patches: dict[str, Any],
) -> None:
    owner_ids = set()
    if before.get("owner_user_id"):
        owner_ids.add(int(before["owner_user_id"]))
    if after_patches.get("owner_user_id"):
        owner_ids.add(int(after_patches["owner_user_id"]))
    owner_labels = await _owner_label_map(db, owner_ids)

    changes: list[dict[str, Any]] = []
    for field, new_val in after_patches.items():
        old_val = before.get(field)
        old_s = _serialize_value(field, old_val, owner_labels)
        new_s = _serialize_value(field, new_val, owner_labels)
        if old_s != new_s:
            label = FIELD_LABELS.get(field, field)
            changes.append({"field": field, "label": label, "old": old_s, "new": new_s})

    await log_api_key_audit(db, key=key, actor=actor, action="updated", changes=changes)


async def log_api_key_status(db: AsyncSession, *, key: NitroApiKey, actor: User, enabled: bool) -> None:
    action = "enabled" if enabled else "disabled"
    changes = [
        {
            "field": "is_active",
            "label": FIELD_LABELS["is_active"],
            "old": not enabled,
            "new": enabled,
        }
    ]
    await log_api_key_audit(db, key=key, actor=actor, action=action, changes=changes)


async def fetch_api_key_changelog(
    db: AsyncSession,
    key_id: int,
    *,
    from_date: datetime.date | None = None,
    to_date: datetime.date | None = None,
) -> list[dict[str, Any]]:
    stmt = (
        select(NitroApiKeyAuditLog)
        .where(NitroApiKeyAuditLog.nitro_api_key_id == key_id)
        .order_by(NitroApiKeyAuditLog.created_at.desc())
    )
    if from_date is not None:
        start = datetime.datetime.combine(from_date, datetime.time.min)
        stmt = stmt.where(NitroApiKeyAuditLog.created_at >= start)
    if to_date is not None:
        end = datetime.datetime.combine(to_date + datetime.timedelta(days=1), datetime.time.min)
        stmt = stmt.where(NitroApiKeyAuditLog.created_at < end)
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


def touch_key_modified(key: NitroApiKey) -> None:
    key.updated_at = _utc_now()
