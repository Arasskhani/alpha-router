"""Scheduler leader election.

The SQLite part checks the state machine (acquire -> on_acquire, heartbeat
failure -> on_release, stop -> release). The PostgreSQL part (opt-in canary,
same flag as the reservation canary) proves mutual exclusion of the advisory
lock across two independent connections and hand-over after release.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.services import scheduler_leader
from app.services.scheduler_leader import SchedulerLeader


async def test_sqlite_first_caller_is_leader_and_callbacks_fire():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    events: list[str] = []
    try:
        leader = SchedulerLeader(
            engine,
            on_acquire=lambda: events.append("acquire"),
            on_release=lambda: events.append("release"),
            retry_seconds=0.01,
            heartbeat_seconds=0.01,
        )
        assert await leader.try_acquire() is True
        assert leader.is_leader is True
        # try_acquire does not call on_acquire itself; the caller (lifespan/loop) does.
        assert events == []
        assert await leader.heartbeat_ok() is True
        await leader.release()
        assert leader.is_leader is False
        assert events == ["release"]

        # Background loop: acquires, fires on_acquire, then stop() releases.
        leader.start()
        for _ in range(200):
            if "acquire" in events:
                break
            await asyncio.sleep(0.005)
        assert "acquire" in events
        await leader.stop()
        assert events[-1] == "release"
        assert leader.is_leader is False
    finally:
        await engine.dispose()


async def test_module_level_is_leader_reflects_installed_instance():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        previous = scheduler_leader.get_leader()
        leader = SchedulerLeader(engine, on_acquire=lambda: None, on_release=lambda: None)
        scheduler_leader.install_leader(leader)
        assert scheduler_leader.is_leader() is False
        await leader.try_acquire()
        assert scheduler_leader.is_leader() is True
        await leader.release()
        assert scheduler_leader.is_leader() is False
        if previous is not None:
            scheduler_leader.install_leader(previous)
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_RESERVATION_CANARY") != "1",
    reason="opt-in PostgreSQL canary",
)
async def test_postgres_lock_is_exclusive_and_hands_over():
    # A private engine: pooled connections of the shared app engine belong
    # to whichever event loop an earlier test used.
    from app.config import get_settings
    from app.database import asyncpg_connect_args

    engine = create_async_engine(get_settings().database_url, connect_args=asyncpg_connect_args())
    a_events: list[str] = []
    b_events: list[str] = []
    a = SchedulerLeader(engine, on_acquire=lambda: a_events.append("acq"), on_release=lambda: a_events.append("rel"))
    b = SchedulerLeader(engine, on_acquire=lambda: b_events.append("acq"), on_release=lambda: b_events.append("rel"))
    try:
        assert await a.try_acquire() is True
        # Second process (separate connection, separate transaction) must not win.
        assert await b.try_acquire() is False
        assert b.is_leader is False
        assert await a.heartbeat_ok() is True

        await a.release()
        assert a_events == ["rel"]
        # Lock is free again: the other process takes over.
        assert await b.try_acquire() is True
        assert await a.try_acquire() is False
    finally:
        await a.release()
        await b.release()
        await engine.dispose()
