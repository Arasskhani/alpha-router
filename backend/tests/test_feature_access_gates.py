"""The web Chat and Projects refuse an account Feature Access closed them to.

What the administrator was promised, end to end through the routes:

- Chat off: the personal chat list, its folders and its chats are refused,
  and so is a turn in a personal chat - but the person's project chats
  keep working, since they follow Projects.
- Projects off: every /api/projects route is refused, and so is a project
  chat reached through the shared chat routes.
- The browser extension is never refused here (it has its own access), and
  neither is an administrator.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.core.security import create_access_token
from app.models.chat import ChatSession
from app.models.feature_access import FeatureAccessRule
from app.services import extension_tokens
from app.services.extension_tokens import create_session
from app.services.feature_access_service import FEATURE_FORBIDDEN_CODE
from app.services.project_service import create_project

SERVER = "https://ai.example.com"
CSRF = "csrf-token"


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    monkeypatch.setattr(extension_tokens, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr(get_settings(), "frontend_url", f"{SERVER}/")


@pytest.fixture(autouse=True)
def _read_db(client):
    """The chat list and folders read through get_read_db: point it at the test database too."""
    from app.database import get_db, get_read_db
    from app.main import app

    app.dependency_overrides[get_read_db] = app.dependency_overrides[get_db]
    yield
    app.dependency_overrides.pop(get_read_db, None)


def _sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _deny(db, feature: str, account) -> None:
    db.add(FeatureAccessRule(feature=feature, effect="deny", user_id=account.id))
    await db.commit()


async def _chat(db, account, project_id: str | None = None) -> str:
    sid = str(uuid.uuid4())
    db.add(ChatSession(id=sid, user_id=account.id, title="t", project_id=project_id))
    await db.commit()
    return sid


async def _project(db, account) -> str:
    created = await create_project(db, user=account, name="Launch")
    await db.commit()
    return str(created["id"])


def _refused(resp, feature: str) -> None:
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == FEATURE_FORBIDDEN_CODE
    assert detail["feature"] == feature


def _turn(**extra) -> dict:
    return {"model": "vendor/model", "messages": [{"role": "user", "content": "hi"}], **extra}


class TestChatOff:
    async def test_the_personal_chat_routes_are_refused(self, client, db_session, user):
        await _deny(db_session, "chat", user)
        personal = await _chat(db_session, user)
        headers = _sign_in(client, user)
        _refused(await client.get("/api/user/chats"), "chat")
        _refused(await client.get("/api/user/chats/folders"), "chat")
        _refused(await client.get("/api/user/chats/search-messages", params={"q": "hello"}), "chat")
        _refused(await client.post("/api/user/chats/sessions", json={"title": "x"}, headers=headers), "chat")
        _refused(await client.get(f"/api/user/chat-sessions/{personal}/messages"), "chat")
        _refused(await client.delete(f"/api/user/chats/sessions/{personal}", headers=headers), "chat")
        _refused(await client.post("/api/chat/completions", json=_turn(), headers=headers), "chat")
        _refused(
            await client.post("/api/chat/completions", json=_turn(chat_session_id=personal), headers=headers),
            "chat",
        )

    async def test_nothing_is_deleted(self, client, db_session, user):
        """Closed, not removed: the chats are there when the section is given back."""
        personal = await _chat(db_session, user)
        await _deny(db_session, "chat", user)
        headers = _sign_in(client, user)
        _refused(await client.delete(f"/api/user/chats/sessions/{personal}", headers=headers), "chat")
        assert await db_session.get(ChatSession, personal) is not None

    async def test_project_chats_keep_working(self, client, db_session, user):
        project_id = await _project(db_session, user)
        in_project = await _chat(db_session, user, project_id)
        await _deny(db_session, "chat", user)
        _sign_in(client, user)
        assert (await client.get("/api/projects")).status_code == 200
        resp = await client.get(f"/api/user/chat-sessions/{in_project}/messages")
        assert resp.status_code == 200, resp.text

    async def test_a_project_id_does_not_carry_a_personal_chat_past_it(self, client, db_session, user):
        project_id = await _project(db_session, user)
        personal = await _chat(db_session, user)
        await _deny(db_session, "chat", user)
        headers = _sign_in(client, user)
        resp = await client.post(
            "/api/chat/completions",
            json=_turn(chat_session_id=personal, project_id=project_id),
            headers=headers,
        )
        _refused(resp, "chat")

    async def test_preferences_stay_reachable(self, client, db_session, user):
        """Settings reads them on every page; closing Chat must not break the rest of the app."""
        await _deny(db_session, "chat", user)
        _sign_in(client, user)
        assert (await client.get("/api/user/chats/prefs")).status_code != 403


class TestProjectsOff:
    async def test_every_project_route_is_refused(self, client, db_session, user):
        project_id = await _project(db_session, user)
        await _deny(db_session, "projects", user)
        headers = _sign_in(client, user)
        _refused(await client.get("/api/projects"), "projects")
        _refused(await client.get(f"/api/projects/{project_id}"), "projects")
        _refused(await client.post("/api/projects", json={"name": "New"}, headers=headers), "projects")
        _refused(await client.get(f"/api/projects/{project_id}/chats"), "projects")

    async def test_a_project_chat_is_refused_through_the_shared_routes(self, client, db_session, user):
        project_id = await _project(db_session, user)
        in_project = await _chat(db_session, user, project_id)
        await _deny(db_session, "projects", user)
        headers = _sign_in(client, user)
        _refused(await client.get(f"/api/user/chat-sessions/{in_project}/messages"), "projects")
        _refused(
            await client.post("/api/chat/completions", json=_turn(project_id=project_id), headers=headers),
            "projects",
        )
        _refused(
            await client.post("/api/chat/completions", json=_turn(chat_session_id=in_project), headers=headers),
            "projects",
        )

    async def test_the_personal_chat_keeps_working(self, client, db_session, user):
        personal = await _chat(db_session, user)
        await _deny(db_session, "projects", user)
        _sign_in(client, user)
        assert (await client.get("/api/user/chats/folders")).status_code == 200
        assert (await client.get(f"/api/user/chat-sessions/{personal}/messages")).status_code == 200


class TestNotGated:
    async def test_the_browser_extension_is_left_to_its_own_access(self, client, db_session, user):
        await _deny(db_session, "chat", user)
        pair = await create_session(db_session, user=user, device_name="Chrome", user_agent="UA", ip="10.0.0.5")
        await db_session.commit()
        browser = SimpleNamespace(headers={"Authorization": f"Bearer {pair.access_token}"})
        resp = await client.post("/api/user/chats/sessions", json={"title": "From a page"}, headers=browser.headers)
        assert resp.status_code in (200, 201), resp.text

    async def test_an_administrator_is_never_refused(self, client, db_session, admin):
        await _deny(db_session, "chat", admin)
        await _deny(db_session, "projects", admin)
        _sign_in(client, admin)
        assert (await client.get("/api/user/chats/folders")).status_code == 200
        assert (await client.get("/api/projects")).status_code == 200
