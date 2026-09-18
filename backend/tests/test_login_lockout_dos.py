"""One host cannot lock a known administrator out of logging in.

``check_login_rate_limit`` is called before the user is looked up, every attempt
counts, and nothing resets the window on success. With the window keyed on the
username alone, anyone who knows an administrator's name - ``alpharouter`` by
default - could send 21 junk attempts a minute from one address and the real
administrator got 429 indefinitely. That is under the 60/min per-IP ceiling, so
the attacker never limited themselves.

A product that deliberately has no account lockout should not have a lockout
primitive hiding in its rate limiter.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services import rate_limit as rl


class _FakeRedis:
    """Enough of the async Redis surface for the sliding window."""

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


async def _exhaust(username: str, ip: str, attempts: int) -> None:
    for _ in range(attempts):
        await rl.check_login_rate_limit(username, ip)


async def test_one_host_cannot_lock_an_admin_out_from_elsewhere(monkeypatch):
    fake = _FakeRedis()  # one instance: _client() is called per request
    monkeypatch.setattr(rl, "_client", lambda: fake)

    # The attacker burns the whole per-username budget from their own address.
    with pytest.raises(HTTPException) as exc:
        await _exhaust("alpharouter", "203.0.113.5", rl._LOGIN_USER_LIMIT + 1)
    assert exc.value.status_code == 429

    # The real administrator, signing in from anywhere else, is unaffected.
    await rl.check_login_rate_limit("alpharouter", "198.51.100.7")


async def test_guessing_one_account_from_one_host_is_still_limited(monkeypatch):
    fake = _FakeRedis()  # one instance: _client() is called per request
    monkeypatch.setattr(rl, "_client", lambda: fake)

    with pytest.raises(HTTPException) as exc:
        await _exhaust("victim", "203.0.113.5", rl._LOGIN_USER_LIMIT + 1)
    assert exc.value.status_code == 429


async def test_one_host_spraying_many_accounts_still_hits_the_ip_ceiling(monkeypatch):
    fake = _FakeRedis()  # one instance: _client() is called per request
    monkeypatch.setattr(rl, "_client", lambda: fake)

    with pytest.raises(HTTPException) as exc:
        for index in range(rl._LOGIN_IP_LIMIT + 2):
            await rl.check_login_rate_limit(f"user{index}", "203.0.113.9")
    assert exc.value.status_code == 429
