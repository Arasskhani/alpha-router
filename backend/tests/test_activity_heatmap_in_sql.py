"""Opening Activity must not read a year of request logs.

``_load_activity_context`` widened every query to at least
``HEATMAP_DAYS`` - 365 days - because the heatmap needed daily totals over a
year, and the only way it knew to get them was to load every row and count
them in Python. So "last 15 minutes" on the Activity dashboard was a full
one-year scan of ``request_logs``, materialised as ORM objects, walked four or
five times.

The heatmap needs three numbers per day. That is a GROUP BY.
"""

from __future__ import annotations

import datetime

import pytest

from app.models.logging import RequestLog
from app.services.activity_service import HEATMAP_DAYS, _aggregate_daily_metrics
from app.services.activity_rollup_service import daily_activity_metrics


async def _log(db_session, *, days_ago: float, user_id: int | None = None, **overrides) -> RequestLog:
    values = {
        "user_id": user_id,
        "username": "alice",
        "model_id": "openai/gpt-4o",
        "source": "chat",
        "success": True,
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_cost_usd": 0.25,
        "request_time": datetime.datetime.utcnow() - datetime.timedelta(days=days_ago),
    }
    values.update(overrides)
    row = RequestLog(**values)
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.parametrize("tz_mode", ["utc", "local"])
async def test_the_rollup_agrees_with_counting_the_rows(db_session, user, tz_mode):
    """The proof for moving work into SQL: the same answer."""

    for days_ago in (0.1, 0.2, 1.3, 5.0, 40.0, 200.0):
        await _log(db_session, days_ago=days_ago, user_id=user.id)
    await _log(db_session, days_ago=2.0, user_id=user.id, prompt_tokens=None, total_cost_usd=None)
    await db_session.commit()

    since = datetime.datetime.utcnow() - datetime.timedelta(days=HEATMAP_DAYS)
    rows = [row for row in (await _all_rows(db_session)) if (row.request_time or since) >= since]

    from_sql = await daily_activity_metrics(db_session, since=since, tz_mode=tz_mode, scope={}, filters={})
    from_python = _aggregate_daily_metrics(rows, tz_mode)

    assert _rounded(from_sql) == _rounded(from_python)


async def _all_rows(db_session):
    from sqlalchemy import select

    return (await db_session.execute(select(RequestLog))).scalars().all()


def _rounded(daily: dict) -> dict:
    return {
        day: {key: round(float(value), 6) for key, value in metrics.items()} for day, metrics in sorted(daily.items())
    }


async def test_the_scope_and_the_filters_both_apply(db_session, user, admin):
    await _log(db_session, days_ago=1.0, user_id=user.id, model_id="openai/gpt-4o")
    await _log(db_session, days_ago=1.0, user_id=user.id, model_id="anthropic/claude")
    await _log(db_session, days_ago=1.0, user_id=admin.id, model_id="openai/gpt-4o")
    await db_session.commit()

    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    scoped = await daily_activity_metrics(
        db_session,
        since=since,
        tz_mode="utc",
        scope={"user_id": user.id},
        filters={"model_id": "openai/gpt-4o"},
    )

    assert sum(day["requests"] for day in scoped.values()) == 1


async def test_a_failed_request_is_excluded_by_the_status_filter(db_session, user):
    await _log(db_session, days_ago=1.0, user_id=user.id, success=True)
    await _log(db_session, days_ago=1.0, user_id=user.id, success=False)
    await db_session.commit()

    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    failed = await daily_activity_metrics(
        db_session, since=since, tz_mode="utc", scope={}, filters={"response_status": "fail"}
    )

    assert sum(day["requests"] for day in failed.values()) == 1


async def test_an_impossible_scope_reads_nothing(db_session, user):
    await _log(db_session, days_ago=1.0, user_id=user.id)
    await db_session.commit()

    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    empty = await daily_activity_metrics(db_session, since=since, tz_mode="utc", scope={"user_ids": []}, filters={})

    assert empty == {}


async def test_a_short_period_no_longer_reads_a_year(db_session, user, monkeypatch):
    """The finding itself: the window asked for was always at least 365 days."""

    from app.api import admin as admin_api

    seen: list[datetime.datetime] = []
    real = admin_api._fetch_logs_since

    async def recording(db, since, **kwargs):
        seen.append(since)
        return await real(db, since, **kwargs)

    monkeypatch.setattr(admin_api, "_fetch_logs_since", recording)

    await admin_api._load_activity_context(
        db_session,
        period="day",
        group_by="model",
        timezone="utc",
        filters={},
        user_id=user.id,
    )

    assert seen, "no row fetch happened at all"
    oldest = min(seen)
    age_days = (datetime.datetime.utcnow() - oldest).days
    assert age_days < HEATMAP_DAYS - 1, f"a one-day view still asked for {age_days} days of request logs"
