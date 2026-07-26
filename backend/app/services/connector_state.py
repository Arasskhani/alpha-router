"""Single-use OAuth state nonces for connector flows.

Mirrors :mod:`app.services.twofa_pending`: Redis when available, in-memory
fallback otherwise. The nonce is embedded in the OAuth ``state`` JWT and also
stored here so a callback can only be used once and cannot be replayed.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time

import redis.asyncio as redis_async

from app.config import effective_redis_url
from app.services.observability import increment

_TTL_SECONDS = 600
_KEY_PREFIX = "connector:state:"

_mem_lock = asyncio.Lock()
_mem_store: dict[str, tuple[str, float]] = {}


def _client() -> redis_async.Redis:
    return redis_async.from_url(effective_redis_url(), decode_responses=True)


def new_state_nonce() -> str:
    return secrets.token_urlsafe(24)


async def store_state(nonce: str, payload: dict) -> None:
    raw = json.dumps(payload)
    client = _client()
    try:
        await client.set(_KEY_PREFIX + nonce, raw, ex=_TTL_SECONDS)
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
        _mem_store[nonce] = (raw, expires)


async def consume_state(nonce: str) -> dict | None:
    if not nonce:
        return None
    client = _client()
    raw = None
    try:
        pipe = client.pipeline()
        pipe.get(_KEY_PREFIX + nonce)
        pipe.delete(_KEY_PREFIX + nonce)
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
            entry = _mem_store.pop(nonce, None)
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
