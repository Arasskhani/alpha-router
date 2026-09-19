"""Read the administrative audit trail.

``security_audit_events`` has been written to since the security settings
shipped and never once read back: there was no endpoint and no page, so the
only way to answer "who changed this" was direct database access. The Admin
Guide already told operators the trail existed, which made it a promise the
product could not keep.

Filters are deliberately the four an investigation actually starts from - a
date range, a person, a kind of action, and a kind of resource - and each one
is backed by an index added alongside this module.

The page first read the security trail alone. The product writes seven more
(agents, tools, knowledge, governance, projects, API keys, connections), each
to its own table, and an investigation should not have to know which. They
are read through :mod:`app.services.admin_log_union`, one normalised shape
over all of them; ``source`` picks a trail or ``all``.
"""

from __future__ import annotations

import datetime
import json
import time
from collections.abc import Sequence
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_api_logs
from app.database import get_db
from app.models.user import User
from app.services import admin_log_union

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


class _AuditRecord(Protocol):
    """What a row of the normalised union looks like to this module.

    Both a ``Row`` from :func:`app.services.admin_log_union.union_for` and any
    object carrying the same attributes satisfy it.
    """

    source: str
    id: str
    created_at: datetime.datetime | None
    actor_user_id: int | None
    actor_username: str | None
    actor_email: str | None
    actor_ip: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    detail: str | None
    outcome: str | None
    detail_redacted_at: datetime.datetime | None


async def _resolve_legacy_actors(db: AsyncSession, events: Sequence[Any]) -> dict[int, tuple[str, str | None]]:
    """Names for the actors of rows that carry only ``actor_user_id``.

    Security rows written before the identity columns existed, and every row
    of the other trails (none of which stores a copy of the name), would
    otherwise show "User #2" where the page should show a person. The account
    is usually still there - ``users`` also holds soft-deleted accounts, and
    only a permanent delete removes the row - so the name can be looked up.

    This is a best-effort lookup, not the stored copy: it reads the account's
    name *now*, and it stops working once the account is permanently deleted.
    Security events written from here on carry their own copy.
    """
    ids = {e.actor_user_id for e in events if e.actor_username is None and e.actor_user_id is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username, User.email).where(User.id.in_(ids)))).all()
    return {int(uid): (username, email) for uid, username, email in rows}


def _parse_detail(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # A row written by an older or hand-edited path should still be listed;
        # showing the raw string beats dropping the event from the trail.
        return {"_unparsed": raw}


def _row(event: _AuditRecord, resolved: dict[int, tuple[str, str | None]]) -> dict[str, Any]:
    # The copy on the row wins: it is what was true at the time, and it survives
    # the account being deleted. The live lookup only fills rows without one.
    fallback = resolved.get(event.actor_user_id) if event.actor_user_id is not None else None
    return {
        "source": event.source,
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
        "detail": _parse_detail(event.detail),
        "outcome": event.outcome,
        "detail_redacted_at": event.detail_redacted_at.isoformat() if event.detail_redacted_at else None,
    }


def _sources_or_400(source: str | None) -> list[str]:
    try:
        return admin_log_union.source_keys(source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown audit source '{source}'.") from exc


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
    source: str | None = Query(default=None, max_length=32),
) -> dict[str, Any]:
    """One page of the audit trail(s) named by ``source``.

    ``source`` is a trail key from :data:`app.services.admin_log_union.SOURCES`
    or ``all``. Left out, it is the security trail alone - exactly what the
    endpoint returned before the other trails were wired in.
    """
    audit = admin_log_union.union_for(_sources_or_400(source))
    stmt = admin_log_union.apply_filters(
        audit,
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
        await db.execute(stmt.order_by(audit.c.created_at.desc(), audit.c.id.desc()).offset(offset).limit(limit + 1))
    ).all()
    # One extra row is fetched purely to answer "is there a next page" without
    # a second COUNT over tables that have no bound on their size.
    has_more = len(rows) > limit
    page = rows[:limit]
    resolved = await _resolve_legacy_actors(db, page)
    return {
        "items": [_row(event, resolved) for event in page],
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }


#: How long the filter panel's answer is reused. The values behind it are a
#: handful of action names, resource types and administrator names, and they
#: change when somebody is given a role - not between two clicks. Without this
#: every open of the panel is four DISTINCT scans of every audit table.
FILTER_OPTIONS_CACHE_TTL_SECONDS = 60

_filter_options_cache: dict[tuple[str, ...], tuple[float, dict[str, list[str]]]] = {}


def reset_filter_options_cache() -> None:
    """Drop the cached panels. Called by tests; harmless in production."""

    _filter_options_cache.clear()


@router.get("/filter-options")
async def admin_log_filter_options(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_logs),
    source: str | None = Query(default=None, max_length=32),
) -> dict[str, list[str]]:
    """Distinct values for the comboboxes, so an operator picks rather than guesses.

    Scoped to the same ``source`` as the list, so the panel never offers an
    action the trail on screen cannot contain.
    """
    keys = tuple(_sources_or_400(source))
    now = time.monotonic()
    cached = _filter_options_cache.get(keys)
    if cached is not None and now - cached[0] < FILTER_OPTIONS_CACHE_TTL_SECONDS:
        return cached[1]

    audit = admin_log_union.union_for(list(keys))
    actions = (await db.execute(select(audit.c.action).distinct().order_by(audit.c.action))).scalars().all()
    resources = (
        (await db.execute(select(audit.c.resource_type).distinct().order_by(audit.c.resource_type))).scalars().all()
    )
    recorded = (
        (await db.execute(select(audit.c.actor_username).where(audit.c.actor_username.isnot(None)).distinct()))
        .scalars()
        .all()
    )
    # Rows that name their actor only by id are resolved to a live name in the
    # list. Offer those names here too, or the combobox omits exactly the
    # administrators the operator can see on screen.
    legacy = (
        (
            await db.execute(
                select(User.username)
                .distinct()
                .where(
                    User.id.in_(
                        select(audit.c.actor_user_id).where(
                            audit.c.actor_username.is_(None), audit.c.actor_user_id.isnot(None)
                        )
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    options = {
        "sources": list(keys),
        "actions": [a for a in actions if a],
        "resource_types": [r for r in resources if r],
        "actors": sorted({a for a in [*recorded, *legacy] if a}),
    }
    _filter_options_cache[keys] = (now, options)
    return options
