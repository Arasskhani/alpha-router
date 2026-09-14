"""Rate limiting shared across uvicorn workers via Redis, with an in-memory
fallback for non-auth endpoints so the application keeps working (fail-open)
if Redis is unavailable.

Login brute-force protection is fail-closed: if Redis cannot be reached, login
is rejected with HTTP 503 so an outage cannot weaken per-worker limits.

Previously this was a per-worker in-memory counter, which meant the effective
limit was multiplied by the worker count and reset on every restart. The
Redis-backed implementation uses a sliding-window counter per key, shared by
all workers, so the configured limit is the true limit.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException

from app.core.redis_client import get_redis
from app.services.observability import increment

_lock = Lock()
_buckets: dict[str, list[float]] = defaultdict(list)

_LOGIN_USER_LIMIT = 20  # per username per minute
_LOGIN_IP_LIMIT = 60  # per source IP per minute

_REDIS_UNAVAILABLE_LOGIN = "Login temporarily unavailable. Try again shortly."
_RATE_LIMIT_EXCEEDED = "Rate limit exceeded. Try again shortly."


def _client():
    """Shared per-process client (never closed here)."""
    try:
        return get_redis()
    except Exception:
        return None


async def check_rate_limit(
    key: str,
    *,
    limit: int,
    window_seconds: int = 60,
    fail_closed: bool = False,
) -> None:
    """Raise HTTP 429 when the user exceeds ``limit`` events per window.

    Tries Redis first (shared across workers). If Redis is unavailable:
    - ``fail_closed=False`` (default, chat endpoints): fall back to the
      per-process in-memory counter so the request is not blocked by an outage.
    - ``fail_closed=True`` (login): raise HTTP 503 so brute-force limits cannot
      weaken across workers during a Redis outage.
    """
    now = time.monotonic()
    cutoff = now - window_seconds
    client = _client()
    if client is not None:
        try:
            # Sliding window via sorted-set: ZADD/ZREMRANGEBYSCORE/ZCARD.
            member = f"{now}:{id(key)}:{now:.6f}"
            pipe = client.pipeline()
            pipe.zadd(key, {member: now})
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            pipe.expire(key, window_seconds + 5)
            _, _, count, _ = await pipe.execute()
            if int(count) > limit:
                raise HTTPException(status_code=429, detail=_RATE_LIMIT_EXCEEDED)
            return
        except HTTPException:
            raise
        except Exception:
            increment("redis_fallback")
            if fail_closed:
                raise HTTPException(status_code=503, detail=_REDIS_UNAVAILABLE_LOGIN)
            # Redis hiccup: fall through to in-memory fallback (fail-open).
    elif fail_closed:
        increment("redis_fallback")
        raise HTTPException(status_code=503, detail=_REDIS_UNAVAILABLE_LOGIN)

    # In-memory fallback (per-worker) — only for fail-open callers.
    with _lock:
        hits = _buckets[key]
        _buckets[key] = [t for t in hits if t > cutoff]
        if len(_buckets[key]) >= limit:
            raise HTTPException(status_code=429, detail=_RATE_LIMIT_EXCEEDED)
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
    accounts from one host). Both must pass.

    Fail-closed if Redis is down so limits cannot weaken across workers.
    """
    await check_rate_limit(
        f"login:user:{username}",
        limit=_LOGIN_USER_LIMIT,
        fail_closed=True,
    )
    if source_ip:
        await check_rate_limit(
            f"login:ip:{source_ip}",
            limit=_LOGIN_IP_LIMIT,
            fail_closed=True,
        )
