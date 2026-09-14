"""Operations dashboard: record and chart system metric snapshots."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import PRODUCT_NAME
from app.models.logging import RequestLog
from app.models.system import SystemMetricSnapshot
from app.services.activity_service import ACTIVITY_CHART_COLORS
from app.services.db_monitor_service import collect_snapshot_metrics
from app.services.operations_time_range import (
    OpsTimeRange,
    ops_time_range_payload,
    resolve_ops_time_range,
)
from app.utils.display import format_app_source

OPS_COLORS = {
    "host": ACTIVITY_CHART_COLORS[0],
    "process": ACTIVITY_CHART_COLORS[4],
    "ping": ACTIVITY_CHART_COLORS[2],
}

RETENTION_DAYS = 14
TOP_LOG_SOURCES = 5
SLOW_REQUEST_MS = 10_000  # requests slower than this count as "slow UX"
TOP_SLOW_MODELS_TABLE = 10
TOP_MODELS_CHART = 3
MIN_REQUESTS_PER_MODEL = 3  # ignore models with fewer samples in rankings


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return float(ordered[idx])


def _source_key(source: str | None) -> str:
    raw = (source or "unknown").strip().lower() or "unknown"
    safe = "".join(c if c.isalnum() else "_" for c in raw)
    return f"src_{safe}"


def _model_key(model_id: str | None) -> str:
    raw = (model_id or "unknown").strip() or "unknown"
    safe = "".join(c if c.isalnum() or c in "._-:" else "_" for c in raw)[:72]
    return f"mdl_{safe}"


def _pct_change(current: float, previous: float) -> float | None:
    if previous <= 0:
        return 100.0 if current > 0 else None
    return round(((current - previous) / previous) * 100, 1)


async def _fetch_logs_since(db: AsyncSession, since: datetime, until: datetime | None = None) -> list[RequestLog]:
    q = select(RequestLog).where(RequestLog.request_time >= since)
    if until is not None:
        q = q.where(RequestLog.request_time < until)
    return (await db.execute(q.order_by(RequestLog.request_time.asc()))).scalars().all()


def _naive_utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


def _utc_epoch(ts: datetime) -> int:
    """Epoch seconds; naive datetimes are treated as UTC (avoids local TZ skew on Windows)."""
    if ts.tzinfo is not None:
        return int(ts.timestamp())
    return calendar.timegm(_naive_utc(ts).timetuple())


def _utc_from_epoch(epoch: int) -> datetime:
    return datetime.utcfromtimestamp(epoch)


def _bucket_key_ts(ts: datetime, bucket_seconds: int) -> str:
    epoch = _utc_epoch(ts)
    return str(epoch - (epoch % bucket_seconds))


def _bucket_label_ts(start: datetime, bucket_seconds: int) -> str:
    if bucket_seconds < 3600:
        return start.strftime("%H:%M")
    if bucket_seconds < 86400:
        return start.strftime("%H:%M")
    if bucket_seconds < 604800:
        return start.strftime("%a %d")
    return start.strftime("%b %d")


def _bucket_starts(tr: OpsTimeRange) -> list[datetime]:
    until_epoch = _utc_epoch(tr.until)
    last_slot = until_epoch - (until_epoch % tr.bucket_seconds)
    return [_utc_from_epoch(last_slot - i * tr.bucket_seconds) for i in range(tr.bucket_count - 1, -1, -1)]


def _logs_by_bucket(logs: list[RequestLog], tr: OpsTimeRange) -> dict[str, list[RequestLog]]:
    buckets: dict[str, list[RequestLog]] = defaultdict(list)
    for row in logs:
        ts = _naive_utc(row.request_time or tr.until)
        if ts < tr.since or ts >= tr.until:
            continue
        buckets[_bucket_key_ts(ts, tr.bucket_seconds)].append(row)
    return buckets


def _build_api_traffic_cards_from_logs(logs: list[RequestLog], *, tr: OpsTimeRange) -> dict[str, Any]:
    """Errors, latency, and throughput from request_logs for the selected window."""
    log_buckets = _logs_by_bucket(logs, tr)

    latencies_all = [float(r.response_time_ms) for r in logs if r.response_time_ms is not None]
    failed = [r for r in logs if not r.success]
    avg_latency = _avg(latencies_all)
    p95_latency = _p95(latencies_all)

    error_by_source: dict[str, int] = defaultdict(int)
    req_by_source: dict[str, int] = defaultdict(int)
    for r in logs:
        sk = _source_key(r.source)
        req_by_source[sk] += 1
        if not r.success:
            error_by_source[sk] += 1

    top_error_sources = sorted(error_by_source.keys(), key=lambda k: error_by_source[k], reverse=True)[:TOP_LOG_SOURCES]
    top_req_sources = sorted(req_by_source.keys(), key=lambda k: req_by_source[k], reverse=True)[:TOP_LOG_SOURCES]

    errors_chart: list[dict[str, Any]] = []
    throughput_chart: list[dict[str, Any]] = []
    latency_chart: list[dict[str, Any]] = []

    for start in _bucket_starts(tr):
        key = _bucket_key_ts(start, tr.bucket_seconds)
        bucket_logs = log_buckets.get(key, [])
        label = _bucket_label_ts(start, tr.bucket_seconds)

        err_point: dict[str, Any] = {"label": label}
        for sk in top_error_sources:
            err_point[sk] = sum(1 for r in bucket_logs if not r.success and _source_key(r.source) == sk)
        errors_chart.append(err_point)

        thr_point: dict[str, Any] = {"label": label}
        for sk in top_req_sources:
            thr_point[sk] = sum(1 for r in bucket_logs if _source_key(r.source) == sk)
        throughput_chart.append(thr_point)

        bucket_lats = [float(r.response_time_ms) for r in bucket_logs if r.response_time_ms is not None]
        latency_chart.append(
            {
                "label": label,
                "latency_avg_ms": round(_avg(bucket_lats), 1),
                "latency_p95_ms": round(_p95(bucket_lats), 1),
            }
        )

    def _segments_from_totals(totals: dict[str, int], top_keys: list[str]) -> list[dict[str, Any]]:
        segs = []
        for idx, sk in enumerate(top_keys):
            if totals.get(sk, 0) <= 0:
                continue
            # Recover display label from first matching log source
            label = sk.replace("src_", "", 1).replace("_", " ").title()
            for r in logs:
                if _source_key(r.source) == sk:
                    label = format_app_source(r.source)
                    break
            segs.append(
                {
                    "key": sk,
                    "label": label,
                    "color": ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)],
                    "value": totals[sk],
                }
            )
        return segs

    return {
        "errors": {
            "title": "Errors",
            "total": len(failed),
            "unit": "",
            "segments": _segments_from_totals(error_by_source, top_error_sources),
            "chart": errors_chart,
            "footer": {
                "label": "Error rate",
                "value": round((len(failed) / len(logs) * 100) if logs else 0, 2),
                "suffix": "%",
            },
        },
        "latency": {
            "title": "Latency",
            "total": round(p95_latency, 0),
            "unit": "ms",
            "segments": [
                {
                    "key": "latency_avg_ms",
                    "label": "Avg (period)",
                    "color": ACTIVITY_CHART_COLORS[0],
                    "value": round(avg_latency, 1),
                },
                {
                    "key": "latency_p95_ms",
                    "label": "P95 (period)",
                    "color": ACTIVITY_CHART_COLORS[1],
                    "value": round(p95_latency, 1),
                },
            ],
            "chart": latency_chart,
            "footer": {
                "label": f"Avg ({tr.period_short})",
                "value": round(avg_latency, 1),
                "suffix": "ms",
            },
        },
        "throughput": {
            "title": "Throughput",
            "total": len(logs),
            "unit": "",
            "segments": _segments_from_totals(req_by_source, top_req_sources),
            "chart": throughput_chart,
            "footer": {
                "label": "Success",
                "value": len(logs) - len(failed),
                "suffix": "",
            },
        },
        "request_log_count": len(logs),
    }


async def _build_api_traffic_cards(db: AsyncSession, *, tr: OpsTimeRange) -> dict[str, Any]:
    logs = await _fetch_logs_since(db, tr.since, until=tr.until)
    return _build_api_traffic_cards_from_logs(logs, tr=tr)


def _model_stats(logs: list[RequestLog]) -> dict[str, dict[str, Any]]:
    by_model: dict[str, list[RequestLog]] = defaultdict(list)
    for r in logs:
        mid = (r.model_id or "unknown").strip() or "unknown"
        by_model[mid].append(r)
    stats: dict[str, dict[str, Any]] = {}
    for mid, rows in by_model.items():
        lats = [float(r.response_time_ms) for r in rows if r.response_time_ms is not None]
        failed = sum(1 for r in rows if not r.success)
        stats[mid] = {
            "model_id": mid,
            "requests": len(rows),
            "avg_ms": round(_avg(lats), 1),
            "p95_ms": round(_p95(lats), 1),
            "error_pct": round((failed / len(rows) * 100) if rows else 0, 2),
        }
    return stats


def _build_model_experience(
    logs_cur: list[RequestLog],
    logs_prev: list[RequestLog],
    *,
    tr: OpsTimeRange,
) -> dict[str, Any]:
    log_buckets = _logs_by_bucket(logs_cur, tr)

    slow_cur = [r for r in logs_cur if (r.response_time_ms or 0) >= SLOW_REQUEST_MS]
    slow_by_source: dict[str, int] = defaultdict(int)
    for r in slow_cur:
        slow_by_source[_source_key(r.source)] += 1
    top_slow_sources = sorted(slow_by_source.keys(), key=lambda k: slow_by_source[k], reverse=True)[:TOP_LOG_SOURCES]

    slow_chart: list[dict[str, Any]] = []
    for start in _bucket_starts(tr):
        key = _bucket_key_ts(start, tr.bucket_seconds)
        bucket_logs = log_buckets.get(key, [])
        point: dict[str, Any] = {"label": _bucket_label_ts(start, tr.bucket_seconds)}
        for sk in top_slow_sources:
            point[sk] = sum(
                1 for r in bucket_logs if (r.response_time_ms or 0) >= SLOW_REQUEST_MS and _source_key(r.source) == sk
            )
        slow_chart.append(point)

    def _slow_segments() -> list[dict[str, Any]]:
        segs = []
        for idx, sk in enumerate(top_slow_sources):
            if slow_by_source[sk] <= 0:
                continue
            label = sk.replace("src_", "", 1).title()
            for r in logs_cur:
                if _source_key(r.source) == sk:
                    label = format_app_source(r.source)
                    break
            segs.append(
                {
                    "key": sk,
                    "label": label,
                    "color": ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)],
                    "value": slow_by_source[sk],
                }
            )
        return segs

    lats_cur = [float(r.response_time_ms) for r in logs_cur if r.response_time_ms is not None]
    lats_prev = [float(r.response_time_ms) for r in logs_prev if r.response_time_ms is not None]
    p95_cur = _p95(lats_cur)
    p95_prev = _p95(lats_prev)
    p95_change = _pct_change(p95_cur, p95_prev)

    p95_chart: list[dict[str, Any]] = []
    for start in _bucket_starts(tr):
        key = _bucket_key_ts(start, tr.bucket_seconds)
        bucket_logs = log_buckets.get(key, [])
        bucket_lats = [float(r.response_time_ms) for r in bucket_logs if r.response_time_ms is not None]
        p95_chart.append({"label": _bucket_label_ts(start, tr.bucket_seconds), "p95_ms": round(_p95(bucket_lats), 1)})

    stats_cur = _model_stats(logs_cur)
    ranked_models = sorted(
        [s for s in stats_cur.values() if s["requests"] >= MIN_REQUESTS_PER_MODEL],
        key=lambda s: s["p95_ms"],
        reverse=True,
    )
    slowest_table = ranked_models[:TOP_SLOW_MODELS_TABLE]

    by_volume = sorted(
        [s for s in stats_cur.values() if s["requests"] >= MIN_REQUESTS_PER_MODEL],
        key=lambda s: s["requests"],
        reverse=True,
    )
    chart_models = by_volume[:TOP_MODELS_CHART]
    chart_keys = [_model_key(m["model_id"]) for m in chart_models]

    models_chart: list[dict[str, Any]] = []
    for start in _bucket_starts(tr):
        key = _bucket_key_ts(start, tr.bucket_seconds)
        bucket_logs = log_buckets.get(key, [])
        point: dict[str, Any] = {"label": _bucket_label_ts(start, tr.bucket_seconds)}
        for mk, mid in zip(chart_keys, [m["model_id"] for m in chart_models], strict=False):
            bl = [
                float(r.response_time_ms) for r in bucket_logs if r.model_id == mid and r.response_time_ms is not None
            ]
            point[mk] = round(_p95(bl), 1)
        models_chart.append(point)

    model_segments = []
    for idx, m in enumerate(chart_models):
        mk = _model_key(m["model_id"])
        short = m["model_id"] if len(m["model_id"]) <= 36 else f"{m['model_id'][:33]}…"
        model_segments.append(
            {
                "key": mk,
                "label": short,
                "color": ACTIVITY_CHART_COLORS[idx % len(ACTIVITY_CHART_COLORS)],
                "value": m["p95_ms"],
            }
        )

    return {
        "slow_request_threshold_ms": SLOW_REQUEST_MS,
        "cards": {
            "slow_requests": {
                "title": "Slow requests",
                "total": len(slow_cur),
                "unit": "",
                "change_pct": None,
                "segments": _slow_segments(),
                "chart": slow_chart,
                "footer": {
                    "label": "Share of traffic",
                    "value": round((len(slow_cur) / len(logs_cur) * 100) if logs_cur else 0, 2),
                    "suffix": "%",
                },
            },
            "p95_vs_prior": {
                "title": "P95 latency",
                "total": round(p95_cur, 0),
                "unit": "ms",
                "change_pct": p95_change,
                "segments": [
                    {
                        "key": "p95_ms",
                        "label": f"Current ({tr.period_short})",
                        "color": ACTIVITY_CHART_COLORS[0],
                        "value": round(p95_cur, 1),
                    },
                ],
                "chart": p95_chart,
                "footer": {
                    "label": f"Prior ({tr.period_short}) P95",
                    "value": round(p95_prev, 1),
                    "suffix": "ms",
                },
            },
            "models_p95": {
                "title": "Model P95 (top traffic)",
                "total": round(slowest_table[0]["p95_ms"], 0) if slowest_table else 0,
                "unit": "ms",
                "change_pct": None,
                "segments": model_segments,
                "chart": models_chart,
                "footer": {
                    "label": "Models tracked",
                    "value": len([s for s in stats_cur.values() if s["requests"] >= MIN_REQUESTS_PER_MODEL]),
                    "suffix": "",
                },
            },
        },
        "slowest_models": slowest_table,
    }


async def record_system_snapshot(db: AsyncSession) -> SystemMetricSnapshot:
    metrics = await collect_snapshot_metrics(db)
    row = SystemMetricSnapshot(
        recorded_at=datetime.utcnow(),
        db_engine=metrics.get("db_engine"),
        host_cpu_percent=metrics.get("host_cpu_percent"),
        host_memory_percent=metrics.get("host_memory_percent"),
        process_cpu_percent=metrics.get("process_cpu_percent"),
        process_rss_bytes=metrics.get("process_rss_bytes"),
        db_ping_ms=metrics.get("db_ping_ms"),
        db_size_bytes=metrics.get("db_size_bytes"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def prune_old_snapshots(db: AsyncSession) -> int:
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    result = await db.execute(delete(SystemMetricSnapshot).where(SystemMetricSnapshot.recorded_at < cutoff))
    await db.commit()
    return result.rowcount or 0


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _build_snapshot_chart(
    snapshots: list[SystemMetricSnapshot],
    *,
    tr: OpsTimeRange,
    fields: tuple[tuple[str, str], ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (chart_rows, segments meta with period averages for legend)."""
    by_bucket: dict[str, list[SystemMetricSnapshot]] = defaultdict(list)
    for s in snapshots:
        if not s.recorded_at:
            continue
        ts = _naive_utc(s.recorded_at)
        if ts < tr.since or ts >= tr.until:
            continue
        key = _bucket_key_ts(ts, tr.bucket_seconds)
        by_bucket[key].append(s)

    chart_rows: list[dict[str, Any]] = []
    accum: dict[str, list[float]] = {fk: [] for fk, _ in fields}

    for start in _bucket_starts(tr):
        key = _bucket_key_ts(start, tr.bucket_seconds)
        rows = by_bucket.get(key, [])
        point: dict[str, Any] = {"label": _bucket_label_ts(start, tr.bucket_seconds)}
        for fk, _ in fields:
            vals = []
            for r in rows:
                v = getattr(r, fk, None)
                if v is not None:
                    vals.append(float(v))
            avg = _avg(vals)
            point[fk] = round(avg, 2)
            if vals:
                accum[fk].extend(vals)
        chart_rows.append(point)

    segments = []
    for fk, label in fields:
        segments.append(
            {
                "key": fk,
                "label": label,
                "color": OPS_COLORS.get(
                    "host" if fk.startswith("host") else "process" if "process" in fk else "ping",
                    ACTIVITY_CHART_COLORS[5],
                ),
                "value": round(_avg(accum[fk]), 2),
            }
        )
    return chart_rows, segments


async def get_operations_dashboard(
    db: AsyncSession,
    *,
    record: bool = False,
    range_key: str | None = None,
) -> dict[str, Any]:
    tr = resolve_ops_time_range(range_key)
    if record:
        await record_system_snapshot(db)
        await prune_old_snapshots(db)

    snapshots = (
        (
            await db.execute(
                select(SystemMetricSnapshot)
                .where(SystemMetricSnapshot.recorded_at >= tr.since)
                .where(SystemMetricSnapshot.recorded_at < tr.until)
                .order_by(SystemMetricSnapshot.recorded_at.asc())
            )
        )
        .scalars()
        .all()
    )

    latest = snapshots[-1] if snapshots else None
    if not latest and not record:
        # Seed one point so the dashboard is not empty on first visit.
        latest = await record_system_snapshot(db)
        snapshots = [latest]

    last_checked = latest.recorded_at.isoformat() + "Z" if latest and latest.recorded_at else None

    cpu_chart, cpu_segments = _build_snapshot_chart(
        snapshots,
        tr=tr,
        fields=(
            ("host_cpu_percent", "Host CPU"),
            ("process_cpu_percent", f"{PRODUCT_NAME} process"),
        ),
    )
    mem_chart, mem_segments = _build_snapshot_chart(
        snapshots,
        tr=tr,
        fields=(("host_memory_percent", "Host RAM"),),
    )
    ping_chart, ping_segments = _build_snapshot_chart(
        snapshots,
        tr=tr,
        fields=(("db_ping_ms", "DB ping"),),
    )

    host_cpu = float(latest.host_cpu_percent or 0) if latest else 0
    host_mem = float(latest.host_memory_percent or 0) if latest else 0
    db_ping = float(latest.db_ping_ms or 0) if latest else 0
    db_size = int(latest.db_size_bytes or 0) if latest else 0
    process_rss = int(latest.process_rss_bytes or 0) if latest else 0

    logs_cur = await _fetch_logs_since(db, tr.since, until=tr.until)
    logs_prev = await _fetch_logs_since(db, tr.compare_since, until=tr.compare_until)

    traffic = _build_api_traffic_cards_from_logs(logs_cur, tr=tr)
    model_experience = _build_model_experience(logs_cur, logs_prev, tr=tr)

    return {
        "last_checked_at": last_checked,
        "auto_refresh_interval_seconds": 3600,
        "chart_hours": tr.bucket_count,
        "time_range": ops_time_range_payload(tr),
        "db_engine": latest.db_engine if latest else None,
        "cards": {
            "cpu": {
                "title": "CPU",
                "total": round(host_cpu, 1),
                "unit": "%",
                "segments": cpu_segments,
                "chart": cpu_chart,
            },
            "memory": {
                "title": "Memory",
                "total": round(host_mem, 1),
                "unit": "%",
                "segments": mem_segments,
                "chart": mem_chart,
                "footer": {"label": f"{PRODUCT_NAME} RSS", "value": process_rss},
            },
            "database": {
                "title": "Database",
                "total": round(db_ping, 2),
                "unit": "ms",
                "segments": ping_segments,
                "chart": ping_chart,
                "footer": {"label": "DB size", "value": db_size},
            },
            "errors": traffic["errors"],
            "latency": traffic["latency"],
            "throughput": traffic["throughput"],
            **model_experience["cards"],
        },
        "model_experience": {
            "slow_request_threshold_ms": model_experience["slow_request_threshold_ms"],
            "slowest_models": model_experience["slowest_models"],
        },
        "snapshot_count": len(snapshots),
        "request_log_count": traffic["request_log_count"],
    }
