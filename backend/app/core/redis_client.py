"""One Redis client (and connection pool) per worker process.

Six services used to call ``redis.asyncio.from_url`` for every operation and
``aclose()`` it right after: a new pool, a new TCP connection and a new AUTH
round-trip per rate-limit check, per presence ping, per one-time code. Under
load that is a connect storm against Redis and a measurable latency tax on
every request.

``get_redis()`` returns a lazily created client bound to the *running event
loop*; the pool is reused for the life of the process and closed once from
the lifespan. The client is looked up per loop so test suites that spin up a
fresh loop per test never reuse connections that belong to a dead loop.

Callers must not ``aclose()`` what they get from here. The knowledge worker
keeps its own dedicated client (``knowledge_queue.create_knowledge_redis``):
blocking XREADGROUP calls should not share a pool with request handlers.
"""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as redis_async

from app.config import effective_redis_url

logger = logging.getLogger(__name__)

_clients: dict[int, tuple[asyncio.AbstractEventLoop, str, redis_async.Redis]] = {}


def _build(url: str) -> redis_async.Redis:
    return redis_async.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
        health_check_interval=30,
        retry_on_timeout=False,
    )


def get_redis() -> redis_async.Redis:
    """Shared client for the current event loop. Never close it yourself."""
    loop = asyncio.get_running_loop()
    url = effective_redis_url()
    entry = _clients.get(id(loop))
    if entry is not None and entry[0] is loop and entry[1] == url:
        return entry[2]
    client = _build(url)
    _clients[id(loop)] = (loop, url, client)
    return client


async def close_redis() -> None:
    """Close the client owned by the current loop (call from the lifespan)."""
    loop = asyncio.get_running_loop()
    entry = _clients.pop(id(loop), None)
    if entry is None:
        return
    try:
        await entry[2].aclose()
    except Exception:
        logger.debug("closing shared redis client failed", exc_info=True)


def reset_for_tests() -> None:
    """Forget every cached client without awaiting (test isolation only)."""
    _clients.clear()
