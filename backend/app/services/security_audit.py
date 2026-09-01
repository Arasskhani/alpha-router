"""Append-only security settings audit log."""

from __future__ import annotations

import datetime
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import SecurityAuditEvent
from app.models.user import User


async def log_security_event(
    db: AsyncSession,
    *,
    actor: User | None,
    actor_ip: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        SecurityAuditEvent(
            actor_user_id=actor.id if actor else None,
            actor_ip=(actor_ip or "")[:64] or None,
            action=action[:64],
            resource_type=resource_type[:64],
            resource_id=(resource_id or None) and str(resource_id)[:64],
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
            created_at=datetime.datetime.utcnow(),
        )
    )
