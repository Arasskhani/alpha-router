"""One-time exchange-code store backed by Redis for OIDC token delivery.

After the Keycloak callback validates the IdP response, we mint a Alpha Router JWT but
must NOT put it in the redirect URL (it would leak via history/Referer/logs).
Instead we store the JWT under a random opaque code in Redis with a short TTL,
redirect the browser to ``/login?code=<opaque>``, and the frontend exchanges
the code for the JWT via ``POST /api/auth/keycloak/exchange``.

Codes are single-use (deleted on read). TTL is short so a leaked code is
useless within seconds.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time

import redis.asyncio as redis_async

from app.config import effective_redis_url

_CODE_TTL_SECONDS = 30
_KEY_PREFIX = "oidc:xchg:"

# In-memory fallback so a Redis outage does not break Keycloak login. The
# callback and the code-exchange may be served by different workers, so this is
# a best-effort degradation (single-worker or sticky-session deployments get a
# full round-trip). Entries expire on read to keep the single-use contract.
_mem_lock = asyncio.Lock()
_mem_store: dict[str, tuple[str, float]] = {}


def _client() -> redis_async.Redis:
    return redis_async.from_url(effective_redis_url(), decode_responses=True)


def _prune_expired(now: float) -> None:
    expired = [k for k, (_, exp) in _mem_store.items() if exp <= now]
    for k in expired:
        _mem_store.pop(k, None)


def generate_code() -> str:
    return secrets.token_urlsafe(32)


async def store_token(code: str, payload: dict) -> None:
    """Store a token payload under ``code`` with a short TTL.

    Falls back to an in-process store when Redis is unreachable so the OIDC
    callback can still complete the redirect instead of returning a 500.
    """
    raw = json.dumps(payload)
    client = _client()
    try:
        await client.set(_KEY_PREFIX + code, raw, ex=_CODE_TTL_SECONDS)
        return
    except Exception:
        # Redis unavailable: degrade to in-memory (best-effort, per-worker).
        pass
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
    expires = time.monotonic() + _CODE_TTL_SECONDS
    async with _mem_lock:
        _prune_expired(time.monotonic())
        _mem_store[code] = (raw, expires)


async def consume_code(code: str) -> dict | None:
    """Atomically retrieve and delete the payload for ``code`` (single-use)."""
    if not code:
        return None
    client = _client()
    try:
        pipe = client.pipeline()
        pipe.get(_KEY_PREFIX + code)
        pipe.delete(_KEY_PREFIX + code)
        raw, _deleted = await pipe.execute()
    except Exception:
        raw = None
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
    if not raw:
        # Fall back to the in-memory store used when Redis was unavailable.
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
