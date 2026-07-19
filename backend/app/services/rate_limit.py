"""Rate limiting shared across uvicorn workers via Redis, with an in-memory
fallback so the application keeps working (fail-open) if Redis is unavailable.

Previously this was a per-worker in-memory counter, which meant the effective
limit was multiplied by the worker count and reset on every restart. The
Redis-backed implementation uses a sliding-window counter per key, shared by
all workers, so the configured limit is the true limit.

It is used for chat list/search endpoints and, since Phase 7, for the login
endpoint (per-username + per-IP brute-force protection).
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException

from app.config import effective_redis_url
from app.services.observability import increment

_lock = Lock()
_buckets: dict[str, list[float]] = defaultdict(list)

_LOGIN_USER_LIMIT = 20  # per username per minute
_LOGIN_IP_LIMIT = 60  # per source IP per minute


def _client():
    try:
        import redis.asyncio as redis_async

        return redis_async.from_url(effective_redis_url(), decode_responses=True)
    except Exception:
        return None


async def check_rate_limit(key: str, *, limit: int, window_seconds: int = 60) -> None:
    """Raise HTTP 429 when the user exceeds ``limit`` events per window.

    Tries Redis first (shared across workers). If Redis is unavailable, falls
    back to the per-process in-memory counter (fail-open: rate limiting is
    approximate but the request is never blocked by an outage).
    """
    now = time.monotonic()
    cutoff = now - window_seconds
    client = _client()
    if client is not None:
        try:
            # Sliding window via sorted-set-free list: INCR a per-window counter.
            # Simpler & adequate: a single counter that we trim by timestamp
            # using ZSET. Use ZADD/ZREMRANGEBYSCORE/ZCARD for a true sliding window.
            member = f"{now}:{id(key)}:{now:.6f}"
            pipe = client.pipeline()
            pipe.zadd(key, {member: now})
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            pipe.expire(key, window_seconds + 5)
            _, _, count, _ = await pipe.execute()
            await client.aclose()
            if int(count) > limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")
            return
        except HTTPException:
            raise
        except Exception:
            # Redis hiccup: fall through to in-memory fallback (fail-open).
            increment("redis_fallback")
            pass
    # In-memory fallback (per-worker).
    with _lock:
        hits = _buckets[key]
        _buckets[key] = [t for t in hits if t > cutoff]
        if len(_buckets[key]) >= limit:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")
        _buckets[key].append(now)


def prune_stale_buckets(max_age_seconds: int = 3600) -> None:
    """Drop idle bucket keys (optional housekeeping for the in-memory fallback)."""
    now = time.monotonic()
    cutoff = now - max_age_seconds
    with _lock:
        stale = [k for k, hits in _buckets.items() if not hits or hits[-1] < cutoff]
        for k in stale:
            del _buckets[k]


async def check_login_rate_limit(username: str, source_ip: str | None) -> None:
    """Brute-force protection on the login endpoint.

    Two independent windows: per-username (stops targeted guessing on one
    account) and per-source-IP (stops distributed guessing across many
    accounts from one host). Both must pass. Fails open if Redis is down.
    """
    await check_rate_limit(f"login:user:{username}", limit=_LOGIN_USER_LIMIT)
    if source_ip:
        await check_rate_limit(f"login:ip:{source_ip}", limit=_LOGIN_IP_LIMIT)
