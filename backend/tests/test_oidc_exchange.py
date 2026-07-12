"""Phase 6: one-time exchange code is single-use and short-lived.

Uses a fake async Redis client to avoid a live Redis dependency in unit tests.
"""

import asyncio
from unittest.mock import patch

from app.services import oidc_exchange


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
                self.ops: list = []

            def get(self, key):
                self.ops.append(("get", key))
                return self

            def delete(self, key):
                self.ops.append(("delete", key))
                return self

            async def execute(self):
                results = []
                for kind, key in self.ops:
                    if kind == "get":
                        results.append(outer.store.get(key))
                    else:
                        results.append(outer.store.pop(key, None) is not None)
                return results

        return _Pipe()

    async def aclose(self):
        pass


def test_store_and_consume_roundtrip():
    fake = FakeRedis()

    async def run():
        with patch("app.services.oidc_exchange._client", return_value=fake):
            code = oidc_exchange.generate_code()
            await oidc_exchange.store_token(code, {"token": "JWT-1", "role": "user"})
            payload = await oidc_exchange.consume_code(code)
        assert payload == {"token": "JWT-1", "role": "user"}

    asyncio.run(run())


def test_consume_is_single_use():
    fake = FakeRedis()

    async def run():
        with patch("app.services.oidc_exchange._client", return_value=fake):
            code = oidc_exchange.generate_code()
            await oidc_exchange.store_token(code, {"token": "JWT-2"})
            first = await oidc_exchange.consume_code(code)
            second = await oidc_exchange.consume_code(code)
        assert first is not None
        assert second is None  # consumed already

    asyncio.run(run())


def test_consume_unknown_code_returns_none():
    fake = FakeRedis()

    async def run():
        with patch("app.services.oidc_exchange._client", return_value=fake):
            assert await oidc_exchange.consume_code("nonexistent") is None
            assert await oidc_exchange.consume_code("") is None

    asyncio.run(run())
