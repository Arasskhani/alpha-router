"""Outstanding SAML AuthnRequests and seen assertion ids (Redis, fail-closed).

Two small sets keep the SP honest about which Responses it accepts:

* ``saml:req:<id>`` — an AuthnRequest this SP issued and has not yet seen a
  Response for. Written by ``/saml/login``, consumed exactly once by the ACS.
  A Response whose ``InResponseTo`` is missing or not in this set is refused,
  which closes both IdP-initiated logins and replay of a captured Response.
* ``saml:asn:<id>`` — assertion ids already accepted, kept until the
  assertion's own ``NotOnOrAfter``. Defense in depth behind the first set.

Redis is shared by all uvicorn workers, so the login and the ACS may land on
different workers. There is deliberately no in-memory fallback: with Redis
down a per-worker dict would either let replays through (assertion set) or
reject legitimate logins at random (request set). Callers get
``SamlStateUnavailable`` and answer 503.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import redis.asyncio as redis_async

from app.config import get_settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_REQ_PREFIX = "saml:req:"
_ASN_PREFIX = "saml:asn:"
_MIN_ASSERTION_TTL_SECONDS = 60
_MAX_ASSERTION_TTL_SECONDS = 24 * 3600


class SamlStateUnavailable(RuntimeError):
    """Redis could not be reached; SAML login cannot be validated safely."""


ClientFactory = Callable[[], Any]


def _default_client() -> redis_async.Redis:
    """Shared per-process client (never closed here)."""
    return get_redis()


_client_factory: ClientFactory = _default_client


def set_client_factory(factory: ClientFactory | None) -> None:
    """Test seam: swap the Redis client factory (None restores the default)."""
    global _client_factory
    _client_factory = factory or _default_client


async def _with_client(op):
    client = _client_factory()
    try:
        return await op(client)
    except SamlStateUnavailable:
        raise
    except Exception as exc:
        logger.error("SAML state store unavailable: %s", type(exc).__name__)
        raise SamlStateUnavailable(str(exc)) from exc


async def remember_authn_request(request_id: str) -> None:
    ttl = max(30, int(getattr(get_settings(), "saml_request_ttl_seconds", 600) or 600))

    async def op(client):
        await client.set(_REQ_PREFIX + request_id, "1", ex=ttl)

    await _with_client(op)


async def consume_authn_request(request_id: str | None) -> bool:
    """Atomically remove the outstanding request. False if it was not there."""
    if not request_id:
        return False

    async def op(client):
        # DEL returns the number of keys removed: 1 means we owned the request.
        return int(await client.delete(_REQ_PREFIX + request_id) or 0) == 1

    return await _with_client(op)


async def register_assertion(assertion_id: str, not_on_or_after: float | None) -> bool:
    """Record the assertion id. False when it was seen before (replay)."""
    if not assertion_id:
        return False
    now = time.time()
    ttl = int(float(not_on_or_after) - now) if not_on_or_after else _MIN_ASSERTION_TTL_SECONDS * 5
    ttl = max(_MIN_ASSERTION_TTL_SECONDS, min(_MAX_ASSERTION_TTL_SECONDS, ttl))

    async def op(client):
        return bool(await client.set(_ASN_PREFIX + assertion_id, "1", ex=ttl, nx=True))

    return await _with_client(op)
