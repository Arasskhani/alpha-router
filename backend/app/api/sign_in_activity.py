"""Read and export the sign-in history.

Every row is a fact about a person — that they signed in, from which address,
that someone failed to sign in as them — so the three things an operator can
do here are all reads, all behind the ``sign_in_activity`` menu, and the one
that leaves the building (the CSV) is written to the administrative trail
with the filter that produced it and the number of rows it carried.

Filters are the ones an investigation starts from: a person, a kind of event,
how it ended, why, from where, and when. Each is backed by an index on
``auth_events``. Free text is accepted only for the username prefix and the
address; everything else must be a value from the catalogue the model
declares, so a typo is a 400 and not an empty page.

The filter panel offers the catalogue, not a DISTINCT over the table: the
values are a fixed product decision (see ``app.models.auth_event``), the UI
owns their labels, and the table has no bound on its size.
"""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_logs import _parse_date
from app.api.deps import require_sign_in_activity
from app.database import get_db
from app.models.auth_event import (
    AUTH_METHODS,
    EVENT_TYPES,
    OUTCOME_FAILURE,
    OUTCOME_NONE,
    OUTCOME_SUCCESS,
    REASON_CODES,
    AuthEvent,
)
from app.models.user import User

router = APIRouter(prefix="/api/admin/sign-in-activity", tags=["sign-in-activity"])

#: One screenful at a time; the same ceiling the other log viewers use.
MAX_PAGE = 500

#: The export is bounded. Above this the file is no longer something a person
#: opens in a spreadsheet, and an unbounded scan because a caller asked is the
#: one thing a log endpoint must never do. The response says when it was cut.
EXPORT_MAX_ROWS = 50_000
_EXPORT_BATCH = 2_000

OUTCOMES: tuple[str, ...] = (OUTCOME_SUCCESS, OUTCOME_FAILURE, OUTCOME_NONE)


def _one_of(value: str | None, allowed: tuple[str, ...], *, name: str) -> str | None:
    if value is None or value == "":
        return None
    if value not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown {name} '{value}'.")
    return value


def _clean(value: str | None, *, limit: int) -> str | None:
    text = (value or "").strip()
    return text[:limit] or None


class Filters:
    """The filter set, validated once, applied to the list, the export and the audit row alike."""

    def __init__(
        self,
        *,
        user_id: int | None,
        username: str | None,
        event_type: str | None,
        outcome: str | None,
        reason_code: str | None,
        auth_method: str | None,
        ip: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> None:
        self.user_id = user_id
        self.username = _clean(username, limit=255)
        self.event_type = _one_of(event_type, EVENT_TYPES, name="event type")
        self.outcome = _one_of(outcome, OUTCOMES, name="outcome")
        self.reason_code = _one_of(reason_code, REASON_CODES, name="reason code")
        self.auth_method = _one_of(auth_method, AUTH_METHODS, name="auth method")
        self.ip = _clean(ip, limit=64)
        self.start = _parse_date(start_date)
        self.end = _parse_date(end_date, end_of_day=True)
        if self.start and self.end and self.start > self.end:
            raise HTTPException(status_code=400, detail="start_date is after end_date.")

    def apply(self, stmt: Select) -> Select:
        if self.user_id is not None:
            stmt = stmt.where(AuthEvent.user_id == self.user_id)
        if self.username:
            # Prefix, case-insensitive: the operator types the start of a name.
            # The LIKE argument is escaped so a typed % or _ is a character.
            needle = self.username.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(func.lower(AuthEvent.username).like(f"{needle}%", escape="\\"))
        if self.event_type:
            stmt = stmt.where(AuthEvent.event_type == self.event_type)
        if self.outcome:
            stmt = stmt.where(AuthEvent.outcome == self.outcome)
        if self.reason_code:
            stmt = stmt.where(AuthEvent.reason_code == self.reason_code)
        if self.auth_method:
            stmt = stmt.where(AuthEvent.auth_method == self.auth_method)
        if self.ip:
            stmt = stmt.where(AuthEvent.ip == self.ip)
        if self.start:
            stmt = stmt.where(AuthEvent.occurred_at >= self.start)
        if self.end:
            stmt = stmt.where(AuthEvent.occurred_at <= self.end)
        return stmt

    def as_dict(self) -> dict[str, Any]:
        """What the audit row records about an export: the filter, not the rows."""
        return {
            key: value
            for key, value in {
                "user_id": self.user_id,
                "username": self.username,
                "event_type": self.event_type,
                "outcome": self.outcome,
                "reason_code": self.reason_code,
                "auth_method": self.auth_method,
                "ip": self.ip,
                "start_date": self.start.date().isoformat() if self.start else None,
                "end_date": self.end.date().isoformat() if self.end else None,
            }.items()
            if value is not None
        }


def filters_from_query(
    user_id: int | None = Query(default=None, ge=1),
    username: str | None = Query(default=None, max_length=255),
    event_type: str | None = Query(default=None, max_length=32),
    outcome: str | None = Query(default=None, max_length=16),
    reason_code: str | None = Query(default=None, max_length=48),
    auth_method: str | None = Query(default=None, max_length=16),
    ip: str | None = Query(default=None, max_length=64),
    start_date: str | None = Query(default=None, max_length=10),
    end_date: str | None = Query(default=None, max_length=10),
) -> Filters:
    return Filters(
        user_id=user_id,
        username=username,
        event_type=event_type,
        outcome=outcome,
        reason_code=reason_code,
        auth_method=auth_method,
        ip=ip,
        start_date=start_date,
        end_date=end_date,
    )


def _iso(value: datetime.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _row(event: AuthEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "occurred_at": _iso(event.occurred_at),
        "user_id": event.user_id,
        "username": event.username,
        "event_type": event.event_type,
        "outcome": event.outcome,
        "scope": event.scope,
        "reason_code": event.reason_code,
        "reason_detail": event.reason_detail,
        "auth_method": event.auth_method,
        "ip": event.ip,
        "user_agent": event.user_agent,
        "session_id": event.session_id,
        "correlation_id": event.correlation_id,
        "backfilled": bool(event.backfilled),
    }


def _ordered(stmt: Select) -> Select:
    # id descending as the tiebreaker: several events can share a timestamp,
    # and a paged view ordered only by time can repeat or skip a row.
    return stmt.order_by(AuthEvent.occurred_at.desc(), AuthEvent.id.desc())


@router.get("")
async def list_sign_in_activity(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_sign_in_activity),
    filters: Filters = Depends(filters_from_query),
    limit: int = Query(100, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """One page, newest first. ``has_more`` without a COUNT over an unbounded table."""

    stmt = _ordered(filters.apply(select(AuthEvent))).offset(offset).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [_row(event) for event in rows[:limit]],
        "limit": limit,
        "offset": offset,
        "has_more": len(rows) > limit,
    }


@router.get("/filter-options")
async def sign_in_activity_filter_options(
    _: User = Depends(require_sign_in_activity),
) -> dict[str, list[str]]:
    """The catalogue the comboboxes offer. Fixed; no query."""

    return {
        "event_types": list(EVENT_TYPES),
        "outcomes": list(OUTCOMES),
        "reason_codes": list(REASON_CODES),
        "auth_methods": list(AUTH_METHODS),
    }


@router.get("/export.csv")
async def export_sign_in_activity(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_sign_in_activity),
    filters: Filters = Depends(filters_from_query),
) -> StreamingResponse:
    """The page's rows as a file, with the page's filters.

    Written to the administrative trail *before* the first byte goes out: the
    record has to exist even if the client disconnects mid-download, and it
    has to say what left — the filter and the row count — not who was in it.

    Bounded at :data:`EXPORT_MAX_ROWS`; ``X-Truncated`` says whether the
    bound was hit, and the audit row carries the same flag.
    """
    from app.services.client_ip import resolve_client_ip
    from app.services.security_audit import log_security_event

    # Cheap on the indexed filters, and it lets the header be honest before
    # the body starts: a count capped one past the bound.
    capped = filters.apply(select(AuthEvent.id)).limit(EXPORT_MAX_ROWS + 1).subquery()
    matched = int((await db.execute(select(func.count()).select_from(capped))).scalar_one() or 0)
    truncated = matched > EXPORT_MAX_ROWS
    exported = min(matched, EXPORT_MAX_ROWS)

    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action="sign_in_activity_exported",
        resource_type="auth_events",
        detail={"filters": filters.as_dict(), "rows": exported, "truncated": truncated},
    )
    await db.commit()

    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        _csv_pages(filters, exported),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="alpharouter-sign-in-activity-{stamp}.csv"',
            "X-Truncated": "true" if truncated else "false",
            "X-Row-Count": str(exported),
        },
    )


CSV_COLUMNS: tuple[str, ...] = (
    "Time (UTC)",
    "User",
    "User ID",
    "Event",
    "Outcome",
    "Scope",
    "Method",
    "IP",
    "Reason",
    "Detail",
    "User Agent",
    "Session ID",
    "Correlation ID",
    "Backfilled",
)


def _cell(value: Any) -> str:
    """A spreadsheet-safe cell.

    ``=``, ``+``, ``-``, ``@`` and the tab/CR characters at the start of a
    cell are read by spreadsheet software as a formula. A user agent or a
    typed username is attacker-controlled text and this file is opened by an
    administrator, so those cells are prefixed with an apostrophe (the
    spreadsheet convention for "this is text").
    """
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def csv_header() -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerow(CSV_COLUMNS)
    return buffer.getvalue()


def csv_rows(events: list[AuthEvent]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for event in events:
        writer.writerow(
            [
                _iso(event.occurred_at) or "",
                _cell(event.username),
                event.user_id if event.user_id is not None else "",
                event.event_type,
                event.outcome,
                event.scope or "",
                event.auth_method or "",
                _cell(event.ip),
                event.reason_code or "",
                _cell(event.reason_detail),
                _cell(event.user_agent),
                _cell(event.session_id),
                _cell(event.correlation_id),
                "yes" if event.backfilled else "no",
            ]
        )
    return buffer.getvalue()


async def _csv_pages(filters: Filters, total: int) -> AsyncIterator[bytes]:
    """Stream in batches from a session of its own, so the file does not depend
    on the request's session outliving the response."""
    from app.database import AsyncSessionLocal

    yield ("﻿" + csv_header()).encode("utf-8")
    remaining = total
    offset = 0
    async with AsyncSessionLocal() as db:
        while remaining > 0:
            batch = min(_EXPORT_BATCH, remaining)
            stmt = _ordered(filters.apply(select(AuthEvent))).offset(offset).limit(batch)
            events = list((await db.execute(stmt)).scalars().all())
            if not events:
                break
            yield csv_rows(events).encode("utf-8")
            offset += len(events)
            remaining -= len(events)
            if len(events) < batch:
                break


@router.get("/{event_id}")
async def get_sign_in_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_sign_in_activity),
) -> dict[str, Any]:
    """One event in full, with the account as it is *now* beside the snapshot."""

    event = await db.get(AuthEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Sign-in event not found")
    account: dict[str, Any] | None = None
    if event.user_id is not None:
        user = await db.get(User, event.user_id)
        if user is not None:
            account = {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "auth_provider": user.auth_provider,
                "is_active": bool(user.is_active),
                "deleted_at": _iso(user.deleted_at),
                "purged_at": _iso(getattr(user, "purged_at", None)),
            }
    return {**_row(event), "user": account}
