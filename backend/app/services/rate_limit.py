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

import secrets
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
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
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
        except Exception as exc:  # noqa: BLE001 -- any Redis failure degrades to the in-memory limiter
            increment("redis_fallback")
            if fail_closed:
                raise HTTPException(status_code=503, detail=_REDIS_UNAVAILABLE_LOGIN) from exc
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


async def failure_limit_reached(key: str, *, limit: int, window_seconds: int = 60) -> bool:
    """Whether ``key`` already has ``limit`` failures in the window.

    Counts nothing itself. A caller asks before doing the work and records only
    what failed (:func:`record_failure`), so however many requests succeed
    behind one address - an office's NAT at nine in the morning - none of them
    fills the window. Fail-open, like the chat limiters.
    """
    client = _client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(key, 0, time.time() - window_seconds)
            pipe.zcard(key)
            _, count = await pipe.execute()
            return int(count) >= limit
        except Exception:  # noqa: BLE001 -- any Redis failure degrades to the in-memory limiter
            increment("redis_fallback")
    cutoff = time.monotonic() - window_seconds
    with _lock:
        hits = [t for t in _buckets.get(key, []) if t > cutoff]
        _buckets[key] = hits
        return len(hits) >= limit


async def record_failure(key: str, *, window_seconds: int = 60) -> None:
    """Count one failure against ``key`` for :func:`failure_limit_reached`.

    In Redis it is scored with the wall clock, which every worker and host
    shares; the per-process fallback uses the monotonic clock, as the rest of
    this module does.
    """
    client = _client()
    if client is not None:
        try:
            now = time.time()
            pipe = client.pipeline()
            pipe.zadd(key, {f"{now:.6f}:{secrets.token_hex(4)}": now})
            pipe.expire(key, window_seconds + 5)
            await pipe.execute()
            return
        except Exception:  # noqa: BLE001 -- any Redis failure degrades to the in-memory limiter
            increment("redis_fallback")
    with _lock:
        _buckets[key].append(time.monotonic())


def prune_stale_buckets(max_age_seconds: int = 3600) -> None:
    """Drop idle bucket keys (optional housekeeping for the in-memory fallback)."""
    now = time.monotonic()
    cutoff = now - max_age_seconds
    with _lock:
        stale = [k for k, hits in _buckets.items() if not hits or hits[-1] < cutoff]
        for k in stale:
            del _buckets[k]


def generation_subject(*, user_id: int | None, api_key_id: int | None) -> str:
    """Who to count a paid call against: the API key if there is one, else the user."""

    if api_key_id:
        return f"key:{int(api_key_id)}"
    return f"user:{int(user_id)}" if user_id else "anonymous"


async def check_generation_rate_limit(kind: str, subject: str, limit: int) -> None:
    """Bound the endpoints that spend money per call.

    The limiter was wired to login and to the chat list and search - the cheap
    reads - and to none of the expensive paths: chat completions, the OpenAI
    compatible gateway, image generation and speech. A leaked API key or a
    runaway client was bounded only by the monthly budget, which is discovered
    after the money is gone.

    Fail-open, unlike login: a Redis outage must not stop people working. The
    budget reservation is still the hard ceiling underneath.
    """

    await check_rate_limit(f"generation:{kind}:{subject}", limit=max(1, int(limit)))


async def check_login_rate_limit(username: str, source_ip: str | None) -> None:
    """Brute-force protection on the login endpoint.

    Two windows, both of which must pass: one per (username, source IP) pair
    and one per source IP.

    The per-username window used to be global to the account, and that made it
    a denial-of-service primitive rather than a protection. The limit is checked
    before the user is even looked up and nothing resets it on success, so
    anyone who knows an administrator's username - ``alpharouter`` by default -
    could send 21 junk attempts a minute and lock the real administrator out
    indefinitely. One IP, well under the per-IP ceiling, so the attacker never
    limited themselves. That is exactly the lockout DoS this design avoids
    lockouts to prevent.

    Scoping it per pair keeps what it was for: guessing one account from one
    host still stops at 20 a minute, and an attacker who spreads the attempts
    across hosts now pays the per-IP window on each of them. Distributed slow
    guessing against a single account is the case this does not catch on its
    own; login events reaching the audit trail are what make that visible.

    Fail-closed if Redis is down so limits cannot weaken across workers.
    """
    scope = source_ip or "unknown"
    await check_rate_limit(
        f"login:user:{username}:{scope}",
        limit=_LOGIN_USER_LIMIT,
        fail_closed=True,
    )
    if source_ip:
        await check_rate_limit(
            f"login:ip:{source_ip}",
            limit=_LOGIN_IP_LIMIT,
            fail_closed=True,
        )
