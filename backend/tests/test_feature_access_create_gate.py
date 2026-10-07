"""Creating a project follows Create projects; everything else in projects does not.

The loophole this closes: with Chat closed and Projects open, a person could
create a project of their own and chat in it. Creating is now refused to them
(unless an administrator gave them an Allow on Create projects), while the
projects they are invited to keep working.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.core.security import create_access_token
from app.models.feature_access import FeatureAccessRule
from app.services.feature_access_service import FEATURE_FORBIDDEN_CODE
from app.models.project import ProjectMember
from app.services.project_service import create_project

CSRF = "csrf-token"


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


def _sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _rule(db, feature: str, account, effect: str = "deny") -> None:
    db.add(FeatureAccessRule(feature=feature, effect=effect, user_id=account.id))
    await db.commit()


async def _create(client, headers):
    return await client.post("/api/projects", json={"name": "Mine"}, headers=headers)


def _refused(resp) -> None:
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == FEATURE_FORBIDDEN_CODE
    assert detail["feature"] == "project_create"
    assert detail["message"].startswith("Create projects is not enabled for your account.")


async def test_open_by_default(client, user):
    assert (await _create(client, _sign_in(client, user))).status_code == 201


async def test_its_own_deny_refuses_creating(client, db_session, user):
    await _rule(db_session, "project_create", user)
    _refused(await _create(client, _sign_in(client, user)))


async def test_closed_chat_refuses_creating_but_invited_projects_keep_working(client, db_session, user, admin):
    created = await create_project(db_session, user=admin, name="Team")
    db_session.add(ProjectMember(project_id=str(created["id"]), user_id=user.id, role="contributor"))
    await db_session.commit()
    await _rule(db_session, "chat", user)
    headers = _sign_in(client, user)

    _refused(await _create(client, headers))
    listed = (await client.get("/api/projects")).json()["projects"]
    assert [p["name"] for p in listed] == ["Team"]
    chat = await client.post(f"/api/projects/{created['id']}/chats", json={"title": "Plan"}, headers=headers)
    assert chat.status_code == 200, chat.text


async def test_a_personal_allow_lets_them_create_with_chat_closed(client, db_session, user):
    await _rule(db_session, "chat", user)
    await _rule(db_session, "project_create", user, effect="allow")
    assert (await _create(client, _sign_in(client, user))).status_code == 201


async def test_an_administrator_creates_whatever_the_rules_say(client, db_session, admin):
    await _rule(db_session, "chat", admin)
    await _rule(db_session, "project_create", admin)
    assert (await _create(client, _sign_in(client, admin))).status_code == 201
