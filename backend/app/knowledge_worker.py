"""Long-running Knowledge job consumer process."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid

from app.database import AsyncSessionLocal, engine
from app.services.knowledge_job_handlers import KnowledgeJobContext
from app.services.knowledge_queue import create_knowledge_redis
from app.services.knowledge_worker_service import KnowledgeWorker
from app.services.qdrant_service import QdrantVectorService

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
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    redis = create_knowledge_redis()
    qdrant = QdrantVectorService()
    consumer_name = (
        f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    worker = KnowledgeWorker(
        session_factory=AsyncSessionLocal,
        redis=redis,
        consumer_name=consumer_name,
        context=KnowledgeJobContext(qdrant=qdrant),
    )
    logger.info("Starting Knowledge worker %s", consumer_name)
    try:
        await worker.run_forever(stop)
    finally:
        await redis.aclose()
        await qdrant.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
