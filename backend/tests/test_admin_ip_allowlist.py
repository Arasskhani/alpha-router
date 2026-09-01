"""Admin IP allowlist validation, lockout guard, and middleware modes."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import app.models  # noqa: F401
from app.database import Base
from app.services.admin_ip_allowlist_service import (
    AllowlistError,
    add_entry,
    delete_entry,
    get_restriction_state,
    invalidate_restriction_cache,
    ip_matches_allowlist,
    normalize_cidr,
    set_restriction_mode,
    update_entry,
)
from app.services.admin_ip_guard import AdminIpGuardMiddleware, path_is_admin_surface
from app.services.observability import reset


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_restriction_cache()
    yield
    invalidate_restriction_cache()


def test_normalize_cidr_rejects_wildcard_and_accepts_hosts():
    assert normalize_cidr("10.1.2.3") == "10.1.2.3/32"
    with pytest.raises(AllowlistError):
        normalize_cidr("0.0.0.0/0")
    with pytest.raises(AllowlistError):
        normalize_cidr("not-an-ip")


def test_ip_matches_allowlist_and_loopback():
    entries = [{"cidr": "10.0.0.0/8", "enabled": True}]
    assert ip_matches_allowlist("10.9.8.7", entries, allow_loopback=False)
    assert not ip_matches_allowlist("11.0.0.1", entries, allow_loopback=False)
    assert ip_matches_allowlist("127.0.0.1", entries, allow_loopback=True)
    assert not ip_matches_allowlist("127.0.0.1", entries, allow_loopback=False)


def test_path_is_admin_surface():
    assert path_is_admin_surface("/admin")
    assert path_is_admin_surface("/admin/security-settings")
    assert path_is_admin_surface("/api/admin/smtp")
    assert not path_is_admin_surface("/api/auth/login")
    assert not path_is_admin_surface("/health")
    assert not path_is_admin_surface("/app/chat")


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


def test_enforce_requires_current_ip():
    async def _run():
        engine, factory = await _session()
        async with factory() as db:
            await add_entry(db, cidr="10.0.0.0/8", label="corp", created_by_user_id=None)
            await db.commit()
        async with factory() as db:
            with pytest.raises(AllowlistError, match="current IP"):
                await set_restriction_mode(db, "enforce", client_ip="203.0.113.9")
            state = await set_restriction_mode(db, "enforce", client_ip="10.1.2.3")
            assert state.mode == "enforce"
        await engine.dispose()

    asyncio.run(_run())


def test_middleware_monitor_does_not_block(monkeypatch):
    reset()

    async def _seed():
        engine, factory = await _session()
        async with factory() as db:
            await add_entry(db, cidr="10.0.0.0/8", created_by_user_id=None)
            await set_restriction_mode(db, "monitor", client_ip="10.0.0.1", allow_loopback=False)
            await db.commit()
        return engine, factory

    engine, factory = asyncio.run(_seed())
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", factory)
    app = FastAPI()
    app.add_middleware(AdminIpGuardMiddleware)

    @app.get("/admin")
    def _admin():
        return PlainTextResponse("ok")

    @app.get("/health")
    def _health():
        return PlainTextResponse("ok")

    client = TestClient(app)
    denied = client.get("/admin")
    assert denied.status_code == 200
    assert client.get("/health").status_code == 200
    asyncio.run(engine.dispose())


def test_middleware_enforce_blocks_admin_and_allows_health(monkeypatch):
    async def _seed():
        engine, factory = await _session()
        async with factory() as db:
            await add_entry(db, cidr="10.0.0.0/8", created_by_user_id=None)
            await set_restriction_mode(db, "enforce", client_ip="10.0.0.1", allow_loopback=False)
            await db.commit()
        return engine, factory

    engine, factory = asyncio.run(_seed())
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", factory)
    app = FastAPI()
    app.add_middleware(AdminIpGuardMiddleware)

    @app.get("/admin")
    def _admin():
        return PlainTextResponse("ok")

    @app.get("/api/admin/smtp")
    def _smtp():
        return {"ok": True}

    @app.get("/health")
    def _health():
        return PlainTextResponse("ok")

    client = TestClient(app)
    assert client.get("/admin").status_code == 403
    assert client.get("/api/admin/smtp").status_code == 403
    assert client.get("/health").status_code == 200
    asyncio.run(engine.dispose())


def test_delete_and_disable_refuse_self_lockout():
    async def _run():
        engine, factory = await _session()
        async with factory() as db:
            entry = await add_entry(db, cidr="10.1.2.3", created_by_user_id=None)
            await set_restriction_mode(db, "enforce", client_ip="10.1.2.3")
            await db.commit()
        async with factory() as db:
            with pytest.raises(AllowlistError, match="lock out"):
                await delete_entry(db, entry["id"], client_ip="10.1.2.3")
            with pytest.raises(AllowlistError, match="lock out"):
                await update_entry(db, entry["id"], enabled=False, client_ip="10.1.2.3")
            await add_entry(db, cidr="10.9.8.7", created_by_user_id=None)
            await delete_entry(db, entry["id"], client_ip="10.9.8.7")
        await engine.dispose()

    asyncio.run(_run())


def test_middleware_uses_stale_enforce_when_db_refresh_fails(monkeypatch):
    async def _seed():
        engine, factory = await _session()
        async with factory() as db:
            await add_entry(db, cidr="10.0.0.0/8", created_by_user_id=None)
            await set_restriction_mode(db, "enforce", client_ip="10.0.0.1", allow_loopback=False)
            await db.commit()
            await get_restriction_state(db)
        return engine, factory

    engine, factory = asyncio.run(_seed())
    import time

    import app.services.admin_ip_allowlist_service as allowlist_mod

    cached_at, state = allowlist_mod._cache
    allowlist_mod._cache = (time.monotonic() - 1000, state)

    class _Broken:
        def __call__(self):
            return self

        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", _Broken())
    app = FastAPI()
    app.add_middleware(AdminIpGuardMiddleware)

    @app.get("/admin")
    def _admin():
        return PlainTextResponse("ok")

    client = TestClient(app)
    assert client.get("/admin").status_code == 403
    asyncio.run(engine.dispose())


def test_get_restriction_state_round_trip():
    async def _run():
        engine, factory = await _session()
        async with factory() as db:
            await add_entry(db, cidr="192.168.1.10", created_by_user_id=1)
            state = await get_restriction_state(db)
            assert state.mode == "off"
            assert state.entries[0]["cidr"] == "192.168.1.10/32"
        await engine.dispose()

    asyncio.run(_run())
