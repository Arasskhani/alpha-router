"""Retention for ``request_logs`` - the one table that had none.

Five retention jobs already exist: media, user media, chat, admin logs and raw
provider payloads. ``request_logs`` is one row per API call, so it is the
fastest-growing table in the product, and nothing ever removed a row from it.
The API Logs page therefore gets slower forever, and the database grows without
bound on an installation nobody is watching.

Deleted in batches with a commit between them, the same shape
``admin_log_retention_service`` uses: one statement over a table this size holds
locks for minutes and bloats WAL, and a failure halfway would undo all of it.

This runs *after* ``ix_request_logs_user_time`` exists (revision e3c4d5f6a7b8).
A first purge against an unindexed table of this size is an outage.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.logging import RequestLog
from app.models.system import SystemSetting

KEY_RETENTION_DAYS = "request_log_retention_days"

#: Long enough that a month-end review still has the data, short enough that the
#: table stops being unbounded. An operator can change it.
DEFAULT_RETENTION_DAYS = 180
MIN_RETENTION_DAYS = 7
MAX_RETENTION_DAYS = 3650

#: Rows per statement. Small enough that a lock is never held long, large enough
#: that a big backlog still clears in a reasonable number of round trips.
PURGE_BATCH_SIZE = 5000


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def clamp_retention_days(value: Any) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS
    return max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, days))


async def get_retention_days(db: AsyncSession) -> int:
    row = await db.get(SystemSetting, KEY_RETENTION_DAYS)
    if row is None or not (row.value or "").strip():
        return DEFAULT_RETENTION_DAYS
    return clamp_retention_days(row.value)


async def set_retention_days(db: AsyncSession, days: Any) -> int:
    clamped = clamp_retention_days(days)
    row = await db.get(SystemSetting, KEY_RETENTION_DAYS)
    if row is None:
        db.add(SystemSetting(key=KEY_RETENTION_DAYS, value=str(clamped)))
    else:
        row.value = str(clamped)
    await db.flush()
    return clamped


async def get_request_log_retention(db: AsyncSession) -> dict[str, int]:
    """What the operator sees before changing the window: the window and its cost."""

    days = await get_retention_days(db)
    cutoff = _now() - datetime.timedelta(days=days)
    total = int((await db.execute(select(func.count()).select_from(RequestLog))).scalar_one() or 0)
    expired = int(
        (
            await db.execute(select(func.count()).select_from(RequestLog).where(RequestLog.request_time < cutoff))
        ).scalar_one()
        or 0
    )
    return {"retention_days": days, "stored_rows": total, "expired_rows": expired}


async def purge_expired_request_logs(db: AsyncSession, *, retention_days: int | None = None) -> dict[str, int]:
    """Delete request log rows past the window, in committed batches."""

    days = clamp_retention_days(retention_days) if retention_days is not None else await get_retention_days(db)
    cutoff = _now() - datetime.timedelta(days=days)

    deleted = 0
    while True:
        ids = (
            (await db.execute(select(RequestLog.id).where(RequestLog.request_time < cutoff).limit(PURGE_BATCH_SIZE)))
            .scalars()
            .all()
        )
        if not ids:
            break
        result = await db.execute(delete(RequestLog).where(RequestLog.id.in_(list(ids))))
        deleted += int(result.rowcount or 0)
        # Committed per batch: the work already done survives a failure in the
        # next one, and no lock is held across the whole purge.
        await db.commit()
        if len(ids) < PURGE_BATCH_SIZE:
            break

    return {"retention_days": days, "rows_deleted": deleted}
