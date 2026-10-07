"""The web Chat and Projects refuse an account Feature Access closed them to.

What the administrator was promised, end to end through the routes:

- Chat off: the personal chat list, its folders and its chats are refused,
  and so is a turn in a personal chat - but the person's project chats
  keep working, since they follow Projects (in a project with other members:
  one that is the person's alone follows Chat, see
  test_feature_access_solo_project_chat.py).
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
from app.models.project import ProjectMember
from app.models.user import User
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
    """A project the account owns with one other member: its chat follows Projects."""
    created = await create_project(db, user=account, name="Launch")
    teammate = User(username=f"teammate-{uuid.uuid4().hex[:8]}", email=None, auth_provider="local", is_active=True)
    db.add(teammate)
    await db.flush()
    db.add(ProjectMember(project_id=str(created["id"]), user_id=teammate.id, role="contributor"))
    await db.commit()
    return str(created["id"])


def _refused(resp, feature: str) -> None:
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == FEATURE_FORBIDDEN_CODE
    assert detail["feature"] == feature


def _is_feature_refusal(resp) -> bool:
    if resp.status_code != 403:
        return False
    detail = resp.json().get("detail")
    return isinstance(detail, dict) and detail.get("code") == FEATURE_FORBIDDEN_CODE


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

    async def test_a_turn_in_a_stored_project_chat_is_not_refused(self, client, db_session, user):
        project_id = await _project(db_session, user)
        in_project = await _chat(db_session, user, project_id)
        await _deny(db_session, "chat", user)
        headers = _sign_in(client, user)
        resp = await client.post(
            "/api/chat/completions",
            json=_turn(chat_session_id=in_project, project_id=project_id),
            headers=headers,
        )
        assert not _is_feature_refusal(resp), resp.text

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

    async def test_a_project_id_alone_does_not_make_a_personal_turn_a_project_one(self, client, db_session, user):
        """No stored chat: only a turn saved in a project the person may write in counts as the project's."""
        mine = await _project(db_session, user)
        headers = _sign_in(client, user)
        await _deny(db_session, "chat", user)
        unsaved = await client.post(
            "/api/chat/completions", json=_turn(project_id=mine, persist_chat=False), headers=headers
        )
        _refused(unsaved, "chat")
        elsewhere = await client.post(
            "/api/chat/completions", json=_turn(project_id="not-a-project", persist_chat=True), headers=headers
        )
        _refused(elsewhere, "chat")
        saved = await client.post(
            "/api/chat/completions", json=_turn(project_id=mine, persist_chat=True), headers=headers
        )
        assert not _is_feature_refusal(saved), saved.text

    async def test_a_new_project_chat_can_be_titled_and_dictated_before_it_is_stored(self, client, db_session, user):
        mine = await _project(db_session, user)
        headers = _sign_in(client, user)
        await _deny(db_session, "chat", user)
        title = await client.post(
            "/api/chat/session-title",
            json={"model": "vendor/model", "messages": [{"role": "user", "content": "hi"}], "project_id": mine},
            headers=headers,
        )
        assert not _is_feature_refusal(title), title.text
        voice = await client.post(
            "/api/chat/voice",
            data={"project_id": mine, "chat_session_id": "not-stored-yet"},
            files={"file": ("v.webm", b"\x1a\x45\xdf\xa3", "audio/webm")},
            headers=headers,
        )
        assert not _is_feature_refusal(voice), voice.text

    async def test_a_chat_not_stored_yet_is_left_to_the_route(self, client, db_session, user):
        """The web app asks whether a new chat is on the server yet: 404 lets it create it, 403 would not."""
        await _deny(db_session, "chat", user)
        _sign_in(client, user)
        resp = await client.get("/api/user/chat-sessions/not-stored-yet/messages")
        assert resp.status_code == 404, resp.text

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


class TestTheSession:
    async def test_tells_the_web_app_which_sections_to_show(self, client, db_session, user):
        _sign_in(client, user)
        features = (await client.get("/api/auth/session")).json()["features"]
        assert features["chat"] is True and features["projects"] is True
        await _deny(db_session, "projects", user)
        features = (await client.get("/api/auth/session")).json()["features"]
        assert features["chat"] is True and features["projects"] is False

    async def test_tells_it_whether_to_offer_creating_projects_and_the_extension(self, client, db_session, user):
        _sign_in(client, user)
        features = (await client.get("/api/auth/session")).json()["features"]
        assert features["project_create"] is True and features["extension"] is True
        await _deny(db_session, "chat", user)
        await _deny(db_session, "extension", user)
        features = (await client.get("/api/auth/session")).json()["features"]
        assert features["project_create"] is False and features["extension"] is False

    async def test_an_administrator_sees_both(self, client, db_session, admin):
        await _deny(db_session, "chat", admin)
        _sign_in(client, admin)
        features = (await client.get("/api/auth/session")).json()["features"]
        assert features["chat"] is True and features["projects"] is True


class TestAgentRoutesAboutAChat:
    async def test_handoffs_in_a_personal_chat_follow_chat(self, client, db_session, user):
        personal = await _chat(db_session, user)
        _sign_in(client, user)
        assert (await client.get("/api/agents/handoffs/pending", params={"session_id": personal})).status_code == 200
        await _deny(db_session, "chat", user)
        _refused(await client.get("/api/agents/handoffs/pending", params={"session_id": personal}), "chat")

    async def test_handoffs_in_a_project_chat_follow_projects(self, client, db_session, user):
        in_project = await _chat(db_session, user, await _project(db_session, user))
        await _deny(db_session, "chat", user)
        _sign_in(client, user)
        assert (await client.get("/api/agents/handoffs/pending", params={"session_id": in_project})).status_code == 200
