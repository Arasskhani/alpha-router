"""One Redis client per worker: built once per loop, never closed by callers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import redis_client


def test_get_redis_builds_once_per_loop_and_url(monkeypatch):
    redis_client.reset_for_tests()
    built = []

    def fake_build(url):
        built.append(url)
        c = MagicMock(name=f"redis-{len(built)}")
        c.aclose = AsyncMock()
        return c

    monkeypatch.setattr(redis_client, "_build", fake_build)
    monkeypatch.setattr(redis_client, "effective_redis_url", lambda: "redis://a:6379/0")

    async def run():
        first = redis_client.get_redis()
        for _ in range(100):
            assert redis_client.get_redis() is first
        assert built == ["redis://a:6379/0"]
        # URL change (settings reload in tests/ops) -> a new client.
        monkeypatch.setattr(redis_client, "effective_redis_url", lambda: "redis://b:6379/0")
        second = redis_client.get_redis()
        assert second is not first and len(built) == 2
        await redis_client.close_redis()
        second.aclose.assert_awaited_once()
        # Closed: the next call builds again.
        redis_client.get_redis()
        assert len(built) == 3

    asyncio.run(run())

    # A different event loop never reuses the previous loop's client.
    async def run2():
        redis_client.get_redis()

    asyncio.run(run2())
    assert len(built) == 4
    redis_client.reset_for_tests()


def test_hot_paths_share_the_client_and_never_close_it(monkeypatch):
    """100 rate-limit checks + 100 presence pings + 50 one-time codes = 1 client, 0 aclose."""
    redis_client.reset_for_tests()

    class FakePipe:
        def __init__(self, store):
            self.store = store
            self.ops = []

        def __getattr__(self, name):
            def op(*a, **k):
                self.ops.append(name)
                return self
            return op

        async def execute(self):
            out = []
            for name in self.ops:
                out.append(1 if name in ("zcard", "delete") else None)
            self.ops = []
            return out

    class FakeRedis:
        instances = 0

        def __init__(self):
            FakeRedis.instances += 1
            self.closed = 0
            self.store = {}

        def pipeline(self):
            return FakePipe(self.store)

        async def set(self, k, v, ex=None, nx=False):
            self.store[k] = v
            return True

        async def delete(self, k):
            return 1 if self.store.pop(k, None) is not None else 0

        async def mget(self, keys):
            return [self.store.get(k) for k in keys]

        async def aclose(self):
            self.closed += 1

    monkeypatch.setattr(redis_client, "_build", lambda url: FakeRedis())
    monkeypatch.setattr(redis_client, "effective_redis_url", lambda: "redis://x/0")

    from app.services import auth_exchange, presence_service, rate_limit

    async def run():
        with patch.object(presence_service, "presence_enabled", lambda: True):
            for i in range(100):
                await rate_limit.check_rate_limit(f"k{i}", limit=10)
                await presence_service.mark_online(i)
            for i in range(50):
                await auth_exchange.store_token(f"c{i}", {"i": i})
        client = redis_client.get_redis()
        assert FakeRedis.instances == 1
        assert client.closed == 0
        assert await presence_service.online_user_ids([1, 2, 999]) == {1, 2}

    asyncio.run(run())
    redis_client.reset_for_tests()
