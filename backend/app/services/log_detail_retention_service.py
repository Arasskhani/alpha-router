"""How long the raw provider payloads behind API Logs are kept.

Every upstream attempt stores the provider's own response
(``usage_events.raw_usage_json``), and every video job stores its last poll
payload (``video_generation_jobs.provider_status_raw``). That is the material
that actually explains a failure — and also the bulkiest, longest-lived thing
in the log tables, sometimes carrying a prompt echoed back by the provider.

So it is kept on a clock the operator sets from the API Logs page: the
payloads are cleared after N days while the rows themselves (costs, tokens,
status, the failure reason) stay for as long as the request log does.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cost_accounting import UsageEvent
from app.models.system import SystemSetting
from app.models.video import VideoGenerationJob

KEY_RAW_PAYLOAD_RETENTION_DAYS = "api_logs_raw_payload_retention_days"

DEFAULT_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 365


def clamp_retention_days(value: Any, *, default: int = DEFAULT_RETENTION_DAYS) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return max(MIN_RETENTION_DAYS, min(MAX_RETENTION_DAYS, days))


async def get_raw_payload_retention_days(db: AsyncSession) -> int:
    row = await db.get(SystemSetting, KEY_RAW_PAYLOAD_RETENTION_DAYS)
    return clamp_retention_days(row.value if row else None)


async def get_raw_payload_retention(db: AsyncSession) -> dict[str, Any]:
    days = await get_raw_payload_retention_days(db)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    pending = (
        await db.execute(
            select(UsageEvent.id).where(UsageEvent.raw_usage_json.isnot(None), UsageEvent.started_at < cutoff).limit(1)
        )
    ).first()
    return {
        "retention_days": days,
        "min_days": MIN_RETENTION_DAYS,
        "max_days": MAX_RETENTION_DAYS,
        "default_days": DEFAULT_RETENTION_DAYS,
        "has_expired_payloads": pending is not None,
    }


async def set_raw_payload_retention_days(db: AsyncSession, days: int) -> dict[str, Any]:
    value = str(clamp_retention_days(days))
    row = await db.get(SystemSetting, KEY_RAW_PAYLOAD_RETENTION_DAYS)
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=KEY_RAW_PAYLOAD_RETENTION_DAYS, value=value))
    await db.flush()
    return await get_raw_payload_retention(db)


async def purge_expired_raw_payloads(db: AsyncSession, *, days: int | None = None) -> dict[str, int]:
    """Blank payloads older than the retention window; keep the rows themselves.

    Nulling the column rather than deleting the row is the point: the cost,
    the tokens and the failure reason stay in the log, only the bulky verbatim
    payload goes.
    """
    retention_days = clamp_retention_days(days) if days is not None else await get_raw_payload_retention_days(db)
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)

    events = await db.execute(
        update(UsageEvent)
        .where(UsageEvent.raw_usage_json.isnot(None), UsageEvent.started_at < cutoff)
        .values(raw_usage_json=None)
    )
    jobs = await db.execute(
        update(VideoGenerationJob)
        .where(
            VideoGenerationJob.provider_status_raw.isnot(None),
            VideoGenerationJob.created_at < cutoff,
        )
        .values(provider_status_raw=None)
    )
    return {
        "retention_days": retention_days,
        "usage_events_cleared": int(events.rowcount or 0),
        "video_jobs_cleared": int(jobs.rowcount or 0),
    }
