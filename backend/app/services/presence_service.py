"""Online presence for the admin Users table, stored only in Redis.

Presence is deliberately ephemeral: one short-lived key per user, refreshed by
the browser while a tab is visible. Nothing is written to PostgreSQL, so there
is no migration, no retention policy, and no cleanup job — an expired key *is*
the offline state.

Two rules keep this safe in production:

- Reads use a single ``MGET`` for the ids on screen. The keyspace is never
  scanned (``KEYS``/``SCAN`` on a shared Redis is a latency hazard).
- Everything fails open. When Redis is unreachable or the feature is disabled,
  presence is reported as *unknown* (``None``) rather than "offline", so callers
  can say so instead of showing every user as logged out.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.redis_client import get_redis
from app.config import get_settings
from app.services.observability import increment

_KEY_PREFIX = "presence:user:"

# Upper bound for one MGET so a crafted or oversized request cannot turn into an
# unbounded Redis command.
MAX_PRESENCE_LOOKUP = 2000

_MIN_TTL_SECONDS = 30


def _client():
    """Shared per-process client (never closed here)."""
    try:
        return get_redis()
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return None)
        return None


def presence_key(user_id: int) -> str:
    return f"{_KEY_PREFIX}{int(user_id)}"


def presence_enabled() -> bool:
    return bool(get_settings().presence_enabled)


def presence_ttl_seconds() -> int:
    """TTL for one presence key, floored so a tab cannot expire between pings."""
    return max(_MIN_TTL_SECONDS, int(get_settings().presence_ttl_seconds or 90))


async def mark_online(user_id: int) -> bool:
    """Refresh one user's presence key. Returns False when presence is off."""
    if not presence_enabled():
        return False
    client = _client()
    if client is None:
        increment("redis_fallback")
        return False
    try:
        await client.set(presence_key(user_id), "1", ex=presence_ttl_seconds())
        return True
    except Exception:  # noqa: BLE001 -- any Redis failure degrades to the in-memory path
        increment("redis_fallback")
        return False


async def clear_presence(user_id: int) -> None:
    """Drop the presence key so an explicit logout shows offline immediately."""
    if not presence_enabled():
        return
    client = _client()
    if client is None:
        return
    try:
        await client.delete(presence_key(user_id))
    except Exception:  # noqa: BLE001 -- any Redis failure degrades to the in-memory path
        increment("redis_fallback")


async def online_user_ids(user_ids: Sequence[int]) -> set[int] | None:
    """Return the subset of ``user_ids`` that is currently online.

    ``None`` means presence is unavailable (disabled or Redis down); callers
    should surface "unknown" instead of marking everyone offline.
    """
    if not presence_enabled():
        return None
    ids: list[int] = []
    seen: set[int] = set()
    for raw in user_ids:
        if raw is None:
            continue
        uid = int(raw)
        if uid not in seen:
            seen.add(uid)
            ids.append(uid)
        if len(ids) >= MAX_PRESENCE_LOOKUP:
            break
    if not ids:
        return set()
    client = _client()
    if client is None:
        increment("redis_fallback")
        return None
    try:
        values = await client.mget([presence_key(uid) for uid in ids])
    except Exception:  # noqa: BLE001 -- any Redis failure degrades to the in-memory path
        increment("redis_fallback")
        return None
    return {uid for uid, value in zip(ids, values, strict=False) if value}
