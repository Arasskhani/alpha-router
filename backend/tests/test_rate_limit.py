"""Tests for the rate limiter.

The Redis path is exercised via a fake async client. Chat endpoints keep
fail-open in-memory fallback; login is fail-closed (HTTP 503) on Redis outage.
"""

import asyncio
import pytest
from fastapi import HTTPException

from app.services import rate_limit as rl


class _FakeRedisOk:
    """A minimal async fake mimicking the pipeline ops used by check_rate_limit."""

    def __init__(self):
        self._store: dict[str, dict[str, float]] = {}

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self):
                self._ops = []

            def zadd(self, key, mapping):
                self._ops.append(("zadd", key, mapping))
                return self

            def zremrangebyscore(self, key, lo, hi):
                self._ops.append(("zremrangebyscore", key, lo, hi))
                return self

            def zcard(self, key):
                self._ops.append(("zcard", key))
                return self

            def expire(self, key, ttl):
                self._ops.append(("expire", key, ttl))
                return self

            async def execute(self):
                results = []
                for op in self._ops:
                    kind = op[0]
                    key = op[1]
                    outer._store.setdefault(key, {})
                    if kind == "zadd":
                        mapping = op[2]
                        outer._store[key].update(mapping)
                        results.append(len(mapping))
                    elif kind == "zremrangebyscore":
                        lo, hi = op[2], op[3]
                        before = dict(outer._store[key])
                        outer._store[key] = {
                            m: t for m, t in before.items() if not (lo <= t <= hi)
                        }
                        results.append(len(before) - len(outer._store[key]))
                    elif kind == "zcard":
                        results.append(len(outer._store[key]))
                    elif kind == "expire":
                        results.append(True)
                return results

        return _Pipe()

    async def aclose(self):
        pass


class _FakeRedisBroken:
    def pipeline(self):
        raise RuntimeError("redis down")

    async def aclose(self):
        pass


def test_check_rate_limit_allows_under_limit():
    fake = _FakeRedisOk()

    async def go():
        rl._client = lambda: fake  # type: ignore[assignment]
        for _ in range(5):
            await rl.check_rate_limit("k1", limit=5)

    asyncio.run(go())


def test_check_rate_limit_blocks_over_limit():
    fake = _FakeRedisOk()

    async def go():
        rl._client = lambda: fake  # type: ignore[assignment]
        for _ in range(3):
            await rl.check_rate_limit("k2", limit=3)
        with pytest.raises(HTTPException) as exc:
            await rl.check_rate_limit("k2", limit=3)
        assert exc.value.status_code == 429

    asyncio.run(go())


def test_check_rate_limit_fails_open_to_in_memory_when_redis_down():
    # When the fake client raises, non-auth limiters fall back to the
    # in-memory per-process counter (fail-open) instead of erroring.
    broken = _FakeRedisBroken()
    rl._buckets.clear()

    async def go():
        rl._client = lambda: broken  # type: ignore[assignment]
        for _ in range(2):
            await rl.check_rate_limit("k3", limit=2)
        with pytest.raises(HTTPException):
            await rl.check_rate_limit("k3", limit=2)

    asyncio.run(go())


def test_check_rate_limit_fail_closed_when_redis_errors():
    broken = _FakeRedisBroken()

    async def go():
        rl._client = lambda: broken  # type: ignore[assignment]
        with pytest.raises(HTTPException) as exc:
            await rl.check_rate_limit("login:user:alice", limit=20, fail_closed=True)
        assert exc.value.status_code == 503
        assert "unavailable" in exc.value.detail.lower()

    asyncio.run(go())


def test_check_rate_limit_fail_closed_when_client_missing():
    async def go():
        rl._client = lambda: None  # type: ignore[assignment]
        with pytest.raises(HTTPException) as exc:
            await rl.check_rate_limit("login:ip:1.2.3.4", limit=60, fail_closed=True)
        assert exc.value.status_code == 503

    asyncio.run(go())


def test_check_login_rate_limit_fail_closed_on_redis_outage():
    broken = _FakeRedisBroken()

    async def go():
        rl._client = lambda: broken  # type: ignore[assignment]
        with pytest.raises(HTTPException) as exc:
            await rl.check_login_rate_limit("alice", "10.0.0.1")
        assert exc.value.status_code == 503

    asyncio.run(go())


def test_check_login_rate_limit_allows_under_limit_via_redis():
    fake = _FakeRedisOk()

    async def go():
        rl._client = lambda: fake  # type: ignore[assignment]
        await rl.check_login_rate_limit("bob", "10.0.0.2")

    asyncio.run(go())
