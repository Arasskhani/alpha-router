"""Resolve Operations dashboard time windows (Datadog-style presets)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

OpsRangeKey = Literal[
    "past_15m",
    "past_30m",
    "past_1h",
    "past_3h",
    "past_1d",
    "past_2d",
    "past_1w",
    "past_1mo",
    "past_1y",
    "today",
    "yesterday",
    "this_week",
    "prev_week",
]

DEFAULT_OPS_RANGE: OpsRangeKey = "past_1d"
MAX_CHART_BUCKETS = 96

VALID_OPS_RANGE_KEYS: frozenset[str] = frozenset(
    [
        "past_15m",
        "past_30m",
        "past_1h",
        "past_3h",
        "past_1d",
        "past_2d",
        "past_1w",
        "past_1mo",
        "past_1y",
        "today",
        "yesterday",
        "this_week",
        "prev_week",
    ]
)

_RANGE_META: dict[str, dict[str, str]] = {
    "past_15m": {"label": "Past 15 Minutes", "badge": "15m", "period_short": "15m"},
    "past_30m": {"label": "Past 30 Minutes", "badge": "30m", "period_short": "30m"},
    "past_1h": {"label": "Past 1 Hour", "badge": "1h", "period_short": "1h"},
    "past_3h": {"label": "Past 3 Hours", "badge": "3h", "period_short": "3h"},
    "past_1d": {"label": "Past 1 Day", "badge": "1d", "period_short": "24h"},
    "past_2d": {"label": "Past 2 Days", "badge": "2d", "period_short": "48h"},
    "past_1w": {"label": "Past 1 Week", "badge": "1w", "period_short": "7d"},
    "past_1mo": {"label": "Past 1 Month", "badge": "1mo", "period_short": "30d"},
    "past_1y": {"label": "Past 1 Year", "badge": "1y", "period_short": "1y"},
    "today": {"label": "Today", "badge": "TD", "period_short": "today"},
    "yesterday": {"label": "Yesterday", "badge": "YD", "period_short": "yesterday"},
    "this_week": {"label": "This Week", "badge": "TW", "period_short": "this week"},
    "prev_week": {"label": "Prev Week", "badge": "PW", "period_short": "prev week"},
}


@dataclass(frozen=True)
class OpsTimeRange:
    key: str
    label: str
    short_badge: str
    period_short: str
    since: datetime
    until: datetime
    bucket_seconds: int
    bucket_count: int
    compare_since: datetime
    compare_until: datetime


def _utc_now() -> datetime:
    return datetime.utcnow()


def _start_of_utc_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_utc_week(dt: datetime) -> datetime:
    return _start_of_utc_day(dt) - timedelta(days=dt.weekday())


def _bucket_count(since: datetime, until: datetime, bucket_seconds: int) -> int:
    duration = max(1, int((until - since).total_seconds()))
    return min(MAX_CHART_BUCKETS, max(1, (duration + bucket_seconds - 1) // bucket_seconds))


def _window(
    key: str,
    *,
    since: datetime,
    until: datetime,
    bucket_seconds: int,
) -> OpsTimeRange:
    meta = _RANGE_META[key]
    bucket_count = _bucket_count(since, until, bucket_seconds)
    duration = until - since
    compare_until = since
    compare_since = since - duration
    return OpsTimeRange(
        key=key,
        label=meta["label"],
        short_badge=meta["badge"],
        period_short=meta["period_short"],
        since=since,
        until=until,
        bucket_seconds=bucket_seconds,
        bucket_count=bucket_count,
        compare_since=compare_since,
        compare_until=compare_until,
    )


def resolve_ops_time_range(key: str | None, *, now: datetime | None = None) -> OpsTimeRange:
    now = now or _utc_now()
    k = key if key in VALID_OPS_RANGE_KEYS else DEFAULT_OPS_RANGE

    if k == "past_15m":
        return _window(k, since=now - timedelta(minutes=15), until=now, bucket_seconds=60)
    if k == "past_30m":
        return _window(k, since=now - timedelta(minutes=30), until=now, bucket_seconds=60)
    if k == "past_1h":
        return _window(k, since=now - timedelta(hours=1), until=now, bucket_seconds=300)
    if k == "past_3h":
        return _window(k, since=now - timedelta(hours=3), until=now, bucket_seconds=600)
    if k == "past_1d":
        return _window(k, since=now - timedelta(hours=24), until=now, bucket_seconds=3600)
    if k == "past_2d":
        return _window(k, since=now - timedelta(hours=48), until=now, bucket_seconds=3600)
    if k == "past_1w":
        return _window(k, since=now - timedelta(days=7), until=now, bucket_seconds=86400)
    if k == "past_1mo":
        return _window(k, since=now - timedelta(days=30), until=now, bucket_seconds=86400)
    if k == "past_1y":
        return _window(k, since=now - timedelta(days=365), until=now, bucket_seconds=604800)

    if k == "today":
        return _window(k, since=_start_of_utc_day(now), until=now, bucket_seconds=3600)
    if k == "yesterday":
        start_today = _start_of_utc_day(now)
        return _window(k, since=start_today - timedelta(days=1), until=start_today, bucket_seconds=3600)

    if k == "this_week":
        since = _start_of_utc_week(now)
        secs = int((now - since).total_seconds())
        bucket_seconds = 3600 if secs <= 72 * 3600 else 86400
        return _window(k, since=since, until=now, bucket_seconds=bucket_seconds)

    # prev_week
    this_monday = _start_of_utc_week(now)
    return _window(
        k,
        since=this_monday - timedelta(days=7),
        until=this_monday,
        bucket_seconds=86400,
    )


def ops_time_range_payload(tr: OpsTimeRange) -> dict:
    return {
        "key": tr.key,
        "label": tr.label,
        "short_badge": tr.short_badge,
        "period_short": tr.period_short,
        "since": tr.since.isoformat() + "Z",
        "until": tr.until.isoformat() + "Z",
        "bucket_seconds": tr.bucket_seconds,
        "bucket_count": tr.bucket_count,
    }
