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
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
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


async def _resolve_legacy_actors(
    db: AsyncSession, events: Sequence[SecurityAuditEvent]
) -> dict[int, tuple[str, str | None]]:
    """Names for the actors of rows written before the identity columns existed.

    Those rows carry only ``actor_user_id``, so the trail showed "User #2" where
    it should show a person. The account is usually still there - ``users`` also
    holds soft-deleted accounts, and only a permanent delete removes the row -
    so the name can be looked up and shown.

    This is a best-effort lookup, not the stored copy: it reads the account's
    name *now*, and it stops working once the account is permanently deleted.
    Events written from here on carry their own copy and never depend on it.
    """
    ids = {e.actor_user_id for e in events if e.actor_username is None and e.actor_user_id is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username, User.email).where(User.id.in_(ids)))).all()
    return {int(uid): (username, email) for uid, username, email in rows}


def _row(event: SecurityAuditEvent, resolved: dict[int, tuple[str, str | None]]) -> dict[str, Any]:
    try:
        detail = json.loads(event.detail_json) if event.detail_json else None
    except (TypeError, ValueError):
        # A row written by an older or hand-edited path should still be listed;
        # showing the raw string beats dropping the event from the trail.
        detail = {"_unparsed": event.detail_json}
    # The copy on the row wins: it is what was true at the time, and it survives
    # the account being deleted. The live lookup only fills rows that predate it.
    fallback = resolved.get(event.actor_user_id) if event.actor_user_id is not None else None
    return {
        "id": event.id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "actor_user_id": event.actor_user_id,
        "actor_username": event.actor_username or (fallback[0] if fallback else None),
        "actor_email": event.actor_email or (fallback[1] if fallback else None),
        #: True when the name above was read from the account just now rather
        #: than recorded with the event, so a caller can tell the two apart.
        "actor_resolved_live": event.actor_username is None and fallback is not None,
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
            # The list resolves legacy rows to a live name, so filtering has to
            # find them by that name as well - otherwise typing the name the
            # table just showed you makes those rows disappear.
            legacy = select(User.id).where(User.username.ilike(f"%{term}%"))
            stmt = stmt.where(
                or_(
                    SecurityAuditEvent.actor_username.ilike(f"%{term}%"),
                    and_(
                        SecurityAuditEvent.actor_username.is_(None),
                        SecurityAuditEvent.actor_user_id.in_(legacy),
                    ),
                )
            )
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
    page = rows[:limit]
    resolved = await _resolve_legacy_actors(db, page)
    return {
        "items": [_row(event, resolved) for event in page],
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
    recorded = (
        (
            await db.execute(
                select(SecurityAuditEvent.actor_username)
                .where(SecurityAuditEvent.actor_username.isnot(None))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    # Rows that predate the identity columns name their actor only by id, and
    # the list resolves those to a live name. Offer those names here too, or the
    # combobox omits exactly the administrators the operator can see on screen.
    legacy = (
        (
            await db.execute(
                select(User.username)
                .distinct()
                .where(
                    User.id.in_(
                        select(SecurityAuditEvent.actor_user_id).where(
                            SecurityAuditEvent.actor_username.is_(None),
                            SecurityAuditEvent.actor_user_id.isnot(None),
                        )
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    return {
        "actions": [a for a in actions if a],
        "resource_types": [r for r in resources if r],
        "actors": sorted({a for a in [*recorded, *legacy] if a}),
    }
