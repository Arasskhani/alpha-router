"""Code Interpreter capacity as a series, not a number read at page load.

The page showed "0.0% utilized" — true at the instant of the request and
useless for the decision the same card asks the operator to make. Setting a
concurrency ceiling needs the peak and the refusals, over a window.

Two series of different kinds share one card. Leases held is a gauge and is
averaged per bucket. Refusals come from a running total in Redis, and the
bucket value is the rise across it: averaging a counter is meaningless, and
differencing from the last reading *before* the bucket is what stops a refusal
falling between two buckets.
"""

from __future__ import annotations

import datetime


from app.models.system import SystemMetricSnapshot
from app.services.operations_service import _build_capacity_chart, resolve_ops_time_range


def _snapshot(hours_ago: float, *, active: int | None = 0, total: int | None = 0) -> SystemMetricSnapshot:
    return SystemMetricSnapshot(
        recorded_at=datetime.datetime.utcnow() - datetime.timedelta(hours=hours_ago),
        code_interpreter_active=active,
        code_interpreter_rejected_total=total,
    )


def _chart(rows: list[SystemMetricSnapshot]):
    tr = resolve_ops_time_range("past_1d")
    return _build_capacity_chart(sorted(rows, key=lambda r: r.recorded_at), tr=tr)


def test_the_peak_is_reported_not_the_last_reading():
    """The number on the card answers "how close did we come to the ceiling",
    which the most recent sample cannot."""
    _rows, _segments, peak, _rejected = _chart(
        [_snapshot(6, active=41), _snapshot(3, active=7), _snapshot(1, active=0)]
    )
    assert peak == 41


def test_refusals_are_counted_as_the_rise_in_the_running_total():
    _rows, _segments, _peak, rejected = _chart(
        [_snapshot(6, total=10), _snapshot(4, total=13), _snapshot(2, total=13), _snapshot(1, total=20)]
    )
    # 10 -> 20 inside the window, measured from the first reading in it.
    assert rejected == 10


def test_a_reading_before_the_window_anchors_the_first_bucket():
    """Without it the first bucket would report every rejection since the
    counter started, which is not what "past 1 day" means."""
    _rows, _segments, _peak, rejected = _chart([_snapshot(40, total=1000), _snapshot(2, total=1004)])
    assert rejected == 4


def test_a_restarted_counter_does_not_draw_a_negative_spike():
    """Redis lost its data; the count before the restart is genuinely gone and
    inventing it would be worse than losing it."""
    _rows, _segments, _peak, rejected = _chart([_snapshot(6, total=900), _snapshot(2, total=5)])
    assert rejected == 0
    assert all(row["code_interpreter_rejected"] >= 0 for row in _rows)


def test_a_snapshot_that_could_not_read_redis_is_not_charted_as_zero():
    """NULL means "could not tell". Averaging it in as a zero would draw a calm
    hour over an outage."""
    rows, segments, peak, _rejected = _chart(
        [_snapshot(5, active=30, total=None), _snapshot(4, active=None, total=None)]
    )
    assert peak == 30
    active_segment = next(s for s in segments if s["key"] == "code_interpreter_active")
    assert active_segment["value"] == 30.0


def test_an_empty_history_charts_flat_rather_than_failing():
    rows, segments, peak, rejected = _chart([])
    assert peak == 0 and rejected == 0
    assert rows and all(row["code_interpreter_active"] == 0 for row in rows)
    assert {s["key"] for s in segments} == {"code_interpreter_active", "code_interpreter_rejected"}


def test_every_bucket_of_the_window_is_present_even_without_samples():
    """The chart is a time axis, not a list of the points that happen to exist."""
    tr = resolve_ops_time_range("past_1d")
    rows, _segments, _peak, _rejected = _chart([_snapshot(2, active=1, total=1)])
    assert len(rows) == tr.bucket_count


async def test_the_snapshot_records_both_readings(db_session, monkeypatch):
    """The collector has to actually write them, or the chart is always empty."""
    from app.services.operations_service import record_system_snapshot

    async def fake_stats():
        return {"active": 3, "limit": 200, "available": 197}

    async def fake_total():
        return 12

    monkeypatch.setattr("app.services.code_interpreter_capacity_service.code_interpreter_capacity_stats", fake_stats)
    monkeypatch.setattr("app.services.code_interpreter_capacity_service.code_interpreter_rejected_total", fake_total)
    row = await record_system_snapshot(db_session)
    assert row.code_interpreter_active == 3
    assert row.code_interpreter_rejected_total == 12


async def test_a_redis_outage_leaves_the_readings_null_and_the_snapshot_intact(db_session, monkeypatch):
    from app.services.operations_service import record_system_snapshot

    async def boom():
        raise RuntimeError("redis down")

    async def none_total():
        return None

    monkeypatch.setattr("app.services.code_interpreter_capacity_service.code_interpreter_capacity_stats", boom)
    monkeypatch.setattr("app.services.code_interpreter_capacity_service.code_interpreter_rejected_total", none_total)
    row = await record_system_snapshot(db_session)
    assert row.code_interpreter_active is None
    assert row.code_interpreter_rejected_total is None
    assert row.recorded_at is not None
