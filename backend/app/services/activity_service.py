"""Stacked activity charts: spend, requests, tokens over time."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from app.models.logging import RequestLog
from app.utils.display import MEMORY_USAGE_SOURCE, format_app_source

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
TOP_OVERVIEW_LIST = 5
TOP_TRENDING = 6
HEATMAP_DAYS = 365  # 12 months for GitHub-style usage grid

OVERVIEW_TOKEN_COLORS = {
    "prompt": "#3b82f6",
    "completion": "#8b5cf6",
}
OVERVIEW_CACHE_COLORS = {
    "uncached": "#94a3b8",
    "cached": "#f97316",
}

ACTIVITY_PERIOD_PATTERN = "^(15m|30m|1h|3h|day|2d|week|month|year)$"
PROMPTS_PERIOD_PATTERN = "^(day|week|month)$"

EXPLORE_METRICS = frozenset(
    {
        "request_count",
        "total_usage",
        "tokens_total",
        "tokens_prompt",
        "tokens_completion",
        "cached_tokens",
        "avg_latency",
        "p50_latency",
    }
)
EXPLORE_GROUPS = frozenset({"none", "model", "api_key", "provider", "app", "user"})
EXPLORE_ROLLUPS = frozenset({"total", "hourly", "daily", "weekly", "monthly"})
EXPLORE_TOP_NS = frozenset({5, 10, 15, 30})
EXPLORE_LATENCY_METRICS = frozenset({"avg_latency", "p50_latency"})


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
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


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
    alpha_router_api_key_id: int | None = None,
    user_api_key_id: int | None = None,
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
    if alpha_router_api_key_id is not None:
        out = [r for r in out if r.alpha_router_api_key_id == alpha_router_api_key_id]
    if user_api_key_id is not None:
        if user_api_key_id < 0:
            return []
        out = [r for r in out if r.user_api_key_id == user_api_key_id]
    if response_status == "success":
        out = [r for r in out if r.success]
    elif response_status == "fail":
        out = [r for r in out if not r.success]
    return out


def _aggregate_daily_metrics(rows: list[RequestLog], tz_mode: str) -> dict[str, dict[str, float]]:
    daily: dict[str, dict[str, float]] = defaultdict(lambda: {"requests": 0.0, "tokens": 0.0, "spend": 0.0})
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
    heatmap_daily: dict[str, dict[str, float]],
    *,
    period: str,
    since: datetime,
    now: datetime,
    tz_mode: str,
) -> dict[str, Any]:
    """``heatmap_daily`` is day -> totals; the caller decides whether SQL or
    Python produced it. Reading a year of rows to count them here is what made
    every Activity view a one-year scan."""

    cur_requests = len(rows)
    cur_tokens = sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in rows)
    cur_spend = sum(float(r.total_cost_usd or 0) for r in rows)

    prev_requests = len(prev_rows)
    prev_tokens = sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in prev_rows)
    prev_spend = sum(float(r.total_cost_usd or 0) for r in prev_rows)

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
            "requests": _metric_usage_stats(heatmap_days, heatmap_daily, "requests", end=now, tz_mode=tz_mode),
            "tokens": _metric_usage_stats(heatmap_days, heatmap_daily, "tokens", end=now, tz_mode=tz_mode),
            "spend": _metric_usage_stats(heatmap_days, heatmap_daily, "spend", end=now, tz_mode=tz_mode),
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
        "available_api_keys": [],
        "group_by": group_by,
    }


def _client_app_key(row: RequestLog) -> str:
    name = (row.client_app or "").strip()
    if name:
        return name
    return format_app_source((row.source or "unknown").strip() or "unknown")


def _is_memory_row(row: RequestLog) -> bool:
    """Automatic memory extraction, by the source every other reader groups on."""

    return (row.source or "").strip().lower() == MEMORY_USAGE_SOURCE


def _kpi_dict(value: float, prev: float, sparkline: list[float]) -> dict[str, Any]:
    return {
        "value": value,
        "change_pct": _pct_change(value, prev),
        "sparkline": sparkline,
    }


def _provider_from_model(model_id: str) -> str:
    raw = (model_id or "").strip()
    if "/" in raw:
        return raw.split("/", 1)[0]
    return ""


def _initials_from_label(label: str) -> str:
    parts = [p for p in label.replace(".", " ").replace("@", " ").replace("_", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (label[:2] or "?").upper()


def _entity_metric(row: RequestLog, metric: str) -> float:
    if metric == "requests":
        return 1.0
    if metric == "tokens":
        return float((row.prompt_tokens or 0) + (row.completion_tokens or 0))
    return float(row.total_cost_usd or 0)


def _build_dimension_trends(  # noqa: C901 -- Phase 4 split; complexity must not grow
    rows: list[RequestLog],
    prev_rows: list[RequestLog],
    *,
    key_fn,
    label_fn,
    subtitle_fn,
    period: str,
    since: datetime,
    now: datetime,
    tz_mode: str,
    extra_fn=None,
) -> dict[str, Any]:
    """Spend-over-time stack + trending list for one entity dimension."""
    bucket_keys = _bucket_labels(period, since, now, tz_mode)
    spend_b: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    req_b: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    tok_b: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    cur: dict[str, dict[str, float]] = defaultdict(lambda: {"spend": 0.0, "requests": 0.0, "tokens": 0.0})
    prev: dict[str, dict[str, float]] = defaultdict(lambda: {"spend": 0.0, "requests": 0.0, "tokens": 0.0})
    daily_metric: dict[str, dict[str, dict[str, float]]] = {
        "spend": defaultdict(lambda: defaultdict(float)),
        "requests": defaultdict(lambda: defaultdict(float)),
        "tokens": defaultdict(lambda: defaultdict(float)),
    }
    meta: dict[str, dict[str, Any]] = {}

    for r in rows:
        key = key_fn(r)
        if not key:
            continue
        bkey = _bucket_key(r.request_time or now, period, tz_mode)
        spend = float(r.total_cost_usd or 0)
        tokens = float((r.prompt_tokens or 0) + (r.completion_tokens or 0))
        spend_b[bkey][key] += spend
        req_b[bkey][key] += 1
        tok_b[bkey][key] += tokens
        cur[key]["spend"] += spend
        cur[key]["requests"] += 1
        cur[key]["tokens"] += tokens
        daily_metric["spend"][key][bkey] += spend
        daily_metric["requests"][key][bkey] += 1
        daily_metric["tokens"][key][bkey] += tokens
        if key not in meta:
            meta[key] = {
                "label": label_fn(r, key),
                "subtitle": subtitle_fn(r, key),
                "initials": _initials_from_label(label_fn(r, key)),
            }
            if extra_fn:
                meta[key].update(extra_fn(r, key) or {})

    for r in prev_rows:
        key = key_fn(r)
        if not key:
            continue
        prev[key]["spend"] += float(r.total_cost_usd or 0)
        prev[key]["requests"] += 1
        prev[key]["tokens"] += float((r.prompt_tokens or 0) + (r.completion_tokens or 0))
        if key not in meta:
            meta[key] = {
                "label": label_fn(r, key),
                "subtitle": subtitle_fn(r, key),
                "initials": _initials_from_label(label_fn(r, key)),
            }
            if extra_fn:
                meta[key].update(extra_fn(r, key) or {})

    ranked = sorted(cur.items(), key=lambda x: x[1]["spend"], reverse=True)
    top_keys = [k for k, _ in ranked[:TOP_SEGMENTS]]
    top_set = set(top_keys)
    stack_order = list(top_keys)
    if any(k not in top_set for k in cur):
        stack_order.append("__others__")

    def _stack(bucket_map: dict[str, dict[str, float]], bkey: str) -> dict[str, float]:
        raw = bucket_map.get(bkey, {})
        out: dict[str, float] = {}
        other = 0.0
        for seg, val in raw.items():
            if seg in top_set:
                out[seg] = out.get(seg, 0.0) + val
            else:
                other += val
        if other > 0:
            out["__others__"] = other
        return out

    chart: list[dict[str, Any]] = []
    for bkey in bucket_keys:
        row: dict[str, Any] = {"bucket": bkey, "label": _chart_label(bkey, period, tz_mode)}
        for seg, val in _stack(spend_b, bkey).items():
            row[f"spend_{seg}"] = val
        chart.append(row)

    segments: list[dict[str, Any]] = []
    for idx, seg in enumerate(stack_order):
        if seg == "__others__":
            stats = {
                "spend": sum(v["spend"] for k, v in ranked[TOP_SEGMENTS:]),
                "requests": sum(v["requests"] for k, v in ranked[TOP_SEGMENTS:]),
                "tokens": sum(v["tokens"] for k, v in ranked[TOP_SEGMENTS:]),
            }
            label = "Other"
        else:
            stats = cur[seg]
            label = meta.get(seg, {}).get("label") or seg
        segments.append(
            {
                "key": seg,
                "label": label,
                "color": ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)],
                "spend": stats["spend"],
                "requests": int(stats["requests"]),
                "tokens": int(stats["tokens"]),
            }
        )

    def _trending_for(metric: str) -> list[dict[str, Any]]:
        scored: list[tuple[float, str]] = []
        for key, stats in cur.items():
            cur_v = float(stats[metric])
            prev_v = float(prev.get(key, {}).get(metric) or 0)
            if cur_v <= 0 and prev_v <= 0:
                continue
            if prev_v <= 0 and cur_v > 0:
                score = 10_000.0 + cur_v
            else:
                score = abs(_pct_change(cur_v, prev_v) or 0) + cur_v * 1e-9
            scored.append((score, key))
        scored.sort(reverse=True)
        out: list[dict[str, Any]] = []
        for _, key in scored[:TOP_TRENDING]:
            cur_v = float(cur[key][metric])
            prev_v = float(prev.get(key, {}).get(metric) or 0)
            is_new = prev_v <= 0 and cur_v > 0
            spark = [daily_metric[metric][key].get(b, 0.0) for b in bucket_keys]
            item = {
                "key": key,
                "label": meta.get(key, {}).get("label") or key,
                "subtitle": meta.get(key, {}).get("subtitle") or "",
                "initials": meta.get(key, {}).get("initials") or "?",
                "color": ACTIVITY_CHART_COLORS[
                    (top_keys.index(key) if key in top_set else len(top_keys)) % len(ACTIVITY_CHART_COLORS)
                ],
                "value": cur_v,
                "change_pct": None if is_new else _pct_change(cur_v, prev_v),
                "is_new": is_new,
                "sparkline": spark,
            }
            if "provider" in meta.get(key, {}):
                item["provider"] = meta[key]["provider"]
            out.append(item)
        return out

    return {
        "spend_over_time": {"segments": segments, "chart": chart},
        "trending": {
            "spend": _trending_for("spend"),
            "requests": _trending_for("requests"),
            "tokens": _trending_for("tokens"),
        },
    }


def _build_trends(
    rows: list[RequestLog],
    prev_rows: list[RequestLog],
    *,
    period: str,
    since: datetime,
    now: datetime,
    tz_mode: str,
    api_key_meta: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """OpenRouter-style Trends: Models / Users / API Keys / Apps."""
    key_meta = api_key_meta or {}

    def model_key(r: RequestLog) -> str:
        return (r.model_id or "unknown").strip() or "unknown"

    def user_key(r: RequestLog) -> str:
        return (r.username or "unknown").strip() or "unknown"

    def app_key(r: RequestLog) -> str:
        return _client_app_key(r)

    def api_key_key(r: RequestLog) -> str:
        if r.alpha_router_api_key_id is None:
            return ""
        return str(int(r.alpha_router_api_key_id))

    return {
        "models": _build_dimension_trends(
            rows,
            prev_rows,
            key_fn=model_key,
            label_fn=lambda _r, k: _short_model_label(k),
            subtitle_fn=lambda _r, k: _provider_from_model(k),
            period=period,
            since=since,
            now=now,
            tz_mode=tz_mode,
            extra_fn=lambda _r, k: {"provider": _provider_from_model(k)},
        ),
        "users": _build_dimension_trends(
            rows,
            prev_rows,
            key_fn=user_key,
            label_fn=lambda _r, k: k,
            subtitle_fn=lambda _r, k: k if "@" in k else "",
            period=period,
            since=since,
            now=now,
            tz_mode=tz_mode,
        ),
        "api_keys": _build_dimension_trends(
            rows,
            prev_rows,
            key_fn=api_key_key,
            label_fn=lambda _r, k: (
                (key_meta.get(k) or {}).get("name") or (key_meta.get(k) or {}).get("label") or f"API key {k}"
            ),
            subtitle_fn=lambda _r, k: (key_meta.get(k) or {}).get("prefix") or "",
            period=period,
            since=since,
            now=now,
            tz_mode=tz_mode,
        ),
        "apps": _build_dimension_trends(
            rows,
            prev_rows,
            key_fn=app_key,
            label_fn=lambda _r, k: k,
            subtitle_fn=lambda _r, _k: "",
            period=period,
            since=since,
            now=now,
            tz_mode=tz_mode,
        ),
    }


def _explore_metric_value(row: RequestLog, metric: str) -> float:
    if metric == "request_count":
        return 1.0
    if metric == "total_usage":
        return float(row.total_cost_usd or 0)
    if metric == "tokens_total":
        return float((row.prompt_tokens or 0) + (row.completion_tokens or 0))
    if metric == "tokens_prompt":
        return float(row.prompt_tokens or 0)
    if metric == "tokens_completion":
        return float(row.completion_tokens or 0)
    if metric == "cached_tokens":
        return float(row.cached_tokens or 0)
    if metric in EXPLORE_LATENCY_METRICS:
        return float(row.response_time_ms or 0)
    return float(row.total_cost_usd or 0)


def _explore_entity_part(row: RequestLog, dim: str, api_key_meta: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Return (key, label) for one explore dimension."""
    if dim == "none":
        return ("__all__", "All")
    if dim == "model":
        key = (row.model_id or "unknown").strip() or "unknown"
        return key, _short_model_label(key)
    if dim == "user":
        key = (row.username or "unknown").strip() or "unknown"
        return key, key
    if dim == "app":
        key = _client_app_key(row)
        return key, key
    if dim == "provider":
        mid = (row.model_id or "unknown").strip() or "unknown"
        key = _provider_from_model(mid) or "unknown"
        return key, key
    if dim == "api_key":
        if row.alpha_router_api_key_id is None:
            return ("__none__", "No API key")
        key = str(int(row.alpha_router_api_key_id))
        meta = api_key_meta.get(key) or {}
        label = str(meta.get("name") or meta.get("label") or f"API key {key}")
        return key, label
    return ("unknown", "unknown")


def _explore_entity_key(
    row: RequestLog,
    group: str,
    subgroup: str | None,
    api_key_meta: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    g_key, g_label = _explore_entity_part(row, group, api_key_meta)
    if not subgroup or subgroup == "none" or subgroup == group:
        return g_key, g_label
    s_key, s_label = _explore_entity_part(row, subgroup, api_key_meta)
    return f"{g_key}›{s_key}", f"{g_label} › {s_label}"


def _explore_rollup_key(dt: datetime, rollup: str, tz_mode: str) -> str:
    local = _display_dt(dt, tz_mode)
    if rollup == "total":
        return "total"
    if rollup == "hourly":
        return local.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
    if rollup == "weekly":
        iso = local.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if rollup == "monthly":
        return local.strftime("%Y-%m")
    return local.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d")


def _explore_rollup_labels(rollup: str, since: datetime, now: datetime, tz_mode: str) -> list[str]:
    if rollup == "total":
        return ["total"]
    since_local = _display_dt(since, tz_mode)
    now_local = _display_dt(now, tz_mode)
    keys: list[str] = []
    if rollup == "hourly":
        t = since_local.replace(minute=0, second=0, microsecond=0)
        while t <= now_local:
            keys.append(_explore_rollup_key(t, rollup, tz_mode))
            t += timedelta(hours=1)
        return keys
    if rollup == "weekly":
        t = since_local - timedelta(days=since_local.weekday())
        t = t.replace(hour=0, minute=0, second=0, microsecond=0)
        while t <= now_local:
            key = _explore_rollup_key(t, rollup, tz_mode)
            if not keys or keys[-1] != key:
                keys.append(key)
            t += timedelta(days=7)
        return keys
    if rollup == "monthly":
        t = since_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while t <= now_local:
            keys.append(_explore_rollup_key(t, rollup, tz_mode))
            t = t.replace(year=t.year + 1, month=1) if t.month == 12 else t.replace(month=t.month + 1)
        return keys
    t = since_local.replace(hour=0, minute=0, second=0, microsecond=0)
    while t <= now_local:
        keys.append(_explore_rollup_key(t, rollup, tz_mode))
        t += timedelta(days=1)
    return keys


def _explore_chart_label(bkey: str, rollup: str) -> str:
    if rollup == "total":
        return "Total"
    if rollup == "hourly":
        if "T" in bkey:
            return bkey.split("T")[1][:5]
        return bkey[-5:]
    if rollup == "weekly":
        return bkey
    if rollup == "monthly":
        return bkey
    if len(bkey) >= 10:
        return bkey[5:10]
    return bkey


def _percentile_50(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def build_explore(  # noqa: C901 -- Phase 4 split; complexity must not grow
    rows: list[RequestLog],
    *,
    since: datetime,
    now: datetime,
    tz_mode: str,
    metric: str = "total_usage",
    group: str = "model",
    subgroup: str | None = None,
    rollup: str = "daily",
    top_mode: str = "top",
    top_n: int = 10,
    rank_by: str = "metric",
    show_other: bool = True,
    cumulative: bool = False,
    chart_type: str = "bar",
    api_key_meta: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """OpenRouter-style Explore chart + table for the admin dashboard."""
    metric = metric if metric in EXPLORE_METRICS else "total_usage"
    group = group if group in EXPLORE_GROUPS else "model"
    sub = subgroup if subgroup in EXPLORE_GROUPS and subgroup not in (None, "none", group) else None
    rollup = rollup if rollup in EXPLORE_ROLLUPS else "daily"
    top_mode = "bottom" if top_mode == "bottom" else "top"
    top_n = top_n if top_n in EXPLORE_TOP_NS else 10
    rank_by = "requests" if rank_by == "requests" else "metric"
    chart_type = chart_type if chart_type in ("bar", "line", "area") else "bar"
    key_meta = api_key_meta or {}
    is_latency = metric in EXPLORE_LATENCY_METRICS

    bucket_keys = _explore_rollup_labels(rollup, since, now, tz_mode)
    # entity -> bucket -> sum / count / latency samples
    series_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    series_count: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    series_lat: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    entity_sum: dict[str, float] = defaultdict(float)
    entity_req: dict[str, float] = defaultdict(float)
    entity_lat: dict[str, list[float]] = defaultdict(list)
    entity_labels: dict[str, str] = {}

    for r in rows:
        ekey, elabel = _explore_entity_key(r, group, sub, key_meta)
        if not ekey:
            continue
        entity_labels[ekey] = elabel
        bkey = _explore_rollup_key(r.request_time or now, rollup, tz_mode)
        val = _explore_metric_value(r, metric)
        series_sum[ekey][bkey] += val
        series_count[ekey][bkey] += 1
        entity_sum[ekey] += val
        entity_req[ekey] += 1
        if is_latency:
            series_lat[ekey][bkey].append(val)
            entity_lat[ekey].append(val)

    def entity_metric_total(key: str) -> float:
        if metric == "avg_latency":
            samples = entity_lat.get(key) or []
            return (sum(samples) / len(samples)) if samples else 0.0
        if metric == "p50_latency":
            return _percentile_50(entity_lat.get(key) or [])
        return float(entity_sum.get(key) or 0)

    def rank_score(key: str) -> float:
        if rank_by == "requests":
            return float(entity_req.get(key) or 0)
        return entity_metric_total(key)

    ranked = sorted(entity_sum.keys(), key=rank_score, reverse=(top_mode != "bottom"))
    # Prefer non-zero metric entities first when ranking by metric
    if rank_by == "metric":
        ranked = sorted(
            entity_sum.keys(),
            key=lambda k: (rank_score(k), entity_req.get(k, 0)),
            reverse=(top_mode != "bottom"),
        )
    top_keys = ranked[:top_n]
    top_set = set(top_keys)
    has_other = show_other and any(k not in top_set for k in ranked)

    def bucket_value(ekey: str, bkey: str) -> float:
        if metric == "avg_latency":
            samples = series_lat[ekey].get(bkey) or []
            return (sum(samples) / len(samples)) if samples else 0.0
        if metric == "p50_latency":
            return _percentile_50(series_lat[ekey].get(bkey) or [])
        return float(series_sum[ekey].get(bkey) or 0)

    def stacked_for_bucket(bkey: str) -> dict[str, float]:
        out: dict[str, float] = {}
        other = 0.0
        other_samples: list[float] = []
        other_count = 0.0
        for ekey in ranked:
            val = bucket_value(ekey, bkey)
            if ekey in top_set:
                out[ekey] = val
            elif show_other:
                if is_latency:
                    other_samples.extend(series_lat[ekey].get(bkey) or [])
                    other_count += series_count[ekey].get(bkey) or 0
                else:
                    other += val
        if show_other and has_other:
            if metric == "avg_latency":
                out["__others__"] = (sum(other_samples) / len(other_samples)) if other_samples else 0.0
            elif metric == "p50_latency":
                out["__others__"] = _percentile_50(other_samples)
            else:
                out["__others__"] = other
        return out

    chart: list[dict[str, Any]] = []
    running: dict[str, float] = defaultdict(float)
    for bkey in bucket_keys:
        row: dict[str, Any] = {
            "bucket": bkey,
            "label": _explore_chart_label(bkey, rollup),
        }
        stacked = stacked_for_bucket(bkey)
        for seg, val in stacked.items():
            if cumulative and not is_latency:
                running[seg] += val
                row[f"v_{seg}"] = running[seg]
            else:
                row[f"v_{seg}"] = val
        chart.append(row)

    stack_order = list(top_keys)
    if has_other:
        stack_order.append("__others__")

    segments: list[dict[str, Any]] = []
    for idx, seg in enumerate(stack_order):
        if seg == "__others__":
            label = "Other"
            color = ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)]
        else:
            label = entity_labels.get(seg) or seg
            color = ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)]
        segments.append({"key": seg, "label": label, "color": color})

    # Table rows for ranked entities (+ Other aggregate)
    table: list[dict[str, Any]] = []
    grand_total = 0.0
    table_targets = list(top_keys)
    if has_other:
        table_targets.append("__others__")

    def entity_bucket_series(ekey: str) -> list[float]:
        if ekey == "__others__":
            vals: list[float] = []
            for bkey in bucket_keys:
                stacked = stacked_for_bucket(bkey)
                vals.append(float(stacked.get("__others__") or 0))
            return vals
        return [bucket_value(ekey, b) for b in bucket_keys]

    totals_for_pct: dict[str, float] = {}
    for ekey in table_targets:
        if ekey == "__others__":
            if is_latency:
                samples: list[float] = []
                for k in ranked:
                    if k not in top_set:
                        samples.extend(entity_lat.get(k) or [])
                totals_for_pct[ekey] = (
                    (sum(samples) / len(samples))
                    if metric == "avg_latency" and samples
                    else _percentile_50(samples)
                    if metric == "p50_latency"
                    else 0.0
                )
            else:
                totals_for_pct[ekey] = sum(entity_metric_total(k) for k in ranked if k not in top_set)
        else:
            totals_for_pct[ekey] = entity_metric_total(ekey)
        grand_total += abs(totals_for_pct[ekey]) if not is_latency else 0.0

    # % of total for latency: share of requests
    req_total = (sum(entity_req.get(k, 0) for k in ranked) or 1.0) if is_latency else (grand_total or 1.0)

    for idx, ekey in enumerate(table_targets):
        series = entity_bucket_series(ekey)
        nonzero = [v for v in series if v != 0]
        sample_vals = nonzero or series
        if ekey == "__others__":
            label = "Other"
            color = ACTIVITY_CHART_COLORS[min(len(top_keys), len(ACTIVITY_CHART_COLORS) - 1)]
            if is_latency:
                samples = []
                for k in ranked:
                    if k not in top_set:
                        samples.extend(entity_lat.get(k) or [])
                vmin = min(samples) if samples else 0.0
                vmax = max(samples) if samples else 0.0
                vavg = (sum(samples) / len(samples)) if samples else 0.0
                vsum = sum(samples)
                value = totals_for_pct[ekey]
                pct = (sum(entity_req.get(k, 0) for k in ranked if k not in top_set) / req_total) * 100
            else:
                vmin = min(sample_vals) if sample_vals else 0.0
                vmax = max(sample_vals) if sample_vals else 0.0
                vavg = (sum(sample_vals) / len(sample_vals)) if sample_vals else 0.0
                vsum = totals_for_pct[ekey]
                value = vsum
                pct = (vsum / req_total) * 100 if req_total else 0.0
        else:
            label = entity_labels.get(ekey) or ekey
            color = ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)]
            if is_latency:
                samples = entity_lat.get(ekey) or []
                vmin = min(samples) if samples else 0.0
                vmax = max(samples) if samples else 0.0
                vavg = (sum(samples) / len(samples)) if samples else 0.0
                vsum = sum(samples)
                value = totals_for_pct[ekey]
                pct = (entity_req.get(ekey, 0) / req_total) * 100
            else:
                vmin = min(sample_vals) if sample_vals else 0.0
                vmax = max(sample_vals) if sample_vals else 0.0
                vavg = (sum(sample_vals) / len(sample_vals)) if sample_vals else 0.0
                vsum = totals_for_pct[ekey]
                value = vsum
                pct = (vsum / req_total) * 100 if req_total else 0.0
        table.append(
            {
                "key": ekey,
                "label": label,
                "color": color,
                "min": round(vmin, 4),
                "max": round(vmax, 4),
                "avg": round(vavg, 4),
                "sum": round(vsum, 4),
                "value": round(value, 4),
                "pct": round(pct, 1),
                "requests": int(
                    sum(entity_req.get(k, 0) for k in ranked if k not in top_set)
                    if ekey == "__others__"
                    else entity_req.get(ekey, 0)
                ),
            }
        )

    return {
        "metric": metric,
        "group": group,
        "subgroup": sub,
        "rollup": rollup,
        "top_mode": top_mode,
        "top_n": top_n,
        "rank_by": rank_by,
        "show_other": show_other,
        "cumulative": cumulative,
        "chart_type": chart_type,
        "segments": segments,
        "chart": chart,
        "table": table,
        "meta": {"row_count": len(ranked), "entity_count": len(table)},
    }


def _build_overview(
    rows: list[RequestLog],
    prev_rows: list[RequestLog],
    *,
    period: str,
    since: datetime,
    now: datetime,
    tz_mode: str,
) -> dict[str, Any]:
    """OpenRouter-style Overview panel metrics (admin Dashboard)."""
    bucket_keys = _bucket_labels(period, since, now, tz_mode)

    spend_by_b: dict[str, float] = defaultdict(float)
    req_by_b: dict[str, float] = defaultdict(float)
    tok_by_b: dict[str, float] = defaultdict(float)
    prompt_by_b: dict[str, float] = defaultdict(float)
    completion_by_b: dict[str, float] = defaultdict(float)
    cached_by_b: dict[str, float] = defaultdict(float)
    model_spend_b: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    model_req_b: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    model_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"spend": 0.0, "requests": 0.0, "tokens": 0.0})
    user_tokens: dict[str, float] = defaultdict(float)
    app_tokens: dict[str, float] = defaultdict(float)

    cur_spend = 0.0
    cur_prompt = 0.0
    cur_completion = 0.0
    cur_cached = 0.0
    cur_memory = 0.0
    memory_by_b: dict[str, float] = defaultdict(float)

    for r in rows:
        spend = float(r.total_cost_usd or 0)
        prompt = float(r.prompt_tokens or 0)
        completion = float(r.completion_tokens or 0)
        cached = float(r.cached_tokens or 0)
        if cached > prompt:
            cached = prompt
        tokens = prompt + completion
        bkey = _bucket_key(r.request_time or now, period, tz_mode)
        mk = (r.model_id or "unknown").strip() or "unknown"
        uk = (r.username or "unknown").strip() or "unknown"
        ak = _client_app_key(r)

        cur_spend += spend
        if _is_memory_row(r):
            cur_memory += spend
            memory_by_b[bkey] += spend
        cur_prompt += prompt
        cur_completion += completion
        cur_cached += cached

        spend_by_b[bkey] += spend
        req_by_b[bkey] += 1
        tok_by_b[bkey] += tokens
        prompt_by_b[bkey] += prompt
        completion_by_b[bkey] += completion
        cached_by_b[bkey] += cached
        model_spend_b[bkey][mk] += spend
        model_req_b[bkey][mk] += 1
        model_stats[mk]["spend"] += spend
        model_stats[mk]["requests"] += 1
        model_stats[mk]["tokens"] += tokens
        user_tokens[uk] += tokens
        app_tokens[ak] += tokens

    cur_requests = float(len(rows))
    cur_tokens = cur_prompt + cur_completion
    cur_cache_rate = (cur_cached / cur_prompt * 100.0) if cur_prompt > 0 else 0.0
    cur_blended = (cur_spend / cur_tokens * 1_000_000.0) if cur_tokens > 0 else 0.0

    prev_spend = sum(float(r.total_cost_usd or 0) for r in prev_rows)
    prev_requests = float(len(prev_rows))
    prev_prompt = sum(float(r.prompt_tokens or 0) for r in prev_rows)
    prev_completion = sum(float(r.completion_tokens or 0) for r in prev_rows)
    prev_tokens = prev_prompt + prev_completion
    prev_cached = 0.0
    for r in prev_rows:
        c = float(r.cached_tokens or 0)
        p = float(r.prompt_tokens or 0)
        prev_cached += min(c, p) if p > 0 else 0.0
    prev_cache_rate = (prev_cached / prev_prompt * 100.0) if prev_prompt > 0 else 0.0
    prev_blended = (prev_spend / prev_tokens * 1_000_000.0) if prev_tokens > 0 else 0.0
    prev_memory = sum(float(r.total_cost_usd or 0) for r in prev_rows if _is_memory_row(r))

    spark_spend = [spend_by_b.get(k, 0.0) for k in bucket_keys]
    spark_memory = [memory_by_b.get(k, 0.0) for k in bucket_keys]
    spark_req = [req_by_b.get(k, 0.0) for k in bucket_keys]
    spark_tok = [tok_by_b.get(k, 0.0) for k in bucket_keys]
    spark_cache: list[float] = []
    spark_blended: list[float] = []
    for k in bucket_keys:
        p = prompt_by_b.get(k, 0.0)
        t = tok_by_b.get(k, 0.0)
        s = spend_by_b.get(k, 0.0)
        spark_cache.append((cached_by_b.get(k, 0.0) / p * 100.0) if p > 0 else 0.0)
        spark_blended.append((s / t * 1_000_000.0) if t > 0 else 0.0)

    ranked_models = sorted(model_stats.items(), key=lambda x: x[1]["spend"], reverse=True)
    top_models = [m for m, _ in ranked_models[:TOP_SEGMENTS]]
    top_set = set(top_models)
    stack_order = list(top_models)
    if any(m not in top_set for m in model_stats):
        stack_order.append("__others__")

    def _stack(bucket_map: dict[str, dict[str, float]], bkey: str) -> dict[str, float]:
        raw = bucket_map.get(bkey, {})
        out: dict[str, float] = {}
        other = 0.0
        for seg, val in raw.items():
            if seg in top_set:
                out[seg] = out.get(seg, 0.0) + val
            else:
                other += val
        if other > 0:
            out["__others__"] = other
        return out

    usage_by_model_chart: list[dict[str, Any]] = []
    request_volume_chart: list[dict[str, Any]] = []
    for bkey in bucket_keys:
        label = _chart_label(bkey, period, tz_mode)
        spend_row: dict[str, Any] = {"bucket": bkey, "label": label}
        req_row: dict[str, Any] = {"bucket": bkey, "label": label}
        for seg, val in _stack(model_spend_b, bkey).items():
            spend_row[f"spend_{seg}"] = val
        for seg, val in _stack(model_req_b, bkey).items():
            req_row[f"requests_{seg}"] = val
        usage_by_model_chart.append(spend_row)
        request_volume_chart.append(req_row)

    model_segments: list[dict[str, Any]] = []
    for idx, seg in enumerate(stack_order):
        if seg == "__others__":
            stats = {
                "spend": sum(v["spend"] for m, v in ranked_models[TOP_SEGMENTS:]),
                "requests": sum(v["requests"] for m, v in ranked_models[TOP_SEGMENTS:]),
                "tokens": sum(v["tokens"] for m, v in ranked_models[TOP_SEGMENTS:]),
            }
        else:
            stats = model_stats[seg]
        model_segments.append(
            {
                "key": seg,
                "label": segment_label(seg, "model"),
                "color": ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)],
                "spend": stats["spend"],
                "requests": int(stats["requests"]),
                "tokens": int(stats["tokens"]),
            }
        )

    token_breakdown_chart: list[dict[str, Any]] = []
    cache_chart: list[dict[str, Any]] = []
    for bkey in bucket_keys:
        label = _chart_label(bkey, period, tz_mode)
        prompt = prompt_by_b.get(bkey, 0.0)
        cached = min(cached_by_b.get(bkey, 0.0), prompt)
        token_breakdown_chart.append(
            {
                "bucket": bkey,
                "label": label,
                "prompt": prompt,
                "completion": completion_by_b.get(bkey, 0.0),
            }
        )
        cache_chart.append(
            {
                "bucket": bkey,
                "label": label,
                "uncached": max(0.0, prompt - cached),
                "cached": cached,
            }
        )

    def _top_list(stats: dict[str, float]) -> list[dict[str, Any]]:
        ranked = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:TOP_OVERVIEW_LIST]
        out: list[dict[str, Any]] = []
        for key, tokens in ranked:
            if tokens <= 0:
                continue
            parts = [p for p in key.replace(".", " ").replace("@", " ").split() if p]
            initials = (parts[0][0] + parts[1][0]).upper() if len(parts) >= 2 else (key[:2] or "?").upper()
            out.append({"key": key, "label": key, "initials": initials, "tokens": int(tokens)})
        return out

    return {
        "kpis": {
            "spend": _kpi_dict(cur_spend, prev_spend, spark_spend),
            "requests": _kpi_dict(cur_requests, prev_requests, spark_req),
            "tokens": _kpi_dict(cur_tokens, prev_tokens, spark_tok),
            "cache_hit_rate": _kpi_dict(cur_cache_rate, prev_cache_rate, spark_cache),
            "blended_per_1m": _kpi_dict(cur_blended, prev_blended, spark_blended),
            # Part of total spend, not additional to it. It earns a card of its
            # own because nobody asks for it: it is the one line here that is
            # spent on someone's behalf rather than by them.
            "memory_spend": _kpi_dict(cur_memory, prev_memory, spark_memory),
        },
        "top_users": _top_list(user_tokens),
        "top_apps": _top_list(app_tokens),
        "usage_by_model": {
            "segments": model_segments,
            "chart": usage_by_model_chart,
        },
        "request_volume_by_model": {
            "segments": model_segments,
            "chart": request_volume_chart,
        },
        "token_breakdown": {
            "segments": [
                {
                    "key": "prompt",
                    "label": "Prompt",
                    "color": OVERVIEW_TOKEN_COLORS["prompt"],
                },
                {
                    "key": "completion",
                    "label": "Completion",
                    "color": OVERVIEW_TOKEN_COLORS["completion"],
                },
            ],
            "chart": token_breakdown_chart,
        },
        "prompt_caching": {
            "segments": [
                {
                    "key": "uncached",
                    "label": "Uncached",
                    "color": OVERVIEW_CACHE_COLORS["uncached"],
                },
                {
                    "key": "cached",
                    "label": "Cached",
                    "color": OVERVIEW_CACHE_COLORS["cached"],
                },
            ],
            "chart": cache_chart,
        },
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
    heatmap_daily: dict[str, dict[str, float]] | None = None,
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
        heatmap_daily=heatmap_daily,
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
    heatmap_daily: dict[str, dict[str, float]] | None = None,
    api_key_meta: dict[str, dict[str, Any]] | None = None,
    explore: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or datetime.utcnow()
    group_by = group_by if group_by in ("model", "app", "user") else "model"
    tz_mode = timezone if timezone in ("local", "utc") else "local"
    explore_opts = explore or {}

    segment_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"spend": 0.0, "requests": 0.0, "tokens": 0.0})
    bucket_spend: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    bucket_requests: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    bucket_tokens: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

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
    if any(m not in top_set for m in segment_stats):
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

    model_only: dict[str, dict[str, float]] = defaultdict(lambda: {"spend": 0.0, "requests": 0.0, "tokens": 0.0})
    for r in rows:
        mk = (r.model_id or "unknown").strip() or "unknown"
        model_only[mk]["spend"] += float(r.total_cost_usd or 0)
        model_only[mk]["requests"] += 1
        model_only[mk]["tokens"] += float((r.prompt_tokens or 0) + (r.completion_tokens or 0))

    daily = (
        heatmap_daily
        if heatmap_daily is not None
        else _aggregate_daily_metrics(heatmap_rows if heatmap_rows is not None else rows, tz_mode)
    )
    insights = _build_insights(
        rows,
        prev_rows or [],
        daily,
        period=period,
        since=since,
        now=now,
        tz_mode=tz_mode,
    )

    overview = _build_overview(
        rows,
        prev_rows or [],
        period=period,
        since=since,
        now=now,
        tz_mode=tz_mode,
    )
    trends = _build_trends(
        rows,
        prev_rows or [],
        period=period,
        since=since,
        now=now,
        tz_mode=tz_mode,
        api_key_meta=api_key_meta,
    )
    explore_payload = build_explore(
        rows,
        since=since,
        now=now,
        tz_mode=tz_mode,
        metric=str(explore_opts.get("metric") or "total_usage"),
        group=str(explore_opts.get("group") or "model"),
        subgroup=explore_opts.get("subgroup"),
        rollup=str(explore_opts.get("rollup") or "daily"),
        top_mode=str(explore_opts.get("top_mode") or "top"),
        top_n=int(explore_opts.get("top_n") or 10),
        rank_by=str(explore_opts.get("rank_by") or "metric"),
        show_other=bool(explore_opts.get("show_other", True)),
        cumulative=bool(explore_opts.get("cumulative", False)),
        chart_type=str(explore_opts.get("chart_type") or "bar"),
        api_key_meta=api_key_meta,
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
        "overview": overview,
        "trends": trends,
        "explore": explore_payload,
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
