"""Singleton outbox relay and stale Knowledge job recovery process."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.services.knowledge_connector_service import schedule_due_connectors
from app.services.knowledge_job_service import recover_stale_knowledge_jobs
from app.services.knowledge_queue import create_knowledge_redis
from app.services.knowledge_retention_service import (
    schedule_expired_knowledge_retention,
)
from app.services.outbox_service import relay_outbox_once

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_args: loop.call_soon_threadsafe(stop.set))


async def run() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    redis = create_knowledge_redis()
    scheduler_id = (
        f"scheduler-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    next_reaper_at = 0.0
    next_connector_poll_at = 0.0
    next_retention_poll_at = 0.0
    logger.info("Starting Knowledge scheduler %s", scheduler_id)
    try:
        while not stop.is_set():
            try:
                stats = await relay_outbox_once(
                    AsyncSessionLocal,
                    redis,
                    worker_id=scheduler_id,
                )
                if stats.claimed:
                    logger.info(
                        "Outbox claimed=%s published=%s retried=%s dead=%s",
                        stats.claimed,
                        stats.published,
                        stats.retried,
                        stats.dead,
                    )
                now = asyncio.get_running_loop().time()
                if now >= next_reaper_at:
                    async with AsyncSessionLocal() as db:
                        recovered = await recover_stale_knowledge_jobs(db)
                        await db.commit()
                    if recovered:
                        logger.warning(
                            "Recovered %s expired Knowledge job leases", recovered
                        )
                    next_reaper_at = now + settings.knowledge_reaper_interval_seconds
                if now >= next_connector_poll_at:
                    async with AsyncSessionLocal() as db:
                        scheduled = await schedule_due_connectors(db)
                        await db.commit()
                    if scheduled:
                        logger.info(
                            "Scheduled %s due Knowledge connector syncs",
                            scheduled,
                        )
                    next_connector_poll_at = (
                        now + settings.knowledge_connector_poll_interval_seconds
                    )
                if now >= next_retention_poll_at:
                    async with AsyncSessionLocal() as db:
                        retention = await schedule_expired_knowledge_retention(
                            db,
                            limit=settings.knowledge_retention_batch_size,
                        )
                        await db.commit()
                    if retention["scheduled_versions"]:
                        logger.info(
                            "Scheduled %s Knowledge retention purges; held=%s",
                            retention["scheduled_versions"],
                            retention["held_resources"],
                        )
                    next_retention_poll_at = (
                        now
                        + max(
                            60,
                            int(settings.knowledge_retention_poll_interval_seconds),
                        )
                    )
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=settings.outbox_poll_interval_seconds,
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Knowledge scheduler loop failed")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1.0)
                except TimeoutError:
                    pass
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
