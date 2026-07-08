"""Stacked activity charts: spend, requests, tokens over time."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.models.logging import RequestLog
from app.utils.display import format_app_source

ACTIVITY_CHART_COLORS = [
    "#14b8a6",
    "#f97316",
    "#eab308",
    "#ec4899",
    "#8b5cf6",
    "#84cc16",
    "#64748b",
]

TOP_SEGMENTS = 6
HEATMAP_DAYS = 365  # 12 months for GitHub-style usage grid

ACTIVITY_PERIOD_PATTERN = "^(15m|30m|1h|3h|day|2d|week|month|year)$"
PROMPTS_PERIOD_PATTERN = "^(day|week|month)$"


def activity_period_start(period: str, now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    deltas = {
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "3h": timedelta(hours=3),
        "day": timedelta(hours=24),
        "2d": timedelta(days=2),
        "week": timedelta(days=7),
        "month": timedelta(days=30),
        "year": timedelta(days=365),
    }
    return now - deltas.get(period, timedelta(days=7))


def _uses_hourly_buckets(period: str) -> bool:
    return period in ("15m", "30m", "1h", "3h", "day", "2d")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _display_dt(dt: datetime, tz_mode: str) -> datetime:
    base = _as_utc(dt)
    if tz_mode == "local":
        return base.astimezone()
    return base


def _short_model_label(model_id: str) -> str:
    raw = (model_id or "unknown").strip()
    if "/" in raw:
        raw = raw.split("/")[-1]
    return raw[:48] if len(raw) > 48 else raw


def segment_key(row: RequestLog, group_by: str) -> str:
    if group_by == "app":
        return (row.source or "unknown").strip() or "unknown"
    if group_by == "user":
        return (row.username or "unknown").strip() or "unknown"
    return (row.model_id or "unknown").strip() or "unknown"


def segment_label(key: str, group_by: str) -> str:
    if key == "__others__":
        return "Others"
    if group_by == "app":
        return format_app_source(key)
    if group_by == "user":
        return key
    return _short_model_label(key)


def _bucket_key(dt: datetime, period: str, tz_mode: str) -> str:
    local = _display_dt(dt, tz_mode)
    if _uses_hourly_buckets(period):
        return local.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
    return local.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d")


def _bucket_labels(period: str, since: datetime, now: datetime, tz_mode: str) -> list[str]:
    keys: list[str] = []
    since_local = _display_dt(since, tz_mode)
    now_local = _display_dt(now, tz_mode)
    if _uses_hourly_buckets(period):
        t = since_local.replace(minute=0, second=0, microsecond=0)
        while t <= now_local:
            keys.append(_bucket_key(t, period, tz_mode))
            t += timedelta(hours=1)
    else:
        t = since_local.replace(hour=0, minute=0, second=0, microsecond=0)
        while t <= now_local:
            keys.append(_bucket_key(t, period, tz_mode))
            t += timedelta(days=1)
    return keys


def _chart_label(bkey: str, period: str, tz_mode: str) -> str:
    if _uses_hourly_buckets(period):
        if "T" in bkey:
            return bkey.split("T")[1][:5]
        return bkey[-5:]
    if len(bkey) >= 10:
        return bkey[5:10]
    return bkey


def apply_activity_filters(
    rows: list[RequestLog],
    *,
    model_id: str | None = None,
    username: str | None = None,
    app: str | None = None,
    response_status: str | None = None,
) -> list[RequestLog]:
    out = rows
    model_filter = (model_id or "").strip()
    if model_filter:
        out = [r for r in out if (r.model_id or "unknown").strip() == model_filter]
    user_filter = (username or "").strip()
    if user_filter:
        out = [r for r in out if (r.username or "").strip() == user_filter]
    app_filter = (app or "").strip()
    if app_filter:
        out = [r for r in out if (r.source or "unknown").strip() == app_filter]
    if response_status == "success":
        out = [r for r in out if r.success]
    elif response_status == "fail":
        out = [r for r in out if not r.success]
    return out


def _aggregate_daily_metrics(rows: list[RequestLog], tz_mode: str) -> dict[str, dict[str, float]]:
    daily: dict[str, dict[str, float]] = defaultdict(
        lambda: {"requests": 0.0, "tokens": 0.0, "spend": 0.0}
    )
    for r in rows:
        dt = r.request_time or datetime.utcnow()
        day = _display_dt(dt, tz_mode).date().isoformat()
        daily[day]["requests"] += 1
        daily[day]["tokens"] += float((r.prompt_tokens or 0) + (r.completion_tokens or 0))
        daily[day]["spend"] += float(r.total_cost_usd or 0)
    return daily


def _pct_change(current: float, previous: float) -> float | None:
    if previous <= 0:
        return 100.0 if current > 0 else None
    return round(((current - previous) / previous) * 100, 1)


def _streak_days(
    daily: dict[str, dict[str, float]],
    end: datetime,
    tz_mode: str,
    metric: str = "requests",
) -> int:
    end_day = _display_dt(end, tz_mode).date()
    streak = 0
    cursor = end_day
    while daily.get(cursor.isoformat(), {}).get(metric, 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _metric_usage_stats(
    heatmap_days: list[dict[str, Any]],
    daily: dict[str, dict[str, float]],
    metric: str,
    *,
    end: datetime,
    tz_mode: str,
) -> dict[str, Any]:
    active = [d for d in heatmap_days if d[metric] > 0]
    total = sum(d[metric] for d in heatmap_days)
    avg_day = total / len(active) if active else 0.0
    streak = _streak_days(daily, end, tz_mode, metric)
    if metric == "spend":
        return {
            "streak_days": streak,
            "avg_day": round(avg_day, 2),
            "avg_week": round(avg_day * 7, 2),
            "total": round(total, 2),
        }
    return {
        "streak_days": streak,
        "avg_day": int(round(avg_day)),
        "avg_week": int(round(avg_day * 7)),
        "total": int(total),
    }


def _heatmap_level(value: float, max_value: float) -> int:
    if value <= 0 or max_value <= 0:
        return 0
    ratio = value / max_value
    if ratio >= 0.75:
        return 4
    if ratio >= 0.5:
        return 3
    if ratio >= 0.25:
        return 2
    return 1


def _build_heatmap(days_metrics: dict[str, dict[str, float]], tz_mode: str, now: datetime) -> list[dict[str, Any]]:
    end = _display_dt(now, tz_mode).date()
    start = end - timedelta(days=HEATMAP_DAYS - 1)
    out: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        key = cursor.isoformat()
        m = days_metrics.get(key, {"requests": 0.0, "tokens": 0.0, "spend": 0.0})
        out.append(
            {
                "date": key,
                "requests": int(m["requests"]),
                "tokens": int(m["tokens"]),
                "spend": float(m["spend"]),
            }
        )
        cursor += timedelta(days=1)
    return out


def _models_meta_from_stats(
    model_stats: dict[str, dict[str, float]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    ranked = sorted(model_stats.items(), key=lambda x: x[1]["tokens"], reverse=True)
    meta: list[dict[str, Any]] = []
    for idx, (model_key, stats) in enumerate(ranked[:limit]):
        meta.append(
            {
                "key": model_key,
                "label": _short_model_label(model_key),
                "color": ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)],
                "spend": stats["spend"],
                "requests": int(stats["requests"]),
                "tokens": int(stats["tokens"]),
            }
        )
    return meta


def _build_insights(
    rows: list[RequestLog],
    prev_rows: list[RequestLog],
    heatmap_rows: list[RequestLog],
    *,
    period: str,
    since: datetime,
    now: datetime,
    tz_mode: str,
) -> dict[str, Any]:
    cur_requests = len(rows)
    cur_tokens = sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in rows)
    cur_spend = sum(float(r.total_cost_usd or 0) for r in rows)

    prev_requests = len(prev_rows)
    prev_tokens = sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in prev_rows)
    prev_spend = sum(float(r.total_cost_usd or 0) for r in prev_rows)

    heatmap_daily = _aggregate_daily_metrics(heatmap_rows, tz_mode)
    streak = _streak_days(heatmap_daily, now, tz_mode, "requests")

    heatmap_days = _build_heatmap(heatmap_daily, tz_mode, now)
    max_requests = max((d["requests"] for d in heatmap_days), default=0)
    max_tokens = max((d["tokens"] for d in heatmap_days), default=0)
    max_spend = max((d["spend"] for d in heatmap_days), default=0.0)
    for d in heatmap_days:
        d["level_requests"] = _heatmap_level(float(d["requests"]), float(max_requests))
        d["level_tokens"] = _heatmap_level(float(d["tokens"]), float(max_tokens))
        d["level_spend"] = _heatmap_level(float(d["spend"]), float(max_spend))

    period_footer = {
        "day": "Today",
        "week": "This Week",
        "month": "This Month",
    }.get(period, "This Period")

    return {
        "streak_days": streak,
        "change_pct": {
            "prompts": _pct_change(float(cur_requests), float(prev_requests)),
            "tokens": _pct_change(float(cur_tokens), float(prev_tokens)),
            "spend": _pct_change(cur_spend, prev_spend),
        },
        "period_footer_label": period_footer,
        "period_prompts": cur_requests,
        "heatmap": {"days": heatmap_days},
        "usage_stats": {
            "requests": _metric_usage_stats(
                heatmap_days, heatmap_daily, "requests", end=now, tz_mode=tz_mode
            ),
            "tokens": _metric_usage_stats(
                heatmap_days, heatmap_daily, "tokens", end=now, tz_mode=tz_mode
            ),
            "spend": _metric_usage_stats(
                heatmap_days, heatmap_daily, "spend", end=now, tz_mode=tz_mode
            ),
        },
    }


def filter_options(rows: list[RequestLog], group_by: str) -> dict[str, list[dict[str, str]]]:
    models = sorted({(r.model_id or "unknown").strip() or "unknown" for r in rows}, key=str.lower)
    users = sorted({(r.username or "unknown").strip() or "unknown" for r in rows}, key=str.lower)
    apps = sorted({(r.source or "unknown").strip() or "unknown" for r in rows}, key=str.lower)
    return {
        "available_models": [{"key": m, "label": _short_model_label(m)} for m in models],
        "available_users": [{"key": u, "label": u} for u in users],
        "available_apps": [{"key": a, "label": format_app_source(a)} for a in apps],
        "group_by": group_by,
    }


def build_prompts_card(
    rows: list[RequestLog],
    *,
    period: str,
    since: datetime,
    group_by: str = "model",
    timezone: str = "local",
    now: datetime | None = None,
    prev_rows: list[RequestLog] | None = None,
    heatmap_rows: list[RequestLog] | None = None,
) -> dict[str, Any]:
    """Prompts hero card: chart + footer metrics for an independent time range."""
    payload = build_activity_payload(
        rows,
        period=period,
        since=since,
        group_by=group_by,
        timezone=timezone,
        now=now,
        prev_rows=prev_rows,
        heatmap_rows=heatmap_rows,
    )
    ins = payload["insights"]
    return {
        "period": period,
        "chart": payload["chart"],
        "models": payload["models"],
        "total": payload["totals"]["requests"],
        "change_pct": ins["change_pct"]["prompts"],
        "period_footer_label": ins["period_footer_label"],
        "period_prompts": ins["period_prompts"],
        "streak_days": ins["streak_days"],
    }


def build_activity_payload(
    rows: list[RequestLog],
    *,
    period: str,
    since: datetime,
    group_by: str = "model",
    timezone: str = "local",
    now: datetime | None = None,
    prev_rows: list[RequestLog] | None = None,
    heatmap_rows: list[RequestLog] | None = None,
) -> dict[str, Any]:
    now = now or datetime.utcnow()
    group_by = group_by if group_by in ("model", "app", "user") else "model"
    tz_mode = timezone if timezone in ("local", "utc") else "local"

    segment_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"spend": 0.0, "requests": 0.0, "tokens": 0.0}
    )
    bucket_spend: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    bucket_requests: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    bucket_tokens: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    failed = 0
    cached_hits = 0
    for r in rows:
        seg = segment_key(r, group_by)
        spend = float(r.total_cost_usd or 0)
        tokens = float((r.prompt_tokens or 0) + (r.completion_tokens or 0))
        segment_stats[seg]["spend"] += spend
        segment_stats[seg]["requests"] += 1
        segment_stats[seg]["tokens"] += tokens
        bkey = _bucket_key(r.request_time or now, period, tz_mode)
        bucket_spend[bkey][seg] += spend
        bucket_requests[bkey][seg] += 1
        bucket_tokens[bkey][seg] += tokens
        if not r.success:
            failed += 1
        if (r.cached_tokens or 0) > 0:
            cached_hits += 1

    ranked = sorted(segment_stats.items(), key=lambda x: x[1]["spend"], reverse=True)
    top_segments = [m for m, _ in ranked[:TOP_SEGMENTS]]
    top_set = set(top_segments)

    def stack_value(bucket_map: dict[str, dict[str, float]], bkey: str) -> dict[str, float]:
        raw = bucket_map.get(bkey, {})
        out: dict[str, float] = {}
        other = 0.0
        for seg, val in raw.items():
            target = seg if seg in top_set else "__others__"
            if target == "__others__":
                other += val
            else:
                out[target] = out.get(target, 0.0) + val
        if other > 0:
            out["__others__"] = other
        return out

    bucket_keys = _bucket_labels(period, since, now, tz_mode)
    chart: list[dict] = []
    for bkey in bucket_keys:
        row: dict[str, Any] = {
            "bucket": bkey,
            "label": _chart_label(bkey, period, tz_mode),
        }
        for seg, val in stack_value(bucket_spend, bkey).items():
            row[f"spend_{seg}"] = val
        for seg, val in stack_value(bucket_requests, bkey).items():
            row[f"requests_{seg}"] = val
        for seg, val in stack_value(bucket_tokens, bkey).items():
            row[f"tokens_{seg}"] = val
        chart.append(row)

    stack_order = list(top_segments)
    if any(m not in top_set for m in segment_stats.keys()):
        stack_order.append("__others__")

    segments_meta: list[dict[str, Any]] = []
    for idx, seg in enumerate(stack_order):
        stats = segment_stats.get(seg, {"spend": 0.0, "requests": 0.0, "tokens": 0.0})
        if seg == "__others__":
            stats = {
                "spend": sum(v["spend"] for _, v in ranked[TOP_SEGMENTS:]),
                "requests": sum(v["requests"] for _, v in ranked[TOP_SEGMENTS:]),
                "tokens": sum(v["tokens"] for _, v in ranked[TOP_SEGMENTS:]),
            }
        segments_meta.append(
            {
                "key": seg,
                "label": segment_label(seg, group_by),
                "color": ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)],
                "spend": stats["spend"],
                "requests": int(stats["requests"]),
                "tokens": int(stats["tokens"]),
            }
        )

    total_spend = sum(v["spend"] for _, v in ranked)
    total_requests = len(rows)
    total_tokens = sum(v["tokens"] for _, v in ranked)

    model_only: dict[str, dict[str, float]] = defaultdict(
        lambda: {"spend": 0.0, "requests": 0.0, "tokens": 0.0}
    )
    for r in rows:
        mk = (r.model_id or "unknown").strip() or "unknown"
        model_only[mk]["spend"] += float(r.total_cost_usd or 0)
        model_only[mk]["requests"] += 1
        model_only[mk]["tokens"] += float((r.prompt_tokens or 0) + (r.completion_tokens or 0))

    insights = _build_insights(
        rows,
        prev_rows or [],
        heatmap_rows if heatmap_rows is not None else rows,
        period=period,
        since=since,
        now=now,
        tz_mode=tz_mode,
    )

    return {
        "period": period,
        "group_by": group_by,
        "timezone": tz_mode,
        "totals": {
            "spend": total_spend,
            "requests": total_requests,
            "tokens": total_tokens,
        },
        "models": segments_meta,
        "top_models": _models_meta_from_stats(model_only),
        "chart": chart,
        "insights": insights,
        "guardrails": {
            "blocked_requests": failed,
            "cached_prompts": cached_hits,
            "redacted_flagged": cached_hits,
        },
    }


def activity_to_export_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    """Summary export: one row per stacked segment."""
    segments = payload.get("models") or []
    if not segments:
        return pd.DataFrame([{"message": "No data in selected range"}])
    return pd.DataFrame(
        [
            {
                "segment": s.get("label"),
                "spend_usd": s.get("spend"),
                "requests": s.get("requests"),
                "tokens": s.get("tokens"),
            }
            for s in segments
        ]
    )
