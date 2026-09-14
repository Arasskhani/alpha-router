"""Redis-backed leased semaphore for Code Interpreter turn admission.

Enforces a global concurrent-turn ceiling and a per-subject fairness cap across
Uvicorn workers. Admission is atomic (Lua), fail-closed on Redis outage, and
rejects immediately with HTTP 429 — no queue. Integrate from preflight before
budget reservation / provider calls::

    permit = await acquire_code_interpreter_turn(subject_for_user(user_id))
    try:
        ...
        alive = await heartbeat_code_interpreter_turn(permit)
    finally:
        await release_code_interpreter_turn(permit)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.core.redis_client import get_redis
from app.config import get_settings
from app.services.observability import increment

CAPACITY_BUSY_CODE = "code_interpreter_capacity_busy"
CAPACITY_UNAVAILABLE_CODE = "code_interpreter_capacity_unavailable"

_BUSY_MESSAGE = "Code Interpreter is currently busy. Please try again later."
_UNAVAILABLE_MESSAGE = "Code Interpreter is temporarily unavailable. Try again shortly."

_KEY_PREFIX = "ci:capacity"
_GLOBAL_ZSET = f"{_KEY_PREFIX}:global"
_SUBJECT_ZSET_PREFIX = f"{_KEY_PREFIX}:subject:"
_LEASE_KEY_PREFIX = f"{_KEY_PREFIX}:lease:"
_POLICY_HASH = f"{_KEY_PREFIX}:policy"
_SETTING_GLOBAL_MAX = "code_interpreter_capacity_global_max"
_SETTING_PER_SUBJECT_MAX = "code_interpreter_capacity_per_subject_max"
_SETTING_RETRY_AFTER = "code_interpreter_capacity_retry_after_seconds"

# Atomic acquire: prune expired members, enforce global + subject caps, then
# add lease_id to both ZSETs and store subject metadata with TTL.
_ACQUIRE_LUA = """
local global_key = KEYS[1]
local subject_key = KEYS[2]
local lease_key = KEYS[3]
local lease_id = ARGV[1]
local subject = ARGV[2]
local now = tonumber(ARGV[3])
local expiry = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
local global_max = tonumber(ARGV[6])
local subject_max = tonumber(ARGV[7])

redis.call('ZREMRANGEBYSCORE', global_key, '-inf', now)
redis.call('ZREMRANGEBYSCORE', subject_key, '-inf', now)

local existing = redis.call('GET', lease_key)
if existing then
  if existing == subject then
    redis.call('ZADD', global_key, expiry, lease_id)
    redis.call('ZADD', subject_key, expiry, lease_id)
    redis.call('SET', lease_key, subject, 'EX', ttl)
    return {1, redis.call('ZCARD', global_key), redis.call('ZCARD', subject_key)}
  end
  return {-2, redis.call('ZCARD', global_key), redis.call('ZCARD', subject_key)}
end

local global_count = redis.call('ZCARD', global_key)
if global_count >= global_max then
  return {0, global_count, redis.call('ZCARD', subject_key)}
end

local subject_count = redis.call('ZCARD', subject_key)
if subject_count >= subject_max then
  return {-1, global_count, subject_count}
end

redis.call('ZADD', global_key, expiry, lease_id)
redis.call('ZADD', subject_key, expiry, lease_id)
redis.call('SET', lease_key, subject, 'EX', ttl)
return {1, global_count + 1, subject_count + 1}
"""

# Idempotent release: remove lease from ZSETs and delete metadata.
_RELEASE_LUA = """
local global_key = KEYS[1]
local lease_key = KEYS[2]
local lease_id = ARGV[1]
local now = tonumber(ARGV[2])
local subject_prefix = ARGV[3]

redis.call('ZREMRANGEBYSCORE', global_key, '-inf', now)

local subject = redis.call('GET', lease_key)
local removed = redis.call('ZREM', global_key, lease_id)
local had_meta = 0
if subject and subject ~= false and subject ~= '' then
  local subject_key = subject_prefix .. subject
  redis.call('ZREM', subject_key, lease_id)
  redis.call('ZREMRANGEBYSCORE', subject_key, '-inf', now)
  had_meta = 1
end
redis.call('DEL', lease_key)
if removed > 0 or had_meta == 1 then
  return 1
end
return 0
"""

# Heartbeat: extend lease TTL and ZSET scores when the lease still exists.
_HEARTBEAT_LUA = """
local global_key = KEYS[1]
local lease_key = KEYS[2]
local lease_id = ARGV[1]
local now = tonumber(ARGV[2])
local expiry = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local subject_prefix = ARGV[5]

redis.call('ZREMRANGEBYSCORE', global_key, '-inf', now)

local subject = redis.call('GET', lease_key)
if not subject or subject == false or subject == '' then
  redis.call('ZREM', global_key, lease_id)
  return 0
end

local subject_key = subject_prefix .. subject
redis.call('ZREMRANGEBYSCORE', subject_key, '-inf', now)
redis.call('SET', lease_key, subject, 'EX', ttl)
redis.call('ZADD', global_key, expiry, lease_id)
redis.call('ZADD', subject_key, expiry, lease_id)
return 1
"""

# Stats: prune expired global members and return active count.
_STATS_LUA = """
local global_key = KEYS[1]
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', global_key, '-inf', now)
return redis.call('ZCARD', global_key)
"""


@dataclass(frozen=True)
class CapacityPermit:
    """Held admission lease for one Code Interpreter turn."""

    lease_id: str
    subject: str
    expires_at: float


def subject_for_user(user_id: int | str) -> str:
    """Subject key for an authenticated browser/user turn."""
    return f"user:{int(user_id)}"


def subject_for_api_key(api_key_id: int | str) -> str:
    """Subject key for an Alpharouter /v1 API-key turn."""
    return f"api_key:{int(api_key_id)}"


def subject_for_system(name: str = "probe") -> str:
    """Subject key for system jobs (probes, maintenance) that share capacity."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(name or "probe").strip())
    cleaned = cleaned.strip("-_") or "probe"
    return f"system:{cleaned}"


def _capacity_settings() -> dict[str, int]:
    settings = get_settings()
    return {
        "global_max": max(1, int(settings.code_interpreter_capacity_global_max or 200)),
        "per_subject_max": max(1, int(settings.code_interpreter_capacity_per_subject_max or 2)),
        "lease_ttl": max(30, int(settings.code_interpreter_capacity_lease_ttl_seconds or 900)),
        "heartbeat": max(5, int(settings.code_interpreter_capacity_heartbeat_seconds or 30)),
        "retry_after": max(1, int(settings.code_interpreter_capacity_retry_after_seconds or 30)),
    }


def _normalize_policy(
    base: dict[str, int],
    *,
    global_max: int | None = None,
    per_subject_max: int | None = None,
    retry_after: int | None = None,
) -> dict[str, int]:
    hard_global = max(1, int(base["global_max"]))
    operational_global = min(
        hard_global,
        max(1, int(global_max if global_max is not None else hard_global)),
    )
    operational_subject = min(
        operational_global,
        max(
            1,
            int(per_subject_max if per_subject_max is not None else base["per_subject_max"]),
        ),
    )
    return {
        **base,
        "global_max": operational_global,
        "per_subject_max": operational_subject,
        "retry_after": max(
            1,
            min(
                300,
                int(retry_after if retry_after is not None else base["retry_after"]),
            ),
        ),
        "hard_global_max": hard_global,
    }


async def _effective_policy(client: Any, base: dict[str, int]) -> dict[str, int]:
    hgetall = getattr(client, "hgetall", None)
    if not callable(hgetall):
        return _normalize_policy(base)
    raw = await hgetall(_POLICY_HASH)
    if not raw:
        return _normalize_policy(base)

    def _optional_int(key: str) -> int | None:
        value = raw.get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return _normalize_policy(
        base,
        global_max=_optional_int("global_max"),
        per_subject_max=_optional_int("per_subject_max"),
        retry_after=_optional_int("retry_after"),
    )


def _subject_zset_key(subject: str) -> str:
    return f"{_SUBJECT_ZSET_PREFIX}{subject}"


def _lease_key(lease_id: str) -> str:
    return f"{_LEASE_KEY_PREFIX}{lease_id}"


def _busy_exception(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": CAPACITY_BUSY_CODE,
            "message": _BUSY_MESSAGE,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


def _unavailable_exception(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": CAPACITY_UNAVAILABLE_CODE,
            "message": _UNAVAILABLE_MESSAGE,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


def _redis_client():
    """Shared per-process client (may raise; never closed here)."""
    return get_redis()


def _normalize_permit(permit: CapacityPermit | str) -> str:
    if isinstance(permit, CapacityPermit):
        return permit.lease_id
    return str(permit)


async def acquire_code_interpreter_turn(
    subject: str,
    *,
    lease_id: str | None = None,
    global_limit: int | None = None,
    subject_limit: int | None = None,
) -> CapacityPermit:
    """Acquire one turn lease or raise HTTP 429/503.

    ``global_limit`` / ``subject_limit`` override settings (useful for system
    probes that need a tighter subject cap). No queue: capacity full → 429.
    """
    base_cfg = _capacity_settings()
    subject = str(subject or "").strip()
    if not subject:
        raise ValueError("subject is required")

    lease = (lease_id or "").strip() or str(uuid.uuid4())
    now = time.time()
    ttl = base_cfg["lease_ttl"]
    expiry = now + ttl
    retry_after = base_cfg["retry_after"]

    client = None
    try:
        client = _redis_client()
        cfg = await _effective_policy(client, base_cfg)
        g_max = max(
            1,
            int(global_limit if global_limit is not None else cfg["global_max"]),
        )
        s_max = max(
            1,
            int(subject_limit if subject_limit is not None else cfg["per_subject_max"]),
        )
        retry_after = cfg["retry_after"]
        result = await client.eval(
            _ACQUIRE_LUA,
            3,
            _GLOBAL_ZSET,
            _subject_zset_key(subject),
            _lease_key(lease),
            lease,
            subject,
            str(now),
            str(expiry),
            str(ttl),
            str(g_max),
            str(s_max),
        )
    except Exception as exc:
        raise _unavailable_exception(retry_after) from exc

    status = int(result[0]) if result else 0
    if status == 1:
        return CapacityPermit(lease_id=lease, subject=subject, expires_at=expiry)
    increment("code_interpreter_capacity_rejected")
    raise _busy_exception(retry_after)


async def release_code_interpreter_turn(permit: CapacityPermit | str) -> bool:
    """Release a turn lease. Idempotent: missing leases return False.

    Redis outages during release return False (TTL reclaim) so stream ``finally``
    blocks stay safe. Fail-closed 503 applies to acquire/heartbeat/stats only.
    """
    lease_id = _normalize_permit(permit)
    if not lease_id:
        return False

    now = time.time()
    client = None
    try:
        client = _redis_client()
        result = await client.eval(
            _RELEASE_LUA,
            2,
            _GLOBAL_ZSET,
            _lease_key(lease_id),
            lease_id,
            str(now),
            _SUBJECT_ZSET_PREFIX,
        )
        return bool(int(result or 0))
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return False)
        return False


async def heartbeat_code_interpreter_turn(permit: CapacityPermit | str) -> bool:
    """Extend lease TTL/scores. Returns False if the lease is gone (stop turn).

    Redis outages raise HTTP 503 so the active turn can fail closed.
    """
    cfg = _capacity_settings()
    lease_id = _normalize_permit(permit)
    if not lease_id:
        return False

    now = time.time()
    ttl = cfg["lease_ttl"]
    expiry = now + ttl

    client = None
    try:
        client = _redis_client()
        result = await client.eval(
            _HEARTBEAT_LUA,
            2,
            _GLOBAL_ZSET,
            _lease_key(lease_id),
            lease_id,
            str(now),
            str(expiry),
            str(ttl),
            _SUBJECT_ZSET_PREFIX,
        )
        return bool(int(result or 0))
    except Exception as exc:
        raise _unavailable_exception(cfg["retry_after"]) from exc


async def code_interpreter_capacity_stats() -> dict[str, Any]:
    """Return live capacity snapshot for operations / preflight diagnostics."""
    base_cfg = _capacity_settings()
    now = time.time()
    client = None
    try:
        client = _redis_client()
        cfg = await _effective_policy(client, base_cfg)
        active = int(
            await client.eval(
                _STATS_LUA,
                1,
                _GLOBAL_ZSET,
                str(now),
            )
            or 0
        )
    except Exception as exc:
        raise _unavailable_exception(base_cfg["retry_after"]) from exc

    limit = cfg["global_max"]
    return {
        "active": active,
        "limit": limit,
        "available": max(0, limit - active),
        "per_subject_limit": cfg["per_subject_max"],
        "lease_ttl_seconds": cfg["lease_ttl"],
        "heartbeat_seconds": cfg["heartbeat"],
        "retry_after_seconds": cfg["retry_after"],
        "hard_limit": cfg["hard_global_max"],
    }


async def get_code_interpreter_capacity_policy(db: Any) -> dict[str, int]:
    """Load persisted operational limits and clamp them to environment hard limits."""
    from app.models.system import SystemSetting

    base = _capacity_settings()

    async def _read(key: str) -> int | None:
        row = await db.get(SystemSetting, key)
        if row is None or row.value is None:
            return None
        try:
            return int(row.value)
        except (TypeError, ValueError):
            return None

    policy = _normalize_policy(
        base,
        global_max=await _read(_SETTING_GLOBAL_MAX),
        per_subject_max=await _read(_SETTING_PER_SUBJECT_MAX),
        retry_after=await _read(_SETTING_RETRY_AFTER),
    )
    return {
        "global_max": policy["global_max"],
        "per_subject_max": policy["per_subject_max"],
        "retry_after_seconds": policy["retry_after"],
        "lease_ttl_seconds": policy["lease_ttl"],
        "heartbeat_seconds": policy["heartbeat"],
        "hard_global_max": policy["hard_global_max"],
    }


async def sync_code_interpreter_capacity_policy(db: Any) -> dict[str, int]:
    """Publish persisted policy to Redis so every API worker sees it immediately."""
    policy = await get_code_interpreter_capacity_policy(db)
    client = None
    try:
        client = _redis_client()
        await client.hset(
            _POLICY_HASH,
            mapping={
                "global_max": str(policy["global_max"]),
                "per_subject_max": str(policy["per_subject_max"]),
                "retry_after": str(policy["retry_after_seconds"]),
            },
        )
    except Exception as exc:
        raise _unavailable_exception(policy["retry_after_seconds"]) from exc
    return policy


async def set_code_interpreter_capacity_policy(
    db: Any,
    *,
    global_max: int,
    per_subject_max: int,
    retry_after_seconds: int,
) -> dict[str, int]:
    """Persist and publish Admin-managed operational limits."""
    from app.models.system import SystemSetting

    base = _capacity_settings()
    normalized = _normalize_policy(
        base,
        global_max=global_max,
        per_subject_max=per_subject_max,
        retry_after=retry_after_seconds,
    )
    values = {
        _SETTING_GLOBAL_MAX: normalized["global_max"],
        _SETTING_PER_SUBJECT_MAX: normalized["per_subject_max"],
        _SETTING_RETRY_AFTER: normalized["retry_after"],
    }
    for key, value in values.items():
        row = await db.get(SystemSetting, key)
        if row is None:
            db.add(SystemSetting(key=key, value=str(value)))
        else:
            row.value = str(value)
    await db.flush()
    return {
        "global_max": normalized["global_max"],
        "per_subject_max": normalized["per_subject_max"],
        "retry_after_seconds": normalized["retry_after"],
        "lease_ttl_seconds": normalized["lease_ttl"],
        "heartbeat_seconds": normalized["heartbeat"],
        "hard_global_max": normalized["hard_global_max"],
    }
