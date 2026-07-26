"""Short-lived pending tokens for post-password 2FA challenge."""

from __future__ import annotations

import asyncio
import json
import secrets
import time

import redis.asyncio as redis_async

from app.config import effective_redis_url
from app.services.observability import increment

_TTL_SECONDS = 300
_KEY_PREFIX = "auth:2fa:"

_mem_lock = asyncio.Lock()
_mem_store: dict[str, tuple[str, float]] = {}


def _client() -> redis_async.Redis:
    return redis_async.from_url(effective_redis_url(), decode_responses=True)


def generate_pending_token() -> str:
    return secrets.token_urlsafe(32)


async def store_pending(token: str, payload: dict) -> None:
    raw = json.dumps(payload)
    client = _client()
    try:
        await client.set(_KEY_PREFIX + token, raw, ex=_TTL_SECONDS)
        return
    except Exception:
        increment("redis_fallback")
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
    expires = time.monotonic() + _TTL_SECONDS
    async with _mem_lock:
        _mem_store[token] = (raw, expires)


async def consume_pending(token: str) -> dict | None:
    if not token:
        return None
    client = _client()
    raw = None
    try:
        pipe = client.pipeline()
        pipe.get(_KEY_PREFIX + token)
        pipe.delete(_KEY_PREFIX + token)
        raw, _deleted = await pipe.execute()
    except Exception:
        increment("redis_fallback")
        raw = None
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
    if not raw:
        async with _mem_lock:
            now = time.monotonic()
            entry = _mem_store.pop(token, None)
            if entry:
                body, exp = entry
                if exp > now:
                    raw = body
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None
