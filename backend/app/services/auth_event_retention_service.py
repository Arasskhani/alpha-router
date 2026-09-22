"""How long sign-in history is kept.

One window, not two. ``admin_log_retention_service`` next door blanks an
unbounded ``detail_json`` column early and keeps the row longer, because that
column can grow without limit and is the only part of an administrative event
that can. ``auth_events`` has no such column: every field on it is a short,
typed fact, and the longest — ``reason_detail`` — is capped at 2000 characters
of scrubbed provider text. There is nothing to redact ahead of the row, and
redacting would recreate the exact defect the table was made to fix (the
reason a sign-in failed aging out before the fact that it failed). So a row is
kept whole until the window passes, and then it goes.

The floor is 90 days rather than the 7 the administrative trail allows.
Sign-in records are the evidence an incident review reaches for first, and
the frameworks most installations are audited against ask for at least three
months of them online (PCI DSS 10.7 asks for twelve, three of them immediately
available; ISO 27001 A.12.4 does not name a number but expects one to be
justified). A default of a year satisfies both; the floor stops a typo from
quietly discarding the quarter an auditor will ask about.

Same posture as the administrative trail on the two things that matter:
saving a shorter window does not purge immediately (the nightly job does, so a
mistyped number can be noticed first), and the purge records itself in the
governance chain, which this module never prunes.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_event import AuthEvent
from app.models.system import SystemSetting

KEY_RETENTION_DAYS = "auth_log_retention_days"

DEFAULT_RETENTION_DAYS = 365
MIN_RETENTION_DAYS = 90
MAX_RETENTION_DAYS = 3650

#: Batched so a first run against a table that has never been pruned cannot
#: hold one enormous transaction open.
_PURGE_BATCH_SIZE = 5000


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def clamp_retention_days(value: Any, *, default: int = DEFAULT_RETENTION_DAYS) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, days))


async def get_retention_days(db: AsyncSession) -> int:
    row = await db.get(SystemSetting, KEY_RETENTION_DAYS)
    return clamp_retention_days(row.value if row else None)


async def get_auth_event_retention(db: AsyncSession) -> dict[str, Any]:
    """The block the Retention Policy page renders."""

    days = await get_retention_days(db)
    cutoff = _now() - datetime.timedelta(days=days)
    stored = int((await db.execute(select(func.count()).select_from(AuthEvent))).scalar_one() or 0)
    expiring = int(
        (
            await db.execute(select(func.count()).select_from(AuthEvent).where(AuthEvent.occurred_at < cutoff))
        ).scalar_one()
        or 0
    )
    return {
        "retention_days": days,
        "min_days": MIN_RETENTION_DAYS,
        "max_days": MAX_RETENTION_DAYS,
        "default_days": DEFAULT_RETENTION_DAYS,
        "stored_events": stored,
        "expiring_events": expiring,
    }


async def set_auth_event_retention_days(db: AsyncSession, days: int) -> dict[str, Any]:
    """Save the window. Does not purge; the nightly job applies it."""

    clamped = clamp_retention_days(days)
    row = await db.get(SystemSetting, KEY_RETENTION_DAYS)
    if row:
        row.value = str(clamped)
    else:
        db.add(SystemSetting(key=KEY_RETENTION_DAYS, value=str(clamped)))
    await db.flush()
    return await get_auth_event_retention(db)


async def purge_expired_auth_events(db: AsyncSession) -> dict[str, int]:
    """Delete rows past the window, in batches. Commits per batch.

    Backfilled rows are not special here: a carried-over sign-in from two
    years ago is exactly as old as its ``occurred_at`` says, and goes when a
    native row of that age would.
    """

    days = await get_retention_days(db)
    cutoff = _now() - datetime.timedelta(days=days)
    deleted = 0
    while True:
        ids = (
            (await db.execute(select(AuthEvent.id).where(AuthEvent.occurred_at < cutoff).limit(_PURGE_BATCH_SIZE)))
            .scalars()
            .all()
        )
        if not ids:
            break
        result = await db.execute(delete(AuthEvent).where(AuthEvent.id.in_(list(ids))))
        deleted += int(result.rowcount or 0)
        await db.commit()
        if len(ids) < _PURGE_BATCH_SIZE:
            break
    await db.commit()
    return {"retention_days": days, "events_deleted": deleted}
