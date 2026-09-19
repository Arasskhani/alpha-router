"""``request_logs`` has a retention window, like every other growing table.

Five retention jobs already existed - media, user media, chat, admin logs and
raw provider payloads. ``request_logs`` is one row per API call, so it is the
fastest-growing table in the product, and nothing ever removed a row from it.
The API Logs page therefore got slower forever and the database grew without
bound on an installation nobody was watching.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select

from app.models.logging import RequestLog
from app.services.request_log_retention_service import (
    DEFAULT_RETENTION_DAYS,
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    PURGE_BATCH_SIZE,
    clamp_retention_days,
    get_request_log_retention,
    purge_expired_request_logs,
    set_retention_days,
)


async def _log(db_session, *, age_days: int, user_id: int | None = None) -> RequestLog:
    row = RequestLog(
        user_id=user_id,
        model_id="test/model",
        request_time=datetime.datetime.utcnow() - datetime.timedelta(days=age_days),
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, MIN_RETENTION_DAYS),
        (-5, MIN_RETENTION_DAYS),
        (100_000, MAX_RETENTION_DAYS),
        ("45", 45),
        (None, DEFAULT_RETENTION_DAYS),
        ("nonsense", DEFAULT_RETENTION_DAYS),
    ],
)
def test_the_window_is_clamped_to_something_sane(value, expected):
    assert clamp_retention_days(value) == expected


async def test_old_rows_go_and_recent_ones_stay(db_session, user):
    await _log(db_session, age_days=400, user_id=user.id)
    await _log(db_session, age_days=10, user_id=user.id)
    await db_session.commit()

    result = await purge_expired_request_logs(db_session, retention_days=180)

    assert result["rows_deleted"] == 1
    remaining = (await db_session.execute(select(RequestLog))).scalars().all()
    assert len(remaining) == 1


async def test_the_operator_sees_what_a_change_would_remove(db_session, user):
    await _log(db_session, age_days=400, user_id=user.id)
    await _log(db_session, age_days=10, user_id=user.id)
    await db_session.commit()

    await set_retention_days(db_session, 365)
    wide = await get_request_log_retention(db_session)
    assert wide["stored_rows"] == 2
    assert wide["expired_rows"] == 1

    await set_retention_days(db_session, 5)
    narrow = await get_request_log_retention(db_session)
    assert narrow["stored_rows"] == 2
    assert narrow["expired_rows"] == 2


async def test_a_purge_larger_than_one_batch_completes(db_session, user):
    """One statement over a table this size holds locks for minutes."""

    for _ in range(3):
        await _log(db_session, age_days=400, user_id=user.id)
    await db_session.commit()

    result = await purge_expired_request_logs(db_session, retention_days=30)

    assert result["rows_deleted"] == 3
    assert (await db_session.execute(select(RequestLog))).scalars().all() == []


def test_the_batch_size_is_bounded():
    assert 100 <= PURGE_BATCH_SIZE <= 50_000


def test_the_scheduler_runs_it():
    from app.services import scheduler

    assert "job_request_log_retention" in scheduler.start_scheduler.__code__.co_names


def test_the_index_the_purge_needs_is_declared():
    """A first purge against an unindexed table of this size is an outage."""

    names = {index.name for index in RequestLog.__table__.indexes}
    assert "ix_request_logs_user_time" in names
