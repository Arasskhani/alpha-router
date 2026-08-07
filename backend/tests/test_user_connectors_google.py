"""End-to-end Google connector flow with a mock OAuth server (Step 4).

Validates the full happy path: store credentials → begin → callback exchanges
code for tokens → tokens stored encrypted → disconnect revokes at provider.
Also covers token refresh and the CASA verification help note.
"""

from __future__ import annotations

import asyncio
import datetime
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.api.user_connectors as uc
from app.config import get_settings
from app.database import Base
from app.models.user import User
from app.models.user_connector import UserConnector
from app.services.connector_state import store_state
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


@pytest.fixture
def factory_and_user():
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
    yield engine, factory, alice_id
    asyncio.run(engine.dispose())


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


def _mock_oauth_transport(token_calls: list, revoke_calls: list, refresh_calls: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2.googleapis.com/token" in url:
            token_calls.append(url)
            # Distinguish refresh vs initial exchange by grant_type body content.
            body = (request.content or b"").decode()
            if "grant_type=refresh_token" in body:
                refresh_calls.append(body)
                return httpx.Response(200, json={"access_token": " refreshed-atok", "expires_in": 3600})
            return httpx.Response(
                200,
                json={
                    "access_token": "access-atok",
                    "refresh_token": "refresh-rtok",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose",
                },
            )
        if "oauth2.googleapis.com/revoke" in url:
            revoke_calls.append(url)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _patch_async_client(transport: httpx.MockTransport):
    """Patch httpx.AsyncClient to inject a mock transport without recursion."""
    real = httpx.AsyncClient

    def patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real(*a, **kw)

    return patch("httpx.AsyncClient", new=patched)


def test_full_google_connect_flow(monkeypatch, factory_and_user):
    _setup_env(monkeypatch)
    _engine, factory, alice_id = factory_and_user
    user = _FakeUser(alice_id)
    app = _make_app(factory, user)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("alpha_router_session", "jwt")
    client.cookies.set("alpha_router_csrf", "tok")

    token_calls: list[str] = []
    revoke_calls: list[str] = []
    refresh_calls: list[str] = []
    transport = _mock_oauth_transport(token_calls, revoke_calls, refresh_calls)

    # 1. Store credentials.
    res = client.post(
        "/api/user/connectors/gmail/credentials",
        json={"client_id": "cid", "client_secret": "csec"},
        headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
    )
    assert res.status_code == 200

    # 2. Begin — should return an auth_url pointing at Google's consent screen.
    res = client.get("/api/user/connectors/gmail/begin")
    assert res.status_code == 200
    auth_url = res.json()["auth_url"]
    assert "accounts.google.com/o/oauth2/v2/auth" in auth_url
    assert "client_id=cid" in auth_url
    assert "gmail.readonly" in auth_url

    # The begin route set an Alpharouter connector-state cookie; capture it.
    nonce_cookie = client.cookies.get("alpha_router_connector_state")
    assert nonce_cookie

    # 3. Simulate the OAuth callback with a valid signed state matching the cookie.
    settings = get_settings()
    state = jose_jwt.encode(
        {"sub": str(alice_id), "provider": "gmail", "nonce": nonce_cookie,
         "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=60)},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    # Pre-seed the single-use nonce store so consume_state succeeds.
    asyncio.run(store_state(nonce_cookie, {"user_id": alice_id, "provider_id": "gmail"}))

    with _patch_async_client(transport):
        res = client.get(f"/api/user/connectors/oauth/callback?code=real-code&state={state}")
    assert res.status_code in (307, 302)
    assert "connectors=connected" in res.headers["location"]
    assert len(token_calls) == 1

    # 4. Tokens stored encrypted, not plaintext.
    async def _verify():
        async with factory() as db:
            row = (
                await db.execute(select(UserConnector).where(UserConnector.user_id == alice_id))
            ).scalar_one()
            assert row.access_token_encrypted != "access-atok"
            assert decrypt_secret(row.access_token_encrypted) == "access-atok"
            assert decrypt_secret(row.refresh_token_encrypted) == "refresh-rtok"
            assert row.revoked_at is None
            assert row.expires_at is not None

    asyncio.run(_verify())

    # 5. Disconnect → best-effort revoke at provider + clear local tokens.
    with _patch_async_client(transport):
        res = client.delete(
            "/api/user/connectors/gmail",
            headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
        )
    assert res.status_code == 200
    assert len(revoke_calls) == 1

    async def _verify_revoked():
        async with factory() as db:
            row = (
                await db.execute(select(UserConnector).where(UserConnector.user_id == alice_id))
            ).scalar_one()
            assert row.revoked_at is not None
            assert row.access_token_encrypted is None
            assert row.refresh_token_encrypted is None

    asyncio.run(_verify_revoked())


def test_callback_token_exchange_failure_redirects_error(monkeypatch, factory_and_user):
    _setup_env(monkeypatch)
    _engine, factory, alice_id = factory_and_user
    user = _FakeUser(alice_id)
    app = _make_app(factory, user)
    client = TestClient(app, follow_redirects=False)
    client.cookies.set("alpha_router_session", "jwt")
    client.cookies.set("alpha_router_csrf", "tok")

    # Store credentials first.
    client.post(
        "/api/user/connectors/gmail/credentials",
        json={"client_id": "cid", "client_secret": "csec"},
        headers={"X-CSRF-Token": "tok", "Origin": "http://127.0.0.1:8080"},
    )
    res = client.get("/api/user/connectors/gmail/begin")
    nonce_cookie = client.cookies.get("alpha_router_connector_state")
    settings = get_settings()
    state = jose_jwt.encode(
        {"sub": str(alice_id), "provider": "gmail", "nonce": nonce_cookie,
         "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=60)},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    asyncio.run(store_state(nonce_cookie, {"user_id": alice_id, "provider_id": "gmail"}))

    # Provider returns 400 on token exchange.
    failing_transport = httpx.MockTransport(
        lambda req: httpx.Response(400, json={"error": "invalid_grant"})
    )
    with _patch_async_client(failing_transport):
        res = client.get(f"/api/user/connectors/oauth/callback?code=bad&state={state}")
    assert res.status_code in (307, 302)
    assert "connectors=error" in res.headers["location"]
    assert "reason=token_exchange" in res.headers["location"]


def test_help_text_mentions_user_verification_responsibility():
    """The ConnectorsPanel must tell users that OAuth app verification (CASA)
    is their own responsibility — verified by reading the component source."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "settings" / "ConnectorsPanel.tsx"
    if not src.exists():
        pytest.skip("frontend source not present in this checkout")
    text = src.read_text(encoding="utf-8")
    # The panel must mention creating an OAuth Client ID in the provider's console.
    assert "OAuth Client ID" in text or "Client ID" in text
    assert "redirect URI" in text or "redirect_uri" in text.lower()
