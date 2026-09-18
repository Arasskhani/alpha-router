"""The endpoints that spend money are bounded per minute.

The limiter existed and was wired to login and to the chat list and search - the
cheap reads. Chat completions, the OpenAI-compatible gateway, image generation
and speech had nothing, so a leaked API key or a runaway client was bounded only
by the monthly budget, which is discovered after the money is gone.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from app.services import rate_limit as rl


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, float]] = {}

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self) -> None:
                self._ops: list = []

            def zadd(self, key, mapping):
                self._ops.append(("zadd", key, mapping))
                return self

            def zremrangebyscore(self, key, lo, hi):
                self._ops.append(("zrem", key, lo, hi))
                return self

            def zcard(self, key):
                self._ops.append(("zcard", key))
                return self

            def expire(self, key, seconds):
                self._ops.append(("expire", key, seconds))
                return self

            async def execute(self):
                results = []
                for op in self._ops:
                    if op[0] == "zadd":
                        outer._store.setdefault(op[1], {}).update(op[2])
                        results.append(1)
                    elif op[0] == "zrem":
                        bucket = outer._store.setdefault(op[1], {})
                        for member, score in list(bucket.items()):
                            if op[2] <= score <= op[3]:
                                del bucket[member]
                        results.append(1)
                    elif op[0] == "zcard":
                        results.append(len(outer._store.get(op[1], {})))
                    else:
                        results.append(1)
                return results

        return _Pipe()

    async def aclose(self):
        return None


def test_the_subject_is_the_key_when_there_is_one():
    """A gateway key's spend belongs to the key, not to whoever owns it."""

    assert rl.generation_subject(user_id=7, api_key_id=42) == "key:42"
    assert rl.generation_subject(user_id=7, api_key_id=None) == "user:7"
    assert rl.generation_subject(user_id=None, api_key_id=None) == "anonymous"


async def test_a_runaway_caller_is_stopped(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(rl, "_client", lambda: fake)

    for _ in range(5):
        await rl.check_generation_rate_limit("image", "user:1", 5)
    with pytest.raises(HTTPException) as exc:
        await rl.check_generation_rate_limit("image", "user:1", 5)
    assert exc.value.status_code == 429


async def test_callers_do_not_share_a_budget(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(rl, "_client", lambda: fake)

    for _ in range(5):
        await rl.check_generation_rate_limit("image", "user:1", 5)
    await rl.check_generation_rate_limit("image", "user:2", 5)


async def test_the_kinds_have_separate_windows(monkeypatch):
    """Generating images should not use up someone's chat allowance."""

    fake = _FakeRedis()
    monkeypatch.setattr(rl, "_client", lambda: fake)

    for _ in range(5):
        await rl.check_generation_rate_limit("image", "user:1", 5)
    await rl.check_generation_rate_limit("chat", "user:1", 5)


async def test_a_redis_outage_does_not_block_work(monkeypatch):
    """Unlike login: the budget reservation is still the hard ceiling underneath."""

    class _Broken:
        def pipeline(self):
            raise RuntimeError("redis down")

        async def aclose(self):
            return None

    monkeypatch.setattr(rl, "_client", lambda: _Broken())
    rl._buckets.clear()
    await rl.check_generation_rate_limit("chat", "user:9", 5)


def test_every_paid_endpoint_is_wired():
    from app.api import images, speech
    from app.services import proxy_service

    assert "check_generation_rate_limit" in inspect.getsource(proxy_service.preflight_stream_chat), (
        "chat completions and the /v1 gateway both go through preflight"
    )
    assert "check_generation_rate_limit" in inspect.getsource(images.generate_image)
    assert "check_generation_rate_limit" in inspect.getsource(speech.generate_speech)
