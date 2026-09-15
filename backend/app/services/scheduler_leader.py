"""Single-instance election for the in-process APScheduler.

Compose runs uvicorn with several workers and every worker used to call
``start_scheduler()`` in its lifespan, so each cron job ran N times: N metric
snapshots per hour, N model syncs, N budget resets racing on the same rows.

Leadership is a PostgreSQL advisory lock held inside an open transaction on a
dedicated connection. Holding it *transactionally* (``pg_try_advisory_xact_lock``
in a transaction that is never committed) rather than at session level is what
makes it work behind PgBouncer in transaction-pooling mode: an open transaction
pins the client to one server connection, so the lock really belongs to this
process for as long as the transaction lives. The cost is one pinned connection
per leader, which is one per deployment.

Non-leaders keep retrying every ``RETRY_SECONDS``; the leader heartbeats on the
same connection and steps down (stopping its scheduler) the moment the
heartbeat fails, so a killed leader is replaced within about one retry period.

SQLite (tests, single-process dev) has no advisory locks: the first caller is
always the leader.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

logger = logging.getLogger(__name__)

# Sibling of the DDL (56023113) and admin-bootstrap (56023114) locks in main.py.
LEADER_LOCK_ID = 56023115
RETRY_SECONDS = 30.0
HEARTBEAT_SECONDS = 15.0


class SchedulerLeader:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        on_acquire: Callable[[], Awaitable[None] | None],
        on_release: Callable[[], Awaitable[None] | None],
        retry_seconds: float = RETRY_SECONDS,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> None:
        self._engine = engine
        self._on_acquire = on_acquire
        self._on_release = on_release
        self._retry = retry_seconds
        self._heartbeat = heartbeat_seconds
        self._conn: AsyncConnection | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self.is_leader = False

    # -- lock primitives -----------------------------------------------------

    async def try_acquire(self) -> bool:
        """Take the lock if free. Returns True when this process is now leader."""
        if self.is_leader:
            return True
        if self._engine.dialect.name != "postgresql":
            self.is_leader = True
            return True
        conn = await self._engine.connect()
        try:
            await conn.begin()
            got = (
                await conn.execute(
                    text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                    {"lock_id": LEADER_LOCK_ID},
                )
            ).scalar()
        except Exception:
            await conn.close()
            raise
        if not got:
            await conn.rollback()
            await conn.close()
            return False
        self._conn = conn
        self.is_leader = True
        return True

    async def heartbeat_ok(self) -> bool:
        """True while the pinned transaction (and therefore the lock) is alive."""
        if self._conn is None:
            return self.is_leader and self._engine.dialect.name != "postgresql"
        try:
            await self._conn.execute(text("SELECT 1"))
            return True
        except Exception:
            logger.warning("Scheduler leader heartbeat failed; stepping down", exc_info=True)
            return False

    async def release(self) -> None:
        """Give the lock back (transaction rollback) and forget leadership."""
        was_leader = self.is_leader
        self.is_leader = False
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.rollback()
            except Exception:
                logger.debug("rollback on leader release failed", exc_info=True)
            try:
                await conn.close()
            except Exception:
                logger.debug("close on leader release failed", exc_info=True)
        if was_leader:
            await _maybe_await(self._on_release())

    # -- background loop ------------------------------------------------------

    def start(self) -> None:
        if self._task is None:
            self._stopping = False
            self._task = asyncio.create_task(self._run(), name="scheduler-leader")

    async def stop(self) -> None:
        self._stopping = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.release()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                if not self.is_leader:
                    if await self.try_acquire():
                        logger.info("This worker is now the scheduler leader")
                        await _maybe_await(self._on_acquire())
                    else:
                        await asyncio.sleep(self._retry)
                        continue
                await asyncio.sleep(self._heartbeat)
                if not await self.heartbeat_ok():
                    await self.release()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler leader loop error; retrying")
                await self.release()
                await asyncio.sleep(self._retry)


async def _maybe_await(result: Awaitable[None] | None) -> None:
    if result is not None:
        await result


_leader: SchedulerLeader | None = None


def get_leader() -> SchedulerLeader | None:
    return _leader


def is_leader() -> bool:
    return bool(_leader and _leader.is_leader)


def install_leader(leader: SchedulerLeader) -> None:
    global _leader
    _leader = leader
