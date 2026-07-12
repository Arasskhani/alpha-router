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

import json
import secrets

import redis.asyncio as redis_async

from app.config import get_settings

_CODE_TTL_SECONDS = 30
_KEY_PREFIX = "oidc:xchg:"


def _client() -> redis_async.Redis:
    return redis_async.from_url(get_settings().redis_url, decode_responses=True)


def generate_code() -> str:
    return secrets.token_urlsafe(32)


async def store_token(code: str, payload: dict) -> None:
    """Store a token payload under ``code`` with a short TTL."""
    client = _client()
    try:
        await client.set(_KEY_PREFIX + code, json.dumps(payload), ex=_CODE_TTL_SECONDS)
    finally:
        await client.aclose()


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
        if not raw:
            return None
        return json.loads(raw)
    finally:
        await client.aclose()
