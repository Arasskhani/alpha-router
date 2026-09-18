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
    # Copied, not joined. Permanent deletion empties the ``users`` row rather
    # than removing it, so the id survives - but the username and email do not,
    # which is the same problem by a different route: an actor identified only
    # by id loses their name the moment their account is purged, taking the
    # answer to "who did this" with it.
    actor_username: str | None = None
    actor_email: str | None = None
    if actor is not None:
        actor_username = str(actor.username)[:255] if actor.username else None
        actor_email = str(actor.email)[:255] if actor.email else None

    db.add(
        SecurityAuditEvent(
            actor_user_id=actor.id if actor else None,
            actor_username=actor_username,
            actor_email=actor_email,
            actor_ip=(actor_ip or "")[:64] or None,
            action=action[:64],
            resource_type=resource_type[:64],
            resource_id=(resource_id or None) and str(resource_id)[:64],
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
            created_at=datetime.datetime.utcnow(),
        )
    )
