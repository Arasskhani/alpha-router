"""How long administrative audit events are kept, and in what form.

Two windows, because an audit row has two halves with very different value and
very different size.

The compliance-relevant half - who did what, to which resource, when, from
where - is a handful of short columns. It is the answer an auditor asks for and
it costs almost nothing to keep, so it is kept for a long time.

``detail_json`` is the other half: an unbounded ``Text`` column holding whatever
the call site chose to record. It is what makes an old event *useful* rather
than merely *countable*, and it is also the only part that can grow without
limit. So it is blanked first, on a shorter window, and ``detail_redacted_at``
marks that it happened - otherwise the viewer cannot tell "nothing was
recorded" from "the detail aged out", which are different answers.

Deliberately not hash-chained and not ORM-locked as append-only. The governance
audit table is hash-chained, and pruning any row of a hash chain makes every
later row fail verification - the two features are mutually exclusive, and a
table that must be prunable cannot also be a chain. An append-only ORM listener
would be worse than nothing here: ``before_delete`` fires on the ORM unit of
work and not on the Core ``delete()`` this module uses, so it would advertise a
guarantee it does not provide. What *is* recorded is the pruning itself, into
the chained governance table, which this module never prunes.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import SecurityAuditEvent
from app.models.system import SystemSetting

KEY_DETAIL_RETENTION_DAYS = "admin_logs_detail_retention_days"
KEY_EVENT_RETENTION_DAYS = "admin_logs_event_retention_days"

DEFAULT_DETAIL_RETENTION_DAYS = 90
DEFAULT_EVENT_RETENTION_DAYS = 365
MIN_RETENTION_DAYS = 7
MAX_RETENTION_DAYS = 3650

#: Batched so a first run against a table that has never been pruned cannot
#: hold one enormous transaction open.
_PURGE_BATCH_SIZE = 5000


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def clamp_retention_days(value: Any, *, default: int) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, days))


async def _setting(db: AsyncSession, key: str, default: int) -> int:
    row = await db.get(SystemSetting, key)
    return clamp_retention_days(row.value if row else None, default=default)


async def get_detail_retention_days(db: AsyncSession) -> int:
    return await _setting(db, KEY_DETAIL_RETENTION_DAYS, DEFAULT_DETAIL_RETENTION_DAYS)


async def get_event_retention_days(db: AsyncSession) -> int:
    return await _setting(db, KEY_EVENT_RETENTION_DAYS, DEFAULT_EVENT_RETENTION_DAYS)


async def get_admin_log_retention(db: AsyncSession) -> dict[str, Any]:
    """The block the Retention Policy page renders."""
    detail_days = await get_detail_retention_days(db)
    event_days = await get_event_retention_days(db)
    stored = int((await db.execute(select(func.count()).select_from(SecurityAuditEvent))).scalar_one() or 0)
    detail_cutoff = _now() - datetime.timedelta(days=detail_days)
    event_cutoff = _now() - datetime.timedelta(days=event_days)
    expiring_details = int(
        (
            await db.execute(
                select(func.count())
                .select_from(SecurityAuditEvent)
                .where(
                    SecurityAuditEvent.detail_redacted_at.is_(None),
                    SecurityAuditEvent.created_at < detail_cutoff,
                )
            )
        ).scalar_one()
        or 0
    )
    expiring_events = int(
        (
            await db.execute(
                select(func.count()).select_from(SecurityAuditEvent).where(SecurityAuditEvent.created_at < event_cutoff)
            )
        ).scalar_one()
        or 0
    )
    return {
        "detail_retention_days": detail_days,
        "event_retention_days": event_days,
        "min_days": MIN_RETENTION_DAYS,
        "max_days": MAX_RETENTION_DAYS,
        "default_detail_days": DEFAULT_DETAIL_RETENTION_DAYS,
        "default_event_days": DEFAULT_EVENT_RETENTION_DAYS,
        "stored_events": stored,
        "expiring_details": expiring_details,
        "expiring_events": expiring_events,
    }


async def set_admin_log_retention(
    db: AsyncSession,
    *,
    detail_retention_days: int | None = None,
    event_retention_days: int | None = None,
) -> dict[str, Any]:
    """Save either window. The detail window is never allowed to outlive the
    row window, because blanking detail on a row that is about to be deleted
    anyway is meaningless and the inverted pair reads as a configuration bug."""
    detail_days = (
        clamp_retention_days(detail_retention_days, default=DEFAULT_DETAIL_RETENTION_DAYS)
        if detail_retention_days is not None
        else await get_detail_retention_days(db)
    )
    event_days = (
        clamp_retention_days(event_retention_days, default=DEFAULT_EVENT_RETENTION_DAYS)
        if event_retention_days is not None
        else await get_event_retention_days(db)
    )
    detail_days = min(detail_days, event_days)

    for key, value in ((KEY_DETAIL_RETENTION_DAYS, detail_days), (KEY_EVENT_RETENTION_DAYS, event_days)):
        row = await db.get(SystemSetting, key)
        if row:
            row.value = str(value)
        else:
            db.add(SystemSetting(key=key, value=str(value)))
    await db.flush()
    return await get_admin_log_retention(db)


async def purge_expired_admin_logs(db: AsyncSession) -> dict[str, int]:
    """Blank aged detail, then delete rows past the longer window.

    Order matters only for the reported counts: a row deleted by the second
    step is not also counted as redacted by the first, because the detail
    window is clamped to be no longer than the row window.
    """
    detail_days = await get_detail_retention_days(db)
    event_days = await get_event_retention_days(db)
    now = _now()

    redacted = await db.execute(
        update(SecurityAuditEvent)
        .where(
            SecurityAuditEvent.detail_redacted_at.is_(None),
            SecurityAuditEvent.created_at < now - datetime.timedelta(days=detail_days),
        )
        .values(detail_json=None, detail_redacted_at=now)
    )

    event_cutoff = now - datetime.timedelta(days=event_days)
    deleted = 0
    while True:
        ids = (
            (
                await db.execute(
                    select(SecurityAuditEvent.id)
                    .where(SecurityAuditEvent.created_at < event_cutoff)
                    .limit(_PURGE_BATCH_SIZE)
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        result = await db.execute(delete(SecurityAuditEvent).where(SecurityAuditEvent.id.in_(list(ids))))
        deleted += int(result.rowcount or 0)
        await db.commit()
        if len(ids) < _PURGE_BATCH_SIZE:
            break

    await db.commit()
    return {
        "detail_retention_days": detail_days,
        "event_retention_days": event_days,
        "details_redacted": int(redacted.rowcount or 0),
        "events_deleted": deleted,
    }
