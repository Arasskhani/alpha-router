"""Unit tests for Redis-backed Code Interpreter capacity admission."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.system import SystemSetting
from app.services import code_interpreter_capacity_service as caps


class _FakeRedis:
    """In-memory Redis stand-in that executes the capacity Lua scripts in Python."""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.strings: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, float] = {}
        self.closed = False
        self.fail_next = False

    def _prune(self, key: str, now: float) -> None:
        members = self.zsets.get(key) or {}
        self.zsets[key] = {m: score for m, score in members.items() if score > now}

    def _expire_strings(self, now: float) -> None:
        expired = [k for k, exp in self.ttls.items() if exp <= now]
        for key in expired:
            self.strings.pop(key, None)
            self.ttls.pop(key, None)

    async def eval(self, script: str, num_keys: int, *keys_and_args: Any):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("redis down")

        keys = list(keys_and_args[:num_keys])
        args = list(keys_and_args[num_keys:])
        now = time.time()
        self._expire_strings(now)

        if script is caps._ACQUIRE_LUA or script == caps._ACQUIRE_LUA:
            return self._acquire(keys, args)
        if script is caps._RELEASE_LUA or script == caps._RELEASE_LUA:
            return self._release(keys, args)
        if script is caps._HEARTBEAT_LUA or script == caps._HEARTBEAT_LUA:
            return self._heartbeat(keys, args)
        if script is caps._STATS_LUA or script == caps._STATS_LUA:
            return self._stats(keys, args)
        raise AssertionError(f"unexpected script ({num_keys=})")

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        self.hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    def _acquire(self, keys: list[Any], args: list[Any]):
        global_key, subject_key, lease_key = keys
        lease_id, subject = str(args[0]), str(args[1])
        now, expiry = float(args[2]), float(args[3])
        ttl = int(float(args[4]))
        global_max, subject_max = int(float(args[5])), int(float(args[6]))

        self._prune(global_key, now)
        self._prune(subject_key, now)

        existing = self.strings.get(lease_key)
        if existing is not None:
            if existing == subject:
                self.zsets.setdefault(global_key, {})[lease_id] = expiry
                self.zsets.setdefault(subject_key, {})[lease_id] = expiry
                self.strings[lease_key] = subject
                self.ttls[lease_key] = now + ttl
                return [1, len(self.zsets[global_key]), len(self.zsets[subject_key])]
            return [-2, len(self.zsets.get(global_key, {})), len(self.zsets.get(subject_key, {}))]

        global_count = len(self.zsets.get(global_key, {}))
        if global_count >= global_max:
            return [0, global_count, len(self.zsets.get(subject_key, {}))]

        subject_count = len(self.zsets.get(subject_key, {}))
        if subject_count >= subject_max:
            return [-1, global_count, subject_count]

        self.zsets.setdefault(global_key, {})[lease_id] = expiry
        self.zsets.setdefault(subject_key, {})[lease_id] = expiry
        self.strings[lease_key] = subject
        self.ttls[lease_key] = now + ttl
        return [1, global_count + 1, subject_count + 1]

    def _release(self, keys: list[Any], args: list[Any]):
        global_key, lease_key = keys
        lease_id = str(args[0])
        now = float(args[1])
        subject_prefix = str(args[2])
        self._prune(global_key, now)

        subject = self.strings.get(lease_key)
        removed = 0
        if lease_id in self.zsets.get(global_key, {}):
            del self.zsets[global_key][lease_id]
            removed = 1
        had_meta = 0
        if subject:
            subject_key = f"{subject_prefix}{subject}"
            if lease_id in self.zsets.get(subject_key, {}):
                del self.zsets[subject_key][lease_id]
            self._prune(subject_key, now)
            had_meta = 1
        self.strings.pop(lease_key, None)
        self.ttls.pop(lease_key, None)
        return 1 if removed or had_meta else 0

    def _heartbeat(self, keys: list[Any], args: list[Any]):
        global_key, lease_key = keys
        lease_id = str(args[0])
        now, expiry = float(args[1]), float(args[2])
        ttl = int(float(args[3]))
        subject_prefix = str(args[4])
        self._prune(global_key, now)

        subject = self.strings.get(lease_key)
        if not subject:
            self.zsets.get(global_key, {}).pop(lease_id, None)
            return 0

        subject_key = f"{subject_prefix}{subject}"
        self._prune(subject_key, now)
        self.strings[lease_key] = subject
        self.ttls[lease_key] = now + ttl
        self.zsets.setdefault(global_key, {})[lease_id] = expiry
        self.zsets.setdefault(subject_key, {})[lease_id] = expiry
        return 1

    def _stats(self, keys: list[Any], args: list[Any]):
        global_key = keys[0]
        now = float(args[0])
        self._prune(global_key, now)
        return len(self.zsets.get(global_key, {}))

    async def aclose(self) -> None:
        self.closed = True


class _FakeDb:
    def __init__(self) -> None:
        self.rows: dict[str, SystemSetting] = {}

    async def get(self, model, key: str):
        assert model is SystemSetting
        return self.rows.get(key)

    def add(self, row: SystemSetting) -> None:
        self.rows[str(row.key)] = row

    async def flush(self) -> None:
        return None


def _settings(**overrides: Any) -> SimpleNamespace:
    base = {
        "code_interpreter_capacity_global_max": 200,
        "code_interpreter_capacity_per_subject_max": 2,
        "code_interpreter_capacity_lease_ttl_seconds": 900,
        "code_interpreter_capacity_heartbeat_seconds": 30,
        "code_interpreter_capacity_retry_after_seconds": 30,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _run(coro):
    return asyncio.run(coro)


def test_subject_helpers() -> None:
    assert caps.subject_for_user(42) == "user:42"
    assert caps.subject_for_api_key("7") == "api_key:7"
    assert caps.subject_for_system("probe") == "system:probe"
    assert caps.subject_for_system("CI Probe!") == "system:CI-Probe"


def test_acquire_release_and_stats_roundtrip() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(caps, "get_settings", return_value=_settings(code_interpreter_capacity_global_max=3)),
        ):
            p1 = await caps.acquire_code_interpreter_turn(caps.subject_for_user(1))
            p2 = await caps.acquire_code_interpreter_turn(caps.subject_for_api_key(9))
            stats = await caps.code_interpreter_capacity_stats()
            assert stats["active"] == 2
            assert stats["limit"] == 3
            assert stats["available"] == 1
            assert stats["per_subject_limit"] == 2
            assert stats["retry_after_seconds"] == 30
            assert await caps.release_code_interpreter_turn(p1) is True
            assert await caps.release_code_interpreter_turn(p1) is False  # idempotent
            assert await caps.release_code_interpreter_turn(p2.lease_id) is True
            stats2 = await caps.code_interpreter_capacity_stats()
            assert stats2["active"] == 0
            assert stats2["available"] == 3

    _run(go())


def test_global_limit_rejects_with_structured_429() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(
                caps,
                "get_settings",
                return_value=_settings(
                    code_interpreter_capacity_global_max=2,
                    code_interpreter_capacity_per_subject_max=10,
                    code_interpreter_capacity_retry_after_seconds=30,
                ),
            ),
        ):
            await caps.acquire_code_interpreter_turn("user:1")
            await caps.acquire_code_interpreter_turn("user:2")
            with pytest.raises(HTTPException) as excinfo:
                await caps.acquire_code_interpreter_turn("user:3")
            err = excinfo.value
            assert err.status_code == 429
            assert err.headers == {"Retry-After": "30"}
            assert err.detail["code"] == caps.CAPACITY_BUSY_CODE
            assert err.detail["retry_after_seconds"] == 30
            assert "busy" in err.detail["message"].lower()

    _run(go())


def test_per_subject_limit_rejects_immediately() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(
                caps,
                "get_settings",
                return_value=_settings(
                    code_interpreter_capacity_global_max=200,
                    code_interpreter_capacity_per_subject_max=2,
                ),
            ),
        ):
            await caps.acquire_code_interpreter_turn("user:1")
            await caps.acquire_code_interpreter_turn("user:1")
            with pytest.raises(HTTPException) as excinfo:
                await caps.acquire_code_interpreter_turn("user:1")
            assert excinfo.value.status_code == 429
            # Other subjects remain admissible.
            await caps.acquire_code_interpreter_turn("user:2")

    _run(go())


def test_redis_operational_policy_overrides_environment_defaults() -> None:
    fake = _FakeRedis()
    fake.hashes[caps._POLICY_HASH] = {
        "global_max": "1",
        "per_subject_max": "1",
        "retry_after": "17",
    }

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(caps, "get_settings", return_value=_settings()),
        ):
            await caps.acquire_code_interpreter_turn("user:1")
            with pytest.raises(HTTPException) as excinfo:
                await caps.acquire_code_interpreter_turn("user:2")
            assert excinfo.value.status_code == 429
            assert excinfo.value.headers == {"Retry-After": "17"}
            stats = await caps.code_interpreter_capacity_stats()
            assert stats["limit"] == 1
            assert stats["hard_limit"] == 200

    _run(go())


def test_admin_policy_is_persisted_published_and_clamped_to_hard_limit() -> None:
    fake_db = _FakeDb()
    fake_redis = _FakeRedis()

    async def go():
        with patch.object(caps, "get_settings", return_value=_settings()):
            stored = await caps.set_code_interpreter_capacity_policy(
                fake_db,
                global_max=999,
                per_subject_max=500,
                retry_after_seconds=999,
            )
            assert stored["global_max"] == 200
            assert stored["per_subject_max"] == 200
            assert stored["retry_after_seconds"] == 300
            with patch.object(caps, "_redis_client", return_value=fake_redis):
                published = await caps.sync_code_interpreter_capacity_policy(fake_db)
            assert published["global_max"] == 200
            assert fake_redis.hashes[caps._POLICY_HASH]["global_max"] == "200"
            assert fake_redis.hashes[caps._POLICY_HASH]["retry_after"] == "300"

    _run(go())


def test_idempotent_acquire_same_lease_id() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(caps, "get_settings", return_value=_settings(code_interpreter_capacity_global_max=1)),
        ):
            first = await caps.acquire_code_interpreter_turn("user:1", lease_id="turn-a")
            second = await caps.acquire_code_interpreter_turn("user:1", lease_id="turn-a")
            assert first.lease_id == second.lease_id == "turn-a"
            stats = await caps.code_interpreter_capacity_stats()
            assert stats["active"] == 1

    _run(go())


def test_heartbeat_extends_and_missing_returns_false() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(
                caps,
                "get_settings",
                return_value=_settings(code_interpreter_capacity_lease_ttl_seconds=900),
            ),
        ):
            permit = await caps.acquire_code_interpreter_turn("user:1")
            lease_key = caps._lease_key(permit.lease_id)
            before = fake.ttls[lease_key]
            fake.ttls[lease_key] = before - 100
            assert await caps.heartbeat_code_interpreter_turn(permit) is True
            assert fake.ttls[lease_key] > before - 100
            await caps.release_code_interpreter_turn(permit)
            assert await caps.heartbeat_code_interpreter_turn(permit) is False

    _run(go())


def test_redis_outage_fail_closed_503_on_acquire() -> None:
    async def go():
        with (
            patch.object(caps, "_redis_client", side_effect=RuntimeError("no redis")),
            patch.object(caps, "get_settings", return_value=_settings()),
        ):
            with pytest.raises(HTTPException) as excinfo:
                await caps.acquire_code_interpreter_turn("user:1")
            err = excinfo.value
            assert err.status_code == 503
            assert err.detail["code"] == caps.CAPACITY_UNAVAILABLE_CODE
            assert err.headers == {"Retry-After": "30"}

    _run(go())


def test_stats_and_heartbeat_fail_closed_on_redis_error() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(caps, "get_settings", return_value=_settings()),
        ):
            permit = await caps.acquire_code_interpreter_turn("user:1")
            fake.fail_next = True
            with pytest.raises(HTTPException) as excinfo:
                await caps.heartbeat_code_interpreter_turn(permit)
            assert excinfo.value.status_code == 503
            fake.fail_next = True
            with pytest.raises(HTTPException) as excinfo:
                await caps.code_interpreter_capacity_stats()
            assert excinfo.value.status_code == 503

    _run(go())


def test_release_soft_fails_on_redis_error() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(caps, "get_settings", return_value=_settings()),
        ):
            permit = await caps.acquire_code_interpreter_turn("user:1")
            fake.fail_next = True
            assert await caps.release_code_interpreter_turn(permit) is False

    _run(go())


def test_system_subject_and_limit_overrides() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(
                caps,
                "get_settings",
                return_value=_settings(
                    code_interpreter_capacity_global_max=200,
                    code_interpreter_capacity_per_subject_max=2,
                ),
            ),
        ):
            subject = caps.subject_for_system("probe")
            await caps.acquire_code_interpreter_turn(subject, subject_limit=1)
            with pytest.raises(HTTPException) as excinfo:
                await caps.acquire_code_interpreter_turn(subject, subject_limit=1)
            assert excinfo.value.status_code == 429

    _run(go())


def test_expired_leases_are_pruned_on_acquire() -> None:
    fake = _FakeRedis()

    async def go():
        with (
            patch.object(caps, "_redis_client", return_value=fake),
            patch.object(
                caps,
                "get_settings",
                return_value=_settings(code_interpreter_capacity_global_max=1),
            ),
        ):
            permit = await caps.acquire_code_interpreter_turn("user:1", lease_id="old")
            # Simulate TTL expiry: drop string meta and mark ZSET score in the past.
            lease_key = caps._lease_key(permit.lease_id)
            fake.strings.pop(lease_key, None)
            fake.ttls.pop(lease_key, None)
            fake.zsets[caps._GLOBAL_ZSET][permit.lease_id] = time.time() - 10
            fake.zsets[caps._subject_zset_key("user:1")][permit.lease_id] = time.time() - 10
            # Slot reclaimable for a new turn.
            await caps.acquire_code_interpreter_turn("user:2", lease_id="new")
            stats = await caps.code_interpreter_capacity_stats()
            assert stats["active"] == 1

    _run(go())
