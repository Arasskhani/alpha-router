"""A project that is the person's alone follows Chat, not Projects, for its chat.

Project chat follows Projects so that a person whose Chat is closed can still
work with their team. In a project they own that nobody else is in, though,
its chat is a personal chat by another name: while their Chat is closed it is
refused too, by every route that reaches it. The rest of the project - files,
rooms, members - keeps working, and the chat opens again once a second member
joins. Pending invitations do not count as members.
"""

from __future__ import annotations

import uuid

import pytest

from app.config import get_settings
from app.core.security import create_access_token
from app.models.chat import ChatSession
from app.models.feature_access import FeatureAccessRule
from app.models.project import ProjectMember
from app.services.feature_access_service import FEATURE_FORBIDDEN_CODE
from app.services.project_service import create_project

CSRF = "csrf-token"


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


@pytest.fixture(autouse=True)
def _read_db(client):
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


async def _close_chat(db, account) -> None:
    db.add(FeatureAccessRule(feature="chat", effect="deny", user_id=account.id))
    await db.commit()


async def _solo(db, account) -> tuple[str, str]:
    """A project only ``account`` is in, with one stored chat."""
    created = await create_project(db, user=account, name="Just me")
    sid = str(uuid.uuid4())
    db.add(ChatSession(id=sid, user_id=account.id, title="t", project_id=str(created["id"])))
    await db.commit()
    return str(created["id"]), sid


def _refused(resp) -> None:
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert (detail["code"], detail["feature"], detail["reason"]) == (FEATURE_FORBIDDEN_CODE, "chat", "solo_project")


def _turn(**extra) -> dict:
    return {"model": "vendor/model", "messages": [{"role": "user", "content": "hi"}], **extra}


def _not_a_feature_refusal(resp) -> bool:
    detail = resp.json().get("detail") if resp.status_code == 403 else None
    return not (isinstance(detail, dict) and detail.get("code") == FEATURE_FORBIDDEN_CODE)


async def test_with_chat_open_a_solo_project_chats_as_before(client, db_session, user):
    project_id, sid = await _solo(db_session, user)
    _sign_in(client, user)
    assert (await client.get(f"/api/projects/{project_id}")).json()["chatClosed"] is False
    assert (await client.get(f"/api/projects/{project_id}/chats")).status_code == 200
    assert (await client.get(f"/api/user/chat-sessions/{sid}/messages")).status_code == 200


async def test_the_project_routes_of_its_chat_are_refused(client, db_session, user):
    project_id, sid = await _solo(db_session, user)
    await _close_chat(db_session, user)
    headers = _sign_in(client, user)
    base = f"/api/projects/{project_id}"

    assert (await client.get(base)).json()["chatClosed"] is True
    _refused(await client.get(f"{base}/chats"))
    _refused(await client.get(f"{base}/chats/sync"))
    _refused(await client.post(f"{base}/chats", json={"title": "Plan"}, headers=headers))
    _refused(await client.get(f"{base}/chats/{sid}"))
    _refused(await client.get(f"{base}/chats/{sid}/messages"))
    _refused(await client.post(f"{base}/chats/{sid}/messages", json={"role": "user", "content": "hi"}, headers=headers))
    _refused(await client.delete(f"{base}/chats/{sid}", headers=headers))
    assert await db_session.get(ChatSession, sid) is not None


async def test_the_rest_of_the_project_keeps_working(client, db_session, user):
    project_id, _sid = await _solo(db_session, user)
    await _close_chat(db_session, user)
    headers = _sign_in(client, user)
    base = f"/api/projects/{project_id}"
    assert (await client.get("/api/projects")).status_code == 200
    assert (await client.get(f"{base}/members")).status_code == 200
    assert (await client.get(f"{base}/resources")).status_code == 200
    assert (await client.get(f"{base}/rooms")).status_code == 200
    room = await client.post(f"{base}/rooms", json={"title": "Notes"}, headers=headers)
    assert room.status_code == 200, room.text
    handoff = await client.post(
        f"{base}/rooms/{room.json()['id']}/handoffs", json={"brief": "Draft the plan"}, headers=headers
    )
    _refused(handoff)


async def test_the_shared_chat_routes_are_refused(client, db_session, user):
    project_id, sid = await _solo(db_session, user)
    await _close_chat(db_session, user)
    headers = _sign_in(client, user)
    _refused(await client.get(f"/api/user/chat-sessions/{sid}/messages"))
    _refused(await client.post("/api/chat/completions", json=_turn(chat_session_id=sid), headers=headers))
    _refused(
        await client.post(
            "/api/chat/completions", json=_turn(project_id=project_id, persist_chat=True), headers=headers
        )
    )
    _refused(
        await client.post(
            "/api/chat/session-title",
            json={"model": "vendor/model", "messages": [{"role": "user", "content": "hi"}], "project_id": project_id},
            headers=headers,
        )
    )
    _refused(await client.get("/api/agents/handoffs/pending", params={"session_id": sid}))


async def test_an_invitation_is_not_a_member(client, db_session, user):
    project_id, _sid = await _solo(db_session, user)
    headers = _sign_in(client, user)
    invited = await client.post(
        f"/api/projects/{project_id}/invitations", json={"role": "contributor"}, headers=headers
    )
    assert invited.status_code in (200, 201), invited.text
    await _close_chat(db_session, user)
    _refused(await client.get(f"/api/projects/{project_id}/chats"))


async def test_a_second_member_opens_it_again(client, db_session, user, admin):
    project_id, sid = await _solo(db_session, user)
    await _close_chat(db_session, user)
    db_session.add(ProjectMember(project_id=project_id, user_id=admin.id, role="viewer"))
    await db_session.commit()
    headers = _sign_in(client, user)
    assert (await client.get(f"/api/projects/{project_id}")).json()["chatClosed"] is False
    assert (await client.get(f"/api/projects/{project_id}/chats")).status_code == 200
    resp = await client.post("/api/chat/completions", json=_turn(chat_session_id=sid), headers=headers)
    assert _not_a_feature_refusal(resp), resp.text


async def test_a_member_of_someone_elses_project_is_not_its_owner(client, db_session, user, admin):
    """Only the Primary Owner's chat closes; a member is never alone in a project they did not create."""
    project_id, _sid = await _solo(db_session, admin)
    db_session.add(ProjectMember(project_id=project_id, user_id=user.id, role="contributor"))
    await db_session.commit()
    await _close_chat(db_session, user)
    _sign_in(client, user)
    assert (await client.get(f"/api/projects/{project_id}/chats")).status_code == 200


async def test_an_administrator_is_never_refused(client, db_session, admin):
    project_id, sid = await _solo(db_session, admin)
    await _close_chat(db_session, admin)
    _sign_in(client, admin)
    assert (await client.get(f"/api/projects/{project_id}")).json()["chatClosed"] is False
    assert (await client.get(f"/api/projects/{project_id}/chats")).status_code == 200
    assert (await client.get(f"/api/user/chat-sessions/{sid}/messages")).status_code == 200


async def test_a_disabled_or_deleted_member_does_not_count(client, db_session, user, admin):
    import datetime

    from app.models.user import User

    project_id, _sid = await _solo(db_session, user)
    gone = User(username="gone-member", email=None, auth_provider="local", is_active=False)
    deleted = User(
        username="deleted-member",
        email=None,
        auth_provider="local",
        is_active=True,
        deleted_at=datetime.datetime.utcnow(),
    )
    db_session.add_all([gone, deleted])
    await db_session.flush()
    db_session.add_all(
        [
            ProjectMember(project_id=project_id, user_id=gone.id, role="contributor"),
            ProjectMember(project_id=project_id, user_id=deleted.id, role="viewer"),
        ]
    )
    await db_session.commit()
    await _close_chat(db_session, user)
    _sign_in(client, user)
    _refused(await client.get(f"/api/projects/{project_id}/chats"))


async def test_one_request_decides_its_sections_once(client, db_session, user, monkeypatch):
    """The Projects router and the chat gate of one request share one decision."""
    import app.api.feature_gate as gate

    project_id, _sid = await _solo(db_session, user)
    calls: list[list[str]] = []
    real = gate.decide_all

    async def counting(db, account, features):
        calls.append(list(features))
        return await real(db, account, features)

    monkeypatch.setattr(gate, "decide_all", counting)
    _sign_in(client, user)
    assert (await client.get(f"/api/projects/{project_id}/chats")).status_code == 200
    assert len(calls) == 1 and set(calls[0]) == {"chat", "projects"}
