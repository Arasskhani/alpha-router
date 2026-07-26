"""Tests for Phase 4 social providers (Step 9)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.user_connectors as uc
from app.config import get_settings
from app.database import Base
from app.models.user import User
from app.models.user_connector import UserConnector
from app.services import connector_registry
from app.services.csrf_protection import CsrfProtectionMiddleware
from app.services.secret_crypto import decrypt_secret


def _setup_env(monkeypatch):
    monkeypatch.setenv("ENABLE_CSRF", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("FRONTEND_URL", "http://127.0.0.1:8080")
    get_settings.cache_clear()
    uc.get_settings.cache_clear()


class _FakeUser:
    def __init__(self, id, username="alice"):
        self.id = id
        self.username = username


def _fixture():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(User(username="alice", role="user", auth_provider="local", hashed_password="x"))
            await db.commit()
            alice = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
            return alice.id

    alice_id = asyncio.run(_seed())
    return engine, factory, alice_id


def _make_app(factory, user):
    app = FastAPI()
    app.add_middleware(CsrfProtectionMiddleware)
    app.include_router(uc.router)

    async def _get_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[uc.get_db] = _get_db
    app.dependency_overrides[uc.require_active_user] = lambda: user
    return app


def test_social_providers_registered_as_api_key():
    for pid in ("instagram", "linkedin", "twitter"):
        spec = connector_registry.get_connector(pid)
        assert spec is not None, pid
        assert spec.auth_type == "api_key", pid


def test_social_api_key_stored_encrypted_not_shown(monkeypatch):
    _setup_env(monkeypatch)
    engine, factory, alice_id = _fixture()
    user = _FakeUser(alice_id)
    app = _make_app(factory, user)
    client = TestClient(app)
    client.cookies.set("alpha_router_session", "jwt")
    client.cookies.set("alpha_router_csrf", "tok")

    res = client.post(
        "/api/user/connectors/twitter/connect-api-key",
        json={"api_key": "x-twitter-secret"},
        headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
    )
    assert res.status_code == 200

    # The list endpoint must never expose the api key.
    listing = client.get("/api/user/connectors").json()
    twitter = next(c for c in listing["connectors"] if c["provider_id"] == "twitter")
    assert twitter["connected"] is True
    assert "api_key" not in twitter
    assert "access_token" not in twitter
    assert "x-twitter-secret" not in client.get("/api/user/connectors").text

    # Stored encrypted in DB.
    async def _verify():
        async with factory() as db:
            row = (
                await db.execute(
                    select(UserConnector).where(
                        UserConnector.user_id == alice_id,
                        UserConnector.provider_id == "twitter",
                    )
                )
            ).scalar_one()
            assert row.access_token_encrypted != "x-twitter-secret"
            assert decrypt_secret(row.access_token_encrypted) == "x-twitter-secret"

    asyncio.run(_verify())
    asyncio.run(engine.dispose())


def test_social_disconnect_clears_key(monkeypatch):
    _setup_env(monkeypatch)
    engine, factory, alice_id = _fixture()
    user = _FakeUser(alice_id)
    app = _make_app(factory, user)
    client = TestClient(app)
    client.cookies.set("alpha_router_session", "jwt")
    client.cookies.set("alpha_router_csrf", "tok")

    client.post(
        "/api/user/connectors/linkedin/connect-api-key",
        json={"api_key": "li-key"},
        headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
    )
    res = client.delete(
        "/api/user/connectors/linkedin",
        headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
    )
    assert res.status_code == 200

    async def _verify():
        async with factory() as db:
            row = (
                await db.execute(
                    select(UserConnector).where(
                        UserConnector.user_id == alice_id,
                        UserConnector.provider_id == "linkedin",
                    )
                )
            ).scalar_one()
            assert row.revoked_at is not None
            assert row.access_token_encrypted is None

    asyncio.run(_verify())
    asyncio.run(engine.dispose())
