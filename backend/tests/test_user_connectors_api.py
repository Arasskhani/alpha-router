"""Security tests for the Connectors API (Step 2).

Covers IDOR, CSRF, secret leakage, unknown-provider rejection, and OAuth
state replay / cross-user guards. Uses a minimal FastAPI app with the
connectors router and a dependency override for ``require_active_user`` so
we can switch the "current user" between requests.
"""

from __future__ import annotations

import asyncio
import datetime
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.api.user_connectors as uc
from app.database import Base
from app.models.user import User
from app.models.user_connector import UserConnector
from app.services.csrf_protection import CsrfProtectionMiddleware
from app.services.secret_crypto import encrypt_secret


def _make_app(factory, current_user_provider):
    app = FastAPI()
    app.add_middleware(CsrfProtectionMiddleware)
    app.include_router(uc.router)

    async def _get_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[uc.get_db] = _get_db
    app.dependency_overrides[uc.require_active_user] = current_user_provider
    return app


def _setup_env(monkeypatch):
    monkeypatch.setenv("ENABLE_CSRF", "true")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("FRONTEND_URL", "http://127.0.0.1:8080")
    from app.config import get_settings

    get_settings.cache_clear()
    uc.get_settings.cache_clear()


class _FakeUser:
    def __init__(self, id, username="alice"):
        self.id = id
        self.username = username


@pytest.fixture
def factory_and_users():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(User(username="alice", role="user", auth_provider="local", hashed_password="x"))
            db.add(User(username="bob", role="user", auth_provider="local", hashed_password="x"))
            await db.commit()
            alice = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
            bob = (await db.execute(select(User).where(User.username == "bob"))).scalar_one()
            db.add(
                UserConnector(
                    user_id=bob.id,
                    provider_id="gmail",
                    client_id_encrypted=encrypt_secret("bob-cid"),
                    client_secret_encrypted=encrypt_secret("bob-csec"),
                    access_token_encrypted=encrypt_secret("bob-atok"),
                    refresh_token_encrypted=encrypt_secret("bob-rtok"),
                    expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=1),
                    scope="gmail.readonly gmail.compose",
                )
            )
            await db.commit()
            return alice.id, bob.id

    alice_id, bob_id = asyncio.run(_seed())
    yield engine, factory, alice_id, bob_id
    asyncio.run(engine.dispose())


def test_list_never_leaks_secrets(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app)
    res = client.get("/api/user/connectors")
    assert res.status_code == 200
    body = res.json()
    text = res.text
    # No secret material ever appears in the response.
    for forbidden in ("client_secret", "access_token", "refresh_token", "bob-csec", "bob-atok", "bob-rtok"):
        assert forbidden not in text, forbidden
    for c in body["connectors"]:
        assert "client_id" not in c
        assert "access_token" not in c
        assert "client_secret" not in c


def test_idor_list_does_not_expose_other_users_rows(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app)
    res = client.get("/api/user/connectors")
    assert res.status_code == 200
    # Alice has no connections; bob's gmail must not appear as connected.
    gmail = next(c for c in res.json()["connectors"] if c["provider_id"] == "gmail")
    assert gmail["connected"] is False


def test_idor_delete_other_users_row_returns_404(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app)
    client.cookies.set("alpha_router_session", "jwt")
    client.cookies.set("alpha_router_csrf", "tok")
    res = client.delete(
        "/api/user/connectors/gmail",
        headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
    )
    # Alice has no gmail row -> 404, and bob's row stays untouched.
    assert res.status_code == 404

    async def _check():
        async with factory() as db:
            bob_row = (
                await db.execute(select(UserConnector).where(UserConnector.user_id == _bob_id))
            ).scalar_one()
            assert bob_row.revoked_at is None
            assert bob_row.access_token_encrypted is not None

    asyncio.run(_check())


def test_csrf_blocks_mutation_without_header(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app)
    client.cookies.set("alpha_router_session", "jwt")
    client.cookies.set("alpha_router_csrf", "tok")
    # No X-CSRF-Token header -> 403.
    res = client.post(
        "/api/user/connectors/gmail/credentials",
        json={"client_id": "cid", "client_secret": "csec"},
        headers={"Origin": "http://127.0.0.1:8080"},
    )
    assert res.status_code == 403
    # With matching header -> accepted.
    res2 = client.post(
        "/api/user/connectors/gmail/credentials",
        json={"client_id": "cid", "client_secret": "csec"},
        headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
    )
    assert res2.status_code == 200


def test_unknown_provider_rejected(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app)
    client.cookies.set("alpha_router_session", "jwt")
    client.cookies.set("alpha_router_csrf", "tok")
    res = client.post(
        "/api/user/connectors/evil/credentials",
        json={"client_id": "cid", "client_secret": "csec"},
        headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
    )
    assert res.status_code == 404


def test_begin_requires_stored_credentials(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app)
    res = client.get("/api/user/connectors/gmail/begin")
    assert res.status_code == 400


def test_callback_rejects_missing_params(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app, follow_redirects=False)
    res = client.get("/api/user/connectors/oauth/callback")
    assert res.status_code in (307, 302)
    assert "connectors=error" in res.headers["location"]


def test_callback_rejects_invalid_state(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app, follow_redirects=False)
    res = client.get("/api/user/connectors/oauth/callback?code=x&state=not-a-jwt")
    assert res.status_code in (307, 302)
    assert "reason=invalid_state" in res.headers["location"]


def test_callback_rejects_state_cookie_mismatch(monkeypatch, factory_and_users):
    _setup_env(monkeypatch)
    _engine, factory, alice_id, _bob_id = factory_and_users
    user = _FakeUser(alice_id)
    app = _make_app(factory, lambda: user)
    client = TestClient(app, follow_redirects=False)
    from jose import jwt as jose_jwt
    from app.config import get_settings

    settings = get_settings()
    state = jose_jwt.encode(
        {"sub": str(alice_id), "provider": "gmail", "nonce": "evil-nonce",
         "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=60)},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client.cookies.set("alpha_router_connector_state", "different-nonce")
    res = client.get(f"/api/user/connectors/oauth/callback?code=x&state={state}")
    assert "reason=state_cookie_mismatch" in res.headers["location"]
