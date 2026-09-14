"""One-time exchange-code store for SSO token delivery (SAML / OIDC).

After the IdP callback validates the response, we mint an Alpharouter JWT but must NOT
put it in the redirect URL. Instead we store the JWT under a random opaque code
in Redis with a short TTL, redirect to ``/login?code=<opaque>``, and the
frontend exchanges the code via ``POST /api/auth/sso/exchange``.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time

import redis.asyncio as redis_async

from app.core.redis_client import get_redis
from app.services.observability import increment

_CODE_TTL_SECONDS = 30
_KEY_PREFIX = "auth:xchg:"

_mem_lock = asyncio.Lock()
_mem_store: dict[str, tuple[str, float]] = {}


def _client() -> redis_async.Redis:
    """Shared per-process client (never closed here)."""
    return get_redis()


def _prune_expired(now: float) -> None:
    expired = [k for k, (_, exp) in _mem_store.items() if exp <= now]
    for k in expired:
        _mem_store.pop(k, None)


def generate_code() -> str:
    return secrets.token_urlsafe(32)


async def store_token(code: str, payload: dict) -> None:
    raw = json.dumps(payload)
    client = _client()
    try:
        await client.set(_KEY_PREFIX + code, raw, ex=_CODE_TTL_SECONDS)
        return
    except Exception:
        increment("redis_fallback")
    expires = time.monotonic() + _CODE_TTL_SECONDS
    async with _mem_lock:
        _prune_expired(time.monotonic())
        _mem_store[code] = (raw, expires)


async def consume_code(code: str) -> dict | None:
    if not code:
        return None
    client = _client()
    try:
        pipe = client.pipeline()
        pipe.get(_KEY_PREFIX + code)
        pipe.delete(_KEY_PREFIX + code)
        raw, _deleted = await pipe.execute()
    except Exception:
        increment("redis_fallback")
        raw = None
    if not raw:
        async with _mem_lock:
            now = time.monotonic()
            _prune_expired(now)
            entry = _mem_store.pop(code, None)
        if entry is None:
            return None
        raw, expires = entry
        if expires <= time.monotonic():
            return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
