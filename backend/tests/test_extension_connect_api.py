"""Connecting a browser: authorize, token, me, revoke, and the user's list of connections."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select, update

from app.config import get_settings
from app.core.security import create_access_token
from app.main import app as fastapi_app
from app.models.extension import ExtensionSession
from app.models.security import SecurityAuditEvent
from app.models.system import SystemSetting
from app.models.user import User
from app.api import extension_connect as rate_limits
from app.services import extension_distribution, extension_keys, extension_tokens, rate_limit
from app.services.chat_tool_access_service import set_chat_tool_access
from app.services.extension_keys import KEY_SETTING, load_or_create_signing_key
from app.services.extension_settings import ExtensionSettings, save_extension_settings
from app.services.extension_tokens import pkce_challenge
from app.services.resource_access_service import AccessGrant

SERVER = "https://ai.example.com"
CSRF = "csrf-token"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = pkce_challenge(VERIFIER)
STATE = "state-0123456789abcdef"
TEMPLATE = Path(__file__).resolve().parents[2] / "frontend" / "extension" / "manifest.template.json"


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self):
                self._ops = []

            def get(self, key):
                self._ops.append(("get", key))

            def delete(self, key):
                self._ops.append(("delete", key))

            async def execute(self):
                out = []
                for op, key in self._ops:
                    out.append(outer.store.get(key) if op == "get" else outer.store.pop(key, None) is not None)
                return out

        return _Pipe()


def _no_redis():
    raise ConnectionError("no redis in tests")


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    for module in (extension_tokens, extension_keys, extension_distribution):
        monkeypatch.setattr(module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    shared = FakeRedis()
    monkeypatch.setattr(extension_tokens, "get_redis", lambda: shared)
    monkeypatch.setattr(rate_limit, "get_redis", _no_redis)
    rate_limit._buckets.clear()
    monkeypatch.setattr(get_settings(), "frontend_url", f"{SERVER}/")
    monkeypatch.setattr(get_settings(), "app_version", "v1.4.0")
    yield
    rate_limit._buckets.clear()


@pytest.fixture
async def extension_id(db_session) -> str:
    key = await load_or_create_signing_key(db_session)
    await db_session.commit()
    return key.extension_id


@pytest.fixture
def redirect(extension_id) -> str:
    return f"chrome-extension://{extension_id}/connected.html"


@pytest.fixture
async def browser(client):
    """The extension's own requests: no cookies, no CSRF header (``client`` points the app at the test database)."""
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _sign_in(client, user) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _authorize(client, headers, redirect_uri, **overrides):
    body = {
        "redirect_uri": redirect_uri,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": STATE,
        **overrides,
    }
    return await client.post("/api/extension/authorize", json=body, headers=headers)


def _query(redirect_to: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(redirect_to).query).items()}


async def _connect(client, browser, user, redirect_uri, *, device_name="Chrome on Windows") -> dict:
    headers = _sign_in(client, user)
    allowed = await _authorize(client, headers, redirect_uri)
    assert allowed.status_code == 200, allowed.text
    code = _query(allowed.json()["redirect_to"])["code"]
    resp = await browser.post(
        "/api/extension/token",
        json={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": VERIFIER,
            "redirect_uri": redirect_uri,
            "device_name": device_name,
        },
        headers={"User-Agent": "Mozilla/5.0 Test"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _from(address: tuple[str, int]) -> httpx.AsyncClient:
    """A client whose requests come from ``address`` (``client`` fixture must be active for the database)."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app, client=address), base_url="http://testserver"
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _audit(session_factory, action: str) -> list[SecurityAuditEvent]:
    async with session_factory() as fresh:
        rows = await fresh.execute(select(SecurityAuditEvent).where(SecurityAuditEvent.action == action))
        return list(rows.scalars().all())


async def _user(db, username: str, *, active: bool = True) -> User:
    row = User(
        username=username, email=f"{username}@test", hashed_password="x", auth_provider="local", is_active=active
    )
    db.add(row)
    await db.commit()
    return row


class TestTheWholeFlow:
    async def test_connect_use_refresh_and_disconnect(self, client, browser, user, redirect, session_factory):
        tokens = await _connect(client, browser, user, redirect)
        assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600
        assert tokens["access_token"].startswith("alpha-router-ext-at-")

        me = await browser.get("/api/extension/me", headers=_bearer(tokens["access_token"]))
        assert me.status_code == 200, me.text
        assert me.json()["user"]["username"] == user.username

        refreshed = await browser.post(
            "/api/extension/token", json={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
        )
        assert refreshed.status_code == 200, refreshed.text
        new = refreshed.json()
        assert new["session_id"] == tokens["session_id"]
        assert (await browser.get("/api/extension/me", headers=_bearer(tokens["access_token"]))).status_code == 401
        assert (await browser.get("/api/extension/me", headers=_bearer(new["access_token"]))).status_code == 200

        bye = await browser.post("/api/extension/revoke", headers=_bearer(new["access_token"]))
        assert bye.status_code == 200 and bye.json() == {"ok": True}
        gone = await browser.get("/api/extension/me", headers=_bearer(new["access_token"]))
        assert gone.status_code == 401
        assert gone.json()["detail"]["code"] == "revoked"

        (connected,) = await _audit(session_factory, "extension_connected")
        assert connected.actor_user_id == user.id
        assert connected.resource_id == tokens["session_id"]
        assert json.loads(connected.detail_json) == {"device_name": "Chrome on Windows"}
        (disconnected,) = await _audit(session_factory, "extension_disconnected")
        assert json.loads(disconnected.detail_json) == {"device_name": "Chrome on Windows", "from": "browser"}

    async def test_token_responses_are_never_cached(self, client, browser, user, redirect):
        headers = _sign_in(client, user)
        code = _query((await _authorize(client, headers, redirect)).json()["redirect_to"])["code"]
        resp = await browser.post(
            "/api/extension/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": VERIFIER,
                "redirect_uri": redirect,
            },
        )
        assert resp.headers["cache-control"] == "no-store"
        assert resp.headers["pragma"] == "no-cache"

    async def test_the_session_remembers_the_browser(self, client, browser, user, redirect, session_factory):
        tokens = await _connect(client, browser, user, redirect, device_name="Edge\n on  Mac")
        async with session_factory() as fresh:
            row = await fresh.get(ExtensionSession, tokens["session_id"])
        assert row.device_name == "Edge on Mac"
        assert row.user_agent == "Mozilla/5.0 Test"


class TestAuthorize:
    async def test_the_answer_goes_back_to_the_extension_with_the_state(self, client, user, redirect):
        resp = await _authorize(client, _sign_in(client, user), redirect)
        target = resp.json()["redirect_to"]
        assert target.startswith(redirect + "?")
        query = _query(target)
        assert query["state"] == STATE and len(query["code"]) >= 43

    async def test_deny_sends_the_refusal_back(self, client, user, redirect, session_factory):
        resp = await _authorize(client, _sign_in(client, user), redirect, deny=True)
        assert resp.status_code == 200
        assert _query(resp.json()["redirect_to"]) == {"error": "access_denied", "state": STATE}

    @pytest.mark.parametrize(
        "make",
        [
            lambda ext: f"chrome-extension://{'a' * 32}/connected.html",
            lambda ext: f"chrome-extension://{ext.upper()}/connected.html",
            lambda ext: f"chrome-extension://{ext}/connected.html?x=1",
            lambda ext: f"chrome-extension://{ext}/connected.html#x",
            lambda ext: f"chrome-extension://{ext}/sidepanel.html",
            lambda ext: f"chrome-extension://{ext}:80/connected.html",
            lambda ext: f"chrome-extension://user@{ext}/connected.html",
            lambda ext: f"https://{ext}/connected.html",
            # Not a browser scheme: an app registered for it would get the code.
            lambda ext: f"extension://{ext}/connected.html",
            lambda ext: "https://evil.example/connected.html",
        ],
    )
    @pytest.mark.parametrize("deny", [False, True])
    async def test_nothing_is_sent_anywhere_else(self, client, user, extension_id, make, deny):
        resp = await _authorize(client, _sign_in(client, user), make(extension_id), deny=deny)
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "invalid_request"

    @pytest.mark.parametrize(
        "overrides",
        [{"code_challenge_method": "plain"}, {"code_challenge": "short"}, {"code_challenge": CHALLENGE + "="}],
    )
    async def test_an_unusable_challenge_is_refused(self, client, user, redirect, overrides):
        resp = await _authorize(client, _sign_in(client, user), redirect, **overrides)
        assert resp.status_code == 400

    @pytest.mark.parametrize("state", ["short", "x" * 129, "has space in it!!"])
    async def test_a_malformed_state_is_refused(self, client, user, redirect, state):
        resp = await _authorize(client, _sign_in(client, user), redirect, state=state)
        assert resp.status_code == 422

    async def test_not_for_a_user_the_admin_left_out(self, client, db_session, user, redirect):
        await set_chat_tool_access(db_session, "browser_extension", access_type="private", grants=[])
        await db_session.commit()
        resp = await _authorize(client, _sign_in(client, user), redirect)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "not_permitted"

    async def test_a_grant_lets_that_user_connect(self, client, db_session, user, redirect):
        await set_chat_tool_access(
            db_session,
            "browser_extension",
            access_type="private",
            grants=[AccessGrant(target_type="user", target=user.id)],
        )
        await db_session.commit()
        assert (await _authorize(client, _sign_in(client, user), redirect)).status_code == 200

    async def test_not_for_a_disabled_account(self, client, db_session, redirect):
        disabled = await _user(db_session, "disabled", active=False)
        assert (await _authorize(client, _sign_in(client, disabled), redirect)).status_code == 403

    async def test_signing_in_and_csrf_are_required(self, client, browser, user, redirect):
        assert (await _authorize(browser, {}, redirect)).status_code == 401
        _sign_in(client, user)
        assert (await _authorize(client, {}, redirect)).status_code == 403

    async def test_a_connected_browser_cannot_authorize_itself(self, client, browser, user, redirect):
        tokens = await _connect(client, browser, user, redirect)
        resp = await _authorize(browser, _bearer(tokens["access_token"]), redirect)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "extension_scope"

    async def test_no_key_yet_means_nothing_to_connect(self, client, user):
        resp = await _authorize(client, _sign_in(client, user), f"chrome-extension://{'a' * 32}/connected.html")
        assert resp.status_code == 400
        assert "not handed out" in resp.json()["detail"]["message"]

    async def test_an_unreadable_key_is_503(self, client, db_session, user, redirect):
        await db_session.execute(update(SystemSetting).where(SystemSetting.key == KEY_SETTING).values(value="garbage"))
        await db_session.commit()
        resp = await _authorize(client, _sign_in(client, user), redirect)
        assert resp.status_code == 503

    async def test_twenty_a_minute(self, client, user, redirect):
        headers = _sign_in(client, user)
        for _ in range(20):
            assert (await _authorize(client, headers, redirect)).status_code == 200
        assert (await _authorize(client, headers, redirect)).status_code == 429


class TestTheCodeExchange:
    async def _code(self, client, user, redirect) -> str:
        return _query((await _authorize(client, _sign_in(client, user), redirect)).json()["redirect_to"])["code"]

    async def _exchange(self, browser, **body):
        return await browser.post("/api/extension/token", json={"grant_type": "authorization_code", **body})

    async def test_a_wrong_verifier_spends_the_code(self, client, browser, user, redirect):
        code = await self._code(client, user, redirect)
        wrong = await self._exchange(browser, code=code, code_verifier="v" * 43, redirect_uri=redirect)
        assert wrong.status_code == 400
        assert wrong.json()["detail"]["code"] == "invalid_grant"
        again = await self._exchange(browser, code=code, code_verifier=VERIFIER, redirect_uri=redirect)
        assert again.json()["detail"]["code"] == "invalid_grant"

    async def test_a_code_works_once(self, client, browser, user, redirect):
        code = await self._code(client, user, redirect)
        first = await self._exchange(browser, code=code, code_verifier=VERIFIER, redirect_uri=redirect)
        second = await self._exchange(browser, code=code, code_verifier=VERIFIER, redirect_uri=redirect)
        assert (first.status_code, second.status_code) == (200, 400)

    async def test_another_redirect_is_refused(self, client, browser, user, redirect, extension_id):
        code = await self._code(client, user, redirect)
        resp = await self._exchange(
            browser, code=code, code_verifier=VERIFIER, redirect_uri=f"extension://{extension_id}/connected.html"
        )
        assert resp.json()["detail"]["code"] == "invalid_grant"

    @pytest.mark.parametrize("missing", ["code", "code_verifier", "redirect_uri"])
    async def test_every_part_is_required(self, client, browser, user, redirect, missing):
        code = await self._code(client, user, redirect)
        body = {"code": code, "code_verifier": VERIFIER, "redirect_uri": redirect}
        body.pop(missing)
        resp = await self._exchange(browser, **body)
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "invalid_request"

    async def test_switched_off_between_allow_and_exchange(
        self, client, browser, db_session, session_factory, user, redirect
    ):
        code = await self._code(client, user, redirect)
        await set_chat_tool_access(db_session, "browser_extension", access_type="private", grants=[])
        await db_session.commit()
        resp = await self._exchange(browser, code=code, code_verifier=VERIFIER, redirect_uri=redirect)
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "not_permitted"
        async with session_factory() as fresh:
            assert (await fresh.execute(select(ExtensionSession.id))).first() is None

    async def test_disabled_between_allow_and_exchange(self, client, browser, db_session, user, redirect):
        code = await self._code(client, user, redirect)
        await db_session.execute(update(User).where(User.id == user.id).values(is_active=False))
        await db_session.commit()
        resp = await self._exchange(browser, code=code, code_verifier=VERIFIER, redirect_uri=redirect)
        assert resp.json()["detail"]["code"] == "invalid_grant"

    async def test_an_unknown_grant_type(self, browser):
        resp = await browser.post("/api/extension/token", json={"grant_type": "password"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "invalid_request"

    async def test_sixty_failures_a_minute_close_the_address(self, browser):
        for _ in range(60):
            resp = await self._exchange(browser, code="nope", code_verifier=VERIFIER, redirect_uri="x")
            assert resp.status_code == 400
        assert (await self._exchange(browser, code="nope", code_verifier=VERIFIER, redirect_uri="x")).status_code == 429


class TestRefresh:
    async def test_an_unknown_refresh_token(self, browser):
        resp = await browser.post(
            "/api/extension/token", json={"grant_type": "refresh_token", "refresh_token": "alpha-router-ext-rt-nope"}
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "invalid_grant"

    async def test_a_missing_refresh_token(self, browser):
        resp = await browser.post("/api/extension/token", json={"grant_type": "refresh_token"})
        assert resp.json()["detail"]["code"] == "invalid_request"

    async def test_a_replayed_token_ends_the_session_and_is_audited(
        self, client, browser, user, redirect, session_factory, monkeypatch
    ):
        tokens = await _connect(client, browser, user, redirect)
        body = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
        assert (await browser.post("/api/extension/token", json=body)).status_code == 200
        later = extension_tokens._now() + extension_tokens.REFRESH_GRACE + datetime.timedelta(seconds=1)
        monkeypatch.setattr(extension_tokens, "_now", lambda: later)
        replay = await browser.post("/api/extension/token", json=body)
        assert replay.status_code == 400
        (event,) = await _audit(session_factory, "extension_session_revoked")
        assert event.actor_user_id == user.id
        assert event.resource_id == tokens["session_id"]
        assert json.loads(event.detail_json) == {"reason": "refresh_reuse", "device_name": "Chrome on Windows"}

    async def test_a_disabled_account_keeps_its_browsers_for_when_it_returns(
        self, client, browser, db_session, user, redirect
    ):
        tokens = await _connect(client, browser, user, redirect)
        await db_session.execute(update(User).where(User.id == user.id).values(is_active=False))
        await db_session.commit()
        body = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
        refreshed = await browser.post("/api/extension/token", json=body)
        assert refreshed.status_code == 200, refreshed.text
        access = refreshed.json()["access_token"]
        me = await browser.get("/api/extension/me", headers=_bearer(access))
        assert me.status_code == 200 and not any(me.json()["features"].values())
        refused = await browser.get("/api/chat/models", headers=_bearer(access))
        assert refused.json()["detail"]["code"] == "account_disabled"
        await db_session.execute(update(User).where(User.id == user.id).values(is_active=True))
        await db_session.commit()
        assert (await browser.get("/api/chat/models", headers=_bearer(access))).status_code == 200

    async def test_successes_never_fill_the_address_window(self, client, browser, user, redirect):
        tokens = await _connect(client, browser, user, redirect)
        refresh = tokens["refresh_token"]
        for _ in range(rate_limits.TOKEN_FAILURES_PER_IP + 5):
            resp = await browser.post(
                "/api/extension/token", json={"grant_type": "refresh_token", "refresh_token": refresh}
            )
            assert resp.status_code == 200, resp.text
            refresh = resp.json()["refresh_token"]

    async def test_the_per_token_limit_follows_the_token_not_the_address(self, client):
        body = {"grant_type": "refresh_token", "refresh_token": "alpha-router-ext-rt-same"}
        async with _from(("10.0.0.8", 5000)) as first, _from(("10.0.0.9", 5000)) as second:
            for _ in range(10):
                assert (await first.post("/api/extension/token", json=body)).status_code == 400
            assert (await second.post("/api/extension/token", json=body)).status_code == 429
            other = {"grant_type": "refresh_token", "refresh_token": "alpha-router-ext-rt-other"}
            assert (await second.post("/api/extension/token", json=other)).status_code == 400

    async def test_ten_refreshes_a_minute_per_token(self, browser):
        body = {"grant_type": "refresh_token", "refresh_token": "alpha-router-ext-rt-same"}
        for _ in range(10):
            assert (await browser.post("/api/extension/token", json=body)).status_code == 400
        assert (await browser.post("/api/extension/token", json=body)).status_code == 429


class TestMe:
    async def test_what_the_panel_is_told(self, client, browser, db_session, user, redirect, tmp_path, monkeypatch):
        monkeypatch.setattr(extension_distribution, "resolve_extension_dist", lambda: tmp_path / "not-built")
        await save_extension_settings(
            db_session, ExtensionSettings(allowed_sites=("example.com",), blocked_sites=("bank.example",))
        )
        await db_session.commit()
        tokens = await _connect(client, browser, user, redirect)
        me = (await browser.get("/api/extension/me", headers=_bearer(tokens["access_token"]))).json()
        assert me["user"] == {"username": user.username, "display_name": None, "email": user.email}
        # Not the build: only administrators see that (/api/admin/version).
        assert me["server"] == {"name": "Alpharouter", "url": SERVER}
        assert me["extension"] == {"latest_version": None, "min_version": "1.0.0.0"}
        assert me["features"] == {
            "chat": True,
            "page_context": True,
            "agent": False,
            "auto_mode": False,
            "private_mode": True,
        }
        assert me["policy"] == {
            "site_access": "per_site",
            "allowed_sites": ["example.com"],
            "blocked_sites": ["bank.example"],
            "page_content_models": [],
            "agent_models": [],
            "agent_max_steps": 25,
        }

    async def test_the_agent_needs_its_own_grant(self, client, browser, db_session, user, redirect):
        await set_chat_tool_access(
            db_session, "browser_agent", access_type="private", grants=[AccessGrant(target_type="user", target=user.id)]
        )
        await db_session.commit()
        tokens = await _connect(client, browser, user, redirect)
        features = (await browser.get("/api/extension/me", headers=_bearer(tokens["access_token"]))).json()["features"]
        assert features["agent"] is True and features["auto_mode"] is False

    async def test_switched_off_it_still_answers_with_everything_off(self, client, browser, db_session, user, redirect):
        tokens = await _connect(client, browser, user, redirect)
        await set_chat_tool_access(db_session, "browser_extension", access_type="private", grants=[])
        await set_chat_tool_access(db_session, "private_mode", access_type="private", grants=[])
        await db_session.commit()
        resp = await browser.get("/api/extension/me", headers=_bearer(tokens["access_token"]))
        assert resp.status_code == 200
        assert not any(resp.json()["features"].values())
        # The site and model rules are for people who may use the extension.
        assert resp.json()["policy"] is None

    async def test_the_latest_version_is_the_package_this_server_hands_out(
        self, client, browser, user, redirect, tmp_path, monkeypatch
    ):
        dist = tmp_path / "dist-extension"
        dist.mkdir()
        (dist / "manifest.json").write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        (dist / "config.json").write_text('{"serverUrl": ""}\n', encoding="utf-8")
        monkeypatch.setattr(extension_distribution, "resolve_extension_dist", lambda: dist)
        tokens = await _connect(client, browser, user, redirect)
        me = (await browser.get("/api/extension/me", headers=_bearer(tokens["access_token"]))).json()
        assert me["extension"]["latest_version"] == "1.0.0.1"

    async def test_revoke_needs_a_connected_browser(self, client, user):
        headers = _sign_in(client, user)
        resp = await client.post("/api/extension/revoke", headers=headers)
        assert resp.status_code == 400


class TestMyConnections:
    async def test_list_and_disconnect_from_settings(
        self, client, browser, db_session, user, redirect, session_factory
    ):
        first = await _connect(client, browser, user, redirect, device_name="Laptop")
        second = await _connect(client, browser, user, redirect, device_name="Desktop")
        headers = _sign_in(client, user)
        listed = (await client.get("/api/extension/sessions")).json()["items"]
        assert {row["id"] for row in listed} == {first["session_id"], second["session_id"]}
        assert set(listed[0]) == {"id", "device_name", "created_at", "last_used_at", "last_ip"}
        resp = await client.delete(f"/api/extension/sessions/{first['session_id']}", headers=headers)
        assert resp.status_code == 200
        listed = (await client.get("/api/extension/sessions")).json()["items"]
        assert [row["id"] for row in listed] == [second["session_id"]]
        assert (await browser.get("/api/extension/me", headers=_bearer(first["access_token"]))).status_code == 401
        (event,) = await _audit(session_factory, "extension_disconnected")
        assert json.loads(event.detail_json) == {"device_name": "Laptop", "from": "settings"}
        again = await client.delete(f"/api/extension/sessions/{first['session_id']}", headers=headers)
        assert again.status_code == 404

    async def test_nobody_else_can_see_or_end_yours(self, client, browser, db_session, user, redirect):
        mine = await _connect(client, browser, user, redirect)
        other = await _user(db_session, "someone_else")
        headers = _sign_in(client, other)
        assert (await client.get("/api/extension/sessions")).json()["items"] == []
        resp = await client.delete(f"/api/extension/sessions/{mine['session_id']}", headers=headers)
        assert resp.status_code == 404
        assert (await browser.get("/api/extension/me", headers=_bearer(mine["access_token"]))).status_code == 200

    @pytest.mark.parametrize("session_id", ["not-a-session", "Z" * 36, "0" * 36])
    async def test_unknown_ids_are_404(self, client, user, session_id):
        headers = _sign_in(client, user)
        assert (await client.delete(f"/api/extension/sessions/{session_id}", headers=headers)).status_code == 404

    async def test_a_connected_browser_cannot_manage_connections(self, client, browser, user, redirect):
        tokens = await _connect(client, browser, user, redirect)
        for method, path in (
            ("GET", "/api/extension/sessions"),
            ("DELETE", f"/api/extension/sessions/{tokens['session_id']}"),
        ):
            resp = await browser.request(method, path, headers=_bearer(tokens["access_token"]))
            assert resp.status_code == 403
            assert resp.json()["detail"]["code"] == "extension_scope"
