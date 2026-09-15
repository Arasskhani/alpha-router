"""One-time exchange code is single-use and short-lived.

Uses a fake async Redis client to avoid a live Redis dependency in unit tests.
"""

from unittest.mock import patch

from app.services import auth_exchange


class FakeRedis:
    """Minimal async Redis-like store backed by a dict."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return self.store.pop(key, None) is not None

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self):
                self._ops = []

            def get(self, key):
                self._ops.append(("get", key))
                return self

            def delete(self, key):
                self._ops.append(("delete", key))
                return self

            async def execute(self):
                results = []
                for op, key in self._ops:
                    if op == "get":
                        results.append(await outer.get(key))
                    elif op == "delete":
                        results.append(await outer.delete(key))
                return results

        return _Pipe()

    async def aclose(self):
        return None


class BrokenRedis(FakeRedis):
    async def set(self, key, value, ex=None):
        raise RuntimeError("redis down")

    def pipeline(self):
        raise RuntimeError("redis down")


async def _test_store_and_consume_once() -> None:
    fake = FakeRedis()
    with patch("app.services.auth_exchange._client", return_value=fake):
        code = auth_exchange.generate_code()
        await auth_exchange.store_token(code, {"token": "JWT-1", "role": "user"})
        payload = await auth_exchange.consume_code(code)
        assert payload == {"token": "JWT-1", "role": "user"}
        assert await auth_exchange.consume_code(code) is None


async def _test_consume_is_single_use() -> None:
    fake = FakeRedis()
    with patch("app.services.auth_exchange._client", return_value=fake):
        code = auth_exchange.generate_code()
        await auth_exchange.store_token(code, {"token": "JWT-2"})
        first = await auth_exchange.consume_code(code)
        second = await auth_exchange.consume_code(code)
        assert first == {"token": "JWT-2"}
        assert second is None


async def _test_missing_code() -> None:
    fake = FakeRedis()
    with patch("app.services.auth_exchange._client", return_value=fake):
        assert await auth_exchange.consume_code("nonexistent") is None
        assert await auth_exchange.consume_code("") is None


async def _test_memory_fallback_when_redis_down() -> None:
    broken = BrokenRedis()
    auth_exchange._mem_store.clear()
    with patch("app.services.auth_exchange._client", return_value=broken):
        code = auth_exchange.generate_code()
        await auth_exchange.store_token(code, {"token": "JWT-FALLBACK"})
        payload = await auth_exchange.consume_code(code)
        assert payload == {"token": "JWT-FALLBACK"}


async def _test_memory_fallback_expired() -> None:
    broken = BrokenRedis()
    auth_exchange._mem_store.clear()
    with patch("app.services.auth_exchange._client", return_value=broken):
        code = auth_exchange.generate_code()
        await auth_exchange.store_token(code, {"token": "JWT-EXPIRED"})
        raw, _ = auth_exchange._mem_store[code]
        auth_exchange._mem_store[code] = (raw, 0.0)
        payload = await auth_exchange.consume_code(code)
        assert payload is None


async def _test_memory_fallback_single_use() -> None:
    broken = BrokenRedis()
    auth_exchange._mem_store.clear()
    with patch("app.services.auth_exchange._client", return_value=broken):
        code = auth_exchange.generate_code()
        await auth_exchange.store_token(code, {"token": "JWT-ONCE"})
        first = await auth_exchange.consume_code(code)
        second = await auth_exchange.consume_code(code)
        assert first == {"token": "JWT-ONCE"}
        assert second is None


async def test_store_and_consume_once():
    await _test_store_and_consume_once()


async def test_consume_is_single_use():
    await _test_consume_is_single_use()


async def test_missing_code():
    await _test_missing_code()


async def test_memory_fallback_when_redis_down():
    await _test_memory_fallback_when_redis_down()


async def test_memory_fallback_expired():
    await _test_memory_fallback_expired()


async def test_memory_fallback_single_use():
    await _test_memory_fallback_single_use()
