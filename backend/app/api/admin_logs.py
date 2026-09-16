"""Read the administrative audit trail.

``security_audit_events`` has been written to since the security settings
shipped and never once read back: there was no endpoint and no page, so the
only way to answer "who changed this" was direct database access. The Admin
Guide already told operators the trail existed, which made it a promise the
product could not keep.

Filters are deliberately the four an investigation actually starts from - a
date range, a person, a kind of action, and a kind of resource - and each one
is backed by an index added alongside this module.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_api_logs
from app.database import get_db
from app.models.security import SecurityAuditEvent
from app.models.user import User

router = APIRouter(prefix="/api/admin/admin-logs", tags=["admin-logs"])

#: The same ceiling the request-log viewer uses, for the same reason: one
#: screenful at a time, and never an unbounded scan because a caller asked.
MAX_PAGE = 500


def _parse_date(value: str | None, *, end_of_day: bool = False) -> datetime.datetime | None:
    """``YYYY-MM-DD`` to a naive-UTC bound, or a 400.

    The request-log endpoint parses its dates with a bare ``strptime`` and
    turns a typo into a 500; a filter the operator typed is a client error.
    """
    if not value:
        return None
    try:
        parsed = datetime.datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc
    return parsed.replace(hour=23, minute=59, second=59) if end_of_day else parsed


def _row(event: SecurityAuditEvent) -> dict[str, Any]:
    try:
        detail = json.loads(event.detail_json) if event.detail_json else None
    except (TypeError, ValueError):
        # A row written by an older or hand-edited path should still be listed;
        # showing the raw string beats dropping the event from the trail.
        detail = {"_unparsed": event.detail_json}
    return {
        "id": event.id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "actor_user_id": event.actor_user_id,
        # Falls back to the live id only when the row predates the identity
        # columns; a deleted actor keeps the name recorded at the time.
        "actor_username": event.actor_username,
        "actor_email": event.actor_email,
        "actor_ip": event.actor_ip,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "detail": detail,
        "detail_redacted_at": event.detail_redacted_at.isoformat() if event.detail_redacted_at else None,
    }


def _apply_filters(
    stmt,
    *,
    actor: str | None,
    action: str | None,
    resource_type: str | None,
    start: datetime.datetime | None,
    end: datetime.datetime | None,
):
    if actor:
        term = actor.strip()
        if term:
            stmt = stmt.where(SecurityAuditEvent.actor_username.ilike(f"%{term}%"))
    if action:
        stmt = stmt.where(SecurityAuditEvent.action == action.strip())
    if resource_type:
        stmt = stmt.where(SecurityAuditEvent.resource_type == resource_type.strip())
    if start:
        stmt = stmt.where(SecurityAuditEvent.created_at >= start)
    if end:
        stmt = stmt.where(SecurityAuditEvent.created_at <= end)
    return stmt


@router.get("")
async def list_admin_logs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
    limit: int = Query(100, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    actor: str | None = Query(default=None, max_length=255),
    action: str | None = Query(default=None, max_length=64),
    resource_type: str | None = Query(default=None, max_length=64),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
) -> dict[str, Any]:
    stmt = _apply_filters(
        select(SecurityAuditEvent),
        actor=actor,
        action=action,
        resource_type=resource_type,
        start=_parse_date(start_date),
        end=_parse_date(end_date, end_of_day=True),
    )
    # id descending as the tiebreaker: several events can share a timestamp to
    # the microsecond, and a paged view that orders only by time can repeat or
    # skip a row between pages.
    rows = (
        (
            await db.execute(
                stmt.order_by(SecurityAuditEvent.created_at.desc(), SecurityAuditEvent.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    # One extra row is fetched purely to answer "is there a next page" without
    # a second COUNT over a table that has no bound on its size.
    has_more = len(rows) > limit
    return {
        "items": [_row(event) for event in rows[:limit]],
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }


@router.get("/filter-options")
async def admin_log_filter_options(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
) -> dict[str, list[str]]:
    """Distinct values for the comboboxes, so an operator picks rather than guesses."""
    actions = (
        (await db.execute(select(SecurityAuditEvent.action).distinct().order_by(SecurityAuditEvent.action)))
        .scalars()
        .all()
    )
    resources = (
        (
            await db.execute(
                select(SecurityAuditEvent.resource_type).distinct().order_by(SecurityAuditEvent.resource_type)
            )
        )
        .scalars()
        .all()
    )
    actors = (
        (
            await db.execute(
                select(SecurityAuditEvent.actor_username)
                .where(SecurityAuditEvent.actor_username.isnot(None))
                .distinct()
                .order_by(SecurityAuditEvent.actor_username)
            )
        )
        .scalars()
        .all()
    )
    return {
        "actions": [a for a in actions if a],
        "resource_types": [r for r in resources if r],
        "actors": [a for a in actors if a],
    }
