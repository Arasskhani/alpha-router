"""Presence lives only in Redis and must fail open.

A fake client keeps these tests hermetic: no Redis, no event-loop plumbing
beyond ``asyncio.run``.
"""

from __future__ import annotations

import asyncio

from app.services import presence_service


class FakeSettings:
    def __init__(self, *, enabled: bool = True, ttl: int = 90) -> None:
        self.presence_enabled = enabled
        self.presence_ttl_seconds = ttl


class FakeRedis:
    def __init__(self, *, values: dict[str, str] | None = None, fail: bool = False) -> None:
        self.store: dict[str, str] = dict(values or {})
        self.ttls: dict[str, int | None] = {}
        self.fail = fail
        self.mget_calls = 0
        self.closed = False

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.fail:
            raise RuntimeError("redis down")
        self.store[key] = value
        self.ttls[key] = ex

    async def delete(self, key: str) -> None:
        if self.fail:
            raise RuntimeError("redis down")
        self.store.pop(key, None)

    async def mget(self, keys: list[str]) -> list[str | None]:
        self.mget_calls += 1
        if self.fail:
            raise RuntimeError("redis down")
        return [self.store.get(key) for key in keys]

    async def aclose(self) -> None:
        self.closed = True


def _install(monkeypatch, client: FakeRedis | None, *, settings: FakeSettings | None = None):
    monkeypatch.setattr(presence_service, "get_settings", lambda: settings or FakeSettings())
    monkeypatch.setattr(presence_service, "_client", lambda: client)
    return client


def test_mark_online_sets_key_with_ttl_and_keeps_the_shared_client_open(monkeypatch) -> None:
    client = _install(monkeypatch, FakeRedis())

    assert asyncio.run(presence_service.mark_online(7)) is True
    assert client.store == {"presence:user:7": "1"}
    assert client.ttls["presence:user:7"] == 90
    # The client is the per-process singleton now; closing it here would
    # tear down the pool for every other caller.
    assert client.closed is False


def test_ttl_is_floored_so_a_tab_cannot_expire_between_pings(monkeypatch) -> None:
    _install(monkeypatch, FakeRedis(), settings=FakeSettings(ttl=1))

    assert presence_service.presence_ttl_seconds() == 30


def test_clear_presence_removes_the_key(monkeypatch) -> None:
    client = _install(monkeypatch, FakeRedis(values={"presence:user:3": "1"}))

    asyncio.run(presence_service.clear_presence(3))

    assert client.store == {}


def test_online_user_ids_uses_one_mget_and_dedupes_ids(monkeypatch) -> None:
    client = _install(
        monkeypatch,
        FakeRedis(values={"presence:user:1": "1", "presence:user:3": "1"}),
    )

    resolved = asyncio.run(presence_service.online_user_ids([1, 2, 3, 1]))

    assert resolved == {1, 3}
    assert client.mget_calls == 1


def test_online_user_ids_is_unknown_when_redis_is_down(monkeypatch) -> None:
    _install(monkeypatch, FakeRedis(fail=True))

    # None (unknown), never an empty set: callers must not mark everyone offline.
    assert asyncio.run(presence_service.online_user_ids([1, 2])) is None


def test_online_user_ids_is_unknown_when_no_client_can_be_built(monkeypatch) -> None:
    _install(monkeypatch, None)

    assert asyncio.run(presence_service.online_user_ids([1])) is None


def test_presence_disabled_reports_unknown_and_skips_writes(monkeypatch) -> None:
    client = _install(monkeypatch, FakeRedis(), settings=FakeSettings(enabled=False))

    assert asyncio.run(presence_service.online_user_ids([1])) is None
    assert asyncio.run(presence_service.mark_online(1)) is False
    assert client.store == {}
    assert client.mget_calls == 0


def test_empty_id_list_never_touches_redis(monkeypatch) -> None:
    client = _install(monkeypatch, FakeRedis())

    assert asyncio.run(presence_service.online_user_ids([])) == set()
    assert client.mget_calls == 0


def test_lookup_is_capped(monkeypatch) -> None:
    ids = list(range(1, presence_service.MAX_PRESENCE_LOOKUP + 50))
    client = _install(
        monkeypatch,
        FakeRedis(values={presence_service.presence_key(uid): "1" for uid in ids}),
    )

    resolved = asyncio.run(presence_service.online_user_ids(ids))

    assert resolved is not None
    assert len(resolved) == presence_service.MAX_PRESENCE_LOOKUP
    assert client.mget_calls == 1
