"""Extension access tokens in the authentication dependency: what they may call, and nothing else."""

from __future__ import annotations

import asyncio
import datetime

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from sqlalchemy import update

from app.api import deps
from app.api.deps import EXTENSION_SCOPE, EXTENSION_UNGATED, get_bearer_token, get_current_user
from app.config import get_settings
from app.core.security import create_access_token
from app.database import get_db
from app.main import app as fastapi_app
from app.models.extension import ExtensionSession
from app.models.user import User
from app.services import extension_tokens
from app.services.chat_tool_access_service import set_chat_tool_access
from app.services.extension_tokens import create_session, revoke_session

CSRF = "csrf-token"
#: Scope entries whose endpoints later steps of the extension work add.
NOT_BUILT_YET: set[tuple[str, str]] = set()


@pytest.fixture(autouse=True)
def _own_sessions(monkeypatch, session_factory):
    monkeypatch.setattr(extension_tokens, "AsyncSessionLocal", session_factory)
    # The admin IP guard reads its allowlist in a session of its own.
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


async def _connect(db, user) -> extension_tokens.TokenPair:
    pair = await create_session(db, user=user, device_name="Chrome", user_agent="UA", ip="10.0.0.5")
    await db.commit()
    return pair


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _probe_app(session_factory) -> FastAPI:
    """Every scope entry plus a few that are not, each answering who called."""
    probe = FastAPI()

    async def whoami(request: Request, user: User = Depends(get_current_user)) -> dict:
        return {"user": user.username, "session": getattr(request.state, "extension_session_id", None)}

    async def raw_token(token: str = Depends(get_bearer_token)) -> dict:
        return {"token": token}

    for method, path in sorted(EXTENSION_SCOPE):
        probe.add_api_route(path, whoami, methods=[method])
    probe.add_api_route("/api/user/chats/sessions/{session_id}", whoami, methods=["DELETE"])
    probe.add_api_route("/api/admin/users", whoami, methods=["GET"])
    probe.add_api_route("/api/probe/token", raw_token, methods=["GET"])

    async def _get_db():
        async with session_factory() as session:
            yield session
            await session.commit()

    probe.dependency_overrides[get_db] = _get_db
    return probe


@pytest.fixture
async def probe(session_factory):
    transport = httpx.ASGITransport(app=_probe_app(session_factory))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _concrete(path: str) -> str:
    return path.replace("{session_id}", "chat-1")


class TestTheScope:
    async def test_every_entry_names_a_real_endpoint(self):
        routes = {
            (method.upper(), path)
            for path, operations in fastapi_app.openapi()["paths"].items()
            for method in operations
        }
        missing = (EXTENSION_SCOPE - NOT_BUILT_YET) - routes
        assert not missing, missing
        assert not (NOT_BUILT_YET & routes), "an endpoint exists now: drop it from NOT_BUILT_YET"

    async def test_every_real_endpoint_in_it_takes_the_token(self, client, db_session, user):
        pair = await _connect(db_session, user)
        # Last: it ends the session.
        calls = sorted(EXTENSION_SCOPE - NOT_BUILT_YET - {("POST", "/api/extension/revoke")})
        for method, path in [*calls, ("POST", "/api/extension/revoke")]:
            resp = await client.request(method, _concrete(path), headers=_bearer(pair.access_token), json={})
            body = resp.json() if resp.headers.get("content-type") == "application/json" else None
            detail = body.get("detail") if isinstance(body, dict) else None
            refused = resp.status_code == 401 or (isinstance(detail, dict) and "code" in detail)
            assert not refused, (method, path, resp.status_code, resp.text)

    async def test_every_entry_lets_the_token_through(self, probe, db_session, user):
        pair = await _connect(db_session, user)
        for method, path in sorted(EXTENSION_SCOPE):
            resp = await probe.request(method, _concrete(path), headers=_bearer(pair.access_token))
            assert resp.status_code == 200, (method, path, resp.text)
            assert resp.json() == {"user": user.username, "session": pair.session_id}

    @pytest.mark.parametrize(
        ("method", "path"), [("DELETE", "/api/user/chats/sessions/chat-1"), ("GET", "/api/admin/users")]
    )
    async def test_anything_else_is_refused(self, probe, db_session, user, method, path):
        pair = await _connect(db_session, user)
        resp = await probe.request(method, path, headers=_bearer(pair.access_token))
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "extension_scope"

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/extension/info"),
            ("GET", "/api/extension/download"),
            ("GET", "/api/user/chats"),
            ("GET", "/api/user/api-keys/list"),
            ("POST", "/api/user/api-keys"),
            ("GET", "/api/user/chat-sessions/chat-1/messages"),
            ("POST", "/api/user/settings/password"),
            ("GET", "/api/admin/users"),
            ("PUT", "/api/admin/extension/settings"),
            ("DELETE", "/api/user/chats/sessions/chat-1"),
        ],
    )
    async def test_real_endpoints_outside_the_scope_refuse_it(self, client, db_session, user, method, path):
        pair = await _connect(db_session, user)
        resp = await client.request(method, path, headers=_bearer(pair.access_token), json={})
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "extension_scope"

    async def test_real_endpoints_inside_it_work(self, client, db_session, user):
        pair = await _connect(db_session, user)
        assert (await client.get("/api/chat/models", headers=_bearer(pair.access_token))).status_code == 200
        # A state-changing call with no cookie and no CSRF header: the token is the credential.
        created = await client.post("/api/user/chats/sessions", headers=_bearer(pair.access_token), json={})
        assert created.status_code == 200, created.text
        assert created.json()["id"]


class TestWithoutARoute:
    async def test_the_scope_fails_closed_when_routing_did_not_name_the_route(self, db_session, user):
        from fastapi import HTTPException
        from starlette.requests import Request as StarletteRequest

        pair = await _connect(db_session, user)
        # A request that reached the dependency with no matched route in its scope.
        request = StarletteRequest({"type": "http", "method": "GET", "path": "/api/chat/models", "headers": []})
        with pytest.raises(HTTPException) as caught:
            await deps._extension_user(request, pair.access_token, db_session)
        assert caught.value.status_code == 403
        assert caught.value.detail["code"] == "extension_scope"


class TestRefusals:
    async def test_an_unknown_token(self, probe):
        resp = await probe.get("/api/chat/models", headers=_bearer(extension_tokens.ACCESS_TOKEN_PREFIX + "nope"))
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "invalid_token"
        assert resp.headers["www-authenticate"] == 'Bearer error="invalid_token"'

    async def test_a_revoked_session(self, probe, db_session, user):
        pair = await _connect(db_session, user)
        await revoke_session(db_session, pair.session_id, reason="user")
        await db_session.commit()
        resp = await probe.get("/api/chat/models", headers=_bearer(pair.access_token))
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "revoked"

    async def test_an_expired_access_token(self, probe, db_session, user):
        pair = await _connect(db_session, user)
        await db_session.execute(
            update(ExtensionSession)
            .where(ExtensionSession.id == pair.session_id)
            .values(access_expires_at=datetime.datetime(2000, 1, 1))
        )
        await db_session.commit()
        resp = await probe.get("/api/chat/models", headers=_bearer(pair.access_token))
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "expired"

    async def test_signing_out_everywhere_disconnects(self, probe, db_session, user):
        pair = await _connect(db_session, user)
        user.token_version = 1
        await db_session.commit()
        resp = await probe.get("/api/chat/models", headers=_bearer(pair.access_token))
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == "revoked"

    async def test_a_disabled_account_can_only_disconnect(self, probe, db_session, user):
        pair = await _connect(db_session, user)
        user.is_active = False
        await db_session.commit()
        refused = await probe.post("/api/chat/completions", headers=_bearer(pair.access_token))
        assert refused.status_code == 403
        assert refused.json()["detail"]["code"] == "account_disabled"
        for method, path in sorted(EXTENSION_UNGATED):
            assert (await probe.request(method, path, headers=_bearer(pair.access_token))).status_code == 200

    async def test_switched_off_for_the_user_keeps_the_session(self, probe, db_session, user):
        pair = await _connect(db_session, user)
        await set_chat_tool_access(db_session, "browser_extension", access_type="private", grants=[])
        await db_session.commit()
        refused = await probe.get("/api/chat/models", headers=_bearer(pair.access_token))
        assert refused.status_code == 403
        assert refused.json()["detail"]["code"] == "extension_not_permitted"
        for method, path in sorted(EXTENSION_UNGATED):
            assert (await probe.request(method, path, headers=_bearer(pair.access_token))).status_code == 200
        await set_chat_tool_access(db_session, "browser_extension", access_type="public", grants=[])
        await db_session.commit()
        assert (await probe.get("/api/chat/models", headers=_bearer(pair.access_token))).status_code == 200


class TestUse:
    async def test_use_is_recorded_at_most_once_a_minute(self, probe, db_session, session_factory, user):
        pair = await _connect(db_session, user)
        stale = datetime.datetime(2026, 1, 1)
        await db_session.execute(
            update(ExtensionSession).where(ExtensionSession.id == pair.session_id).values(last_used_at=stale)
        )
        await db_session.commit()
        await probe.get("/api/chat/models", headers=_bearer(pair.access_token))
        await extension_tokens.wait_for_touches()
        async with session_factory() as fresh:
            row = await fresh.get(ExtensionSession, pair.session_id)
        assert row.last_used_at > stale
        touched = row.last_used_at
        await probe.get("/api/chat/models", headers=_bearer(pair.access_token))
        await extension_tokens.wait_for_touches()
        async with session_factory() as fresh:
            assert (await fresh.get(ExtensionSession, pair.session_id)).last_used_at == touched


class TestRecordingUseNeverHoldsTheRequest:
    async def test_the_request_does_not_wait_for_the_touch(self, probe, db_session, user, monkeypatch):
        pair = await _connect(db_session, user)
        await db_session.execute(
            update(ExtensionSession)
            .where(ExtensionSession.id == pair.session_id)
            .values(last_used_at=datetime.datetime(2026, 1, 1))
        )
        await db_session.commit()
        release = asyncio.Event()
        started = asyncio.Event()

        async def slow_touch(session_id, *, ip):
            started.set()
            await release.wait()

        monkeypatch.setattr(extension_tokens, "touch_session", slow_touch)
        resp = await asyncio.wait_for(probe.get("/api/chat/models", headers=_bearer(pair.access_token)), timeout=10)
        assert resp.status_code == 200
        assert started.is_set()
        release.set()
        await extension_tokens.wait_for_touches()


class TestTheOtherPathsAreUnchanged:
    async def test_the_session_cookie(self, client, user):
        client.cookies.set(get_settings().session_cookie_name, create_access_token(user.username, "user"))
        assert (await client.get("/api/chat/models")).status_code == 200

    async def test_csrf_still_guards_cookie_requests(self, client, user):
        settings = get_settings()
        client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
        client.cookies.set(settings.csrf_cookie_name, CSRF)
        refused = await client.post("/api/user/chats/sessions", json={})
        assert refused.status_code == 403
        allowed = await client.post("/api/user/chats/sessions", json={}, headers={settings.csrf_header_name: CSRF})
        assert allowed.status_code == 200, allowed.text

    @pytest.mark.parametrize("legacy", [True, False])
    async def test_a_legacy_bearer_jwt(self, probe, user, monkeypatch, legacy):
        monkeypatch.setattr(get_settings(), "allow_legacy_bearer_auth", legacy)
        resp = await probe.get("/api/chat/models", headers=_bearer(create_access_token(user.username, "user")))
        assert resp.status_code == (200 if legacy else 401)

    async def test_an_extension_token_never_falls_through_to_the_jwt_path(self, probe, db_session, user, monkeypatch):
        monkeypatch.setattr(get_settings(), "allow_legacy_bearer_auth", True)
        pair = await _connect(db_session, user)
        resp = await probe.get("/api/admin/users", headers=_bearer(pair.access_token))
        assert resp.json()["detail"]["code"] == "extension_scope"

    async def test_the_token_wins_over_a_cookie(self, probe, db_session, user):
        other = User(username="cookie_user", email="cookie@test", auth_provider="local", is_active=True)
        db_session.add(other)
        await db_session.commit()
        pair = await _connect(db_session, user)
        probe.cookies.set(get_settings().session_cookie_name, create_access_token(other.username, "user"))
        resp = await probe.get("/api/chat/models", headers=_bearer(pair.access_token))
        assert resp.json()["user"] == user.username

    @pytest.mark.parametrize("legacy", [True, False])
    async def test_endpoints_that_pass_the_jwt_on_never_get_an_extension_token(
        self, probe, db_session, user, monkeypatch, legacy
    ):
        monkeypatch.setattr(get_settings(), "allow_legacy_bearer_auth", legacy)
        pair = await _connect(db_session, user)
        resp = await probe.get("/api/probe/token", headers=_bearer(pair.access_token))
        assert resp.status_code == 401

    def test_the_scope_is_a_constant_of_the_dependency_module(self):
        assert deps.EXTENSION_UNGATED <= deps.EXTENSION_SCOPE
