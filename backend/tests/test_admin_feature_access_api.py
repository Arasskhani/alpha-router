"""The Feature Access admin API: list, add, change, remove, check a person.

The page is under Chat experience and needs the Chat Tools menu: a plain
user reaches none of it. Every change goes to the administrative trail.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.feature_access import FeatureAccessRule
from app.models.security import SecurityAuditEvent
from app.models.user import UserGroup, user_group_members

CSRF = "csrf-token"
BASE = "/api/admin/feature-access"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


def _sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _group(db, name: str, *user_ids: int) -> UserGroup:
    group = UserGroup(name=name)
    db.add(group)
    await db.flush()
    for user_id in user_ids:
        await db.execute(user_group_members.insert().values(group_id=group.id, user_id=user_id))
    await db.commit()
    return group


async def _trail(session_factory) -> list[SecurityAuditEvent]:
    async with session_factory() as fresh:
        rows = await fresh.execute(
            select(SecurityAuditEvent)
            .where(SecurityAuditEvent.action.like("feature_access_%"))
            .order_by(SecurityAuditEvent.id)
        )
        return list(rows.scalars().all())


class TestRules:
    async def test_add_list_change_remove(self, client, admin, user, session_factory):
        headers = _sign_in(client, admin)
        empty = (await client.get(BASE)).json()
        assert [f["key"] for f in empty["features"]] == ["chat", "projects"]
        assert all(f["rules"] == [] for f in empty["features"])

        added = await client.post(
            f"{BASE}/rules",
            json={"feature": "chat", "target_type": "user", "target": user.id, "note": "contractor"},
            headers=headers,
        )
        assert added.status_code == 201, added.text
        rule = added.json()
        assert rule["effect"] == "deny"
        assert rule["label"] == "fixture_user"
        assert rule["created_by"] == "fixture_admin"

        listed = (await client.get(BASE)).json()["features"][0]
        assert listed["deny_count"] == 1 and listed["rules"][0]["id"] == rule["id"]

        changed = await client.post(
            f"{BASE}/rules",
            json={"feature": "chat", "target_type": "user", "target": user.id, "effect": "allow"},
            headers=headers,
        )
        assert changed.status_code == 200
        assert changed.json()["id"] == rule["id"]
        assert changed.json()["effect"] == "allow"

        removed = await client.delete(f"{BASE}/rules/{rule['id']}", headers=headers)
        assert removed.status_code == 200
        assert (await client.delete(f"{BASE}/rules/{rule['id']}", headers=headers)).status_code == 404

        actions = [event.action for event in await _trail(session_factory)]
        assert actions == ["feature_access_rule_added", "feature_access_rule_changed", "feature_access_rule_removed"]

    async def test_groups_and_departments_take_deny_only(self, client, admin, db_session):
        group = await _group(db_session, "Interns")
        headers = _sign_in(client, admin)
        refused = await client.post(
            f"{BASE}/rules",
            json={"feature": "projects", "target_type": "group", "target": group.id, "effect": "allow"},
            headers=headers,
        )
        assert refused.status_code == 400
        ok = await client.post(
            f"{BASE}/rules",
            json={"feature": "projects", "target_type": "group", "target": group.id},
            headers=headers,
        )
        assert ok.status_code == 201
        assert ok.json()["label"] == "Interns"

    async def test_a_department_is_one_rule_whatever_its_spelling(self, client, admin, db_session):
        headers = _sign_in(client, admin)
        first = await client.post(
            f"{BASE}/rules",
            json={"feature": "chat", "target_type": "department", "target": "  Sales  Team "},
            headers=headers,
        )
        assert first.status_code == 201
        assert first.json()["target"] == "Sales Team"
        again = await client.post(
            f"{BASE}/rules",
            json={"feature": "chat", "target_type": "department", "target": "sales team", "note": "n"},
            headers=headers,
        )
        assert again.status_code == 200
        assert again.json()["id"] == first.json()["id"]
        rows = (await db_session.execute(select(FeatureAccessRule))).scalars().all()
        assert len(rows) == 1

    async def test_targets_must_exist(self, client, admin):
        headers = _sign_in(client, admin)
        for body in (
            {"feature": "chat", "target_type": "user", "target": 999_999},
            {"feature": "chat", "target_type": "group", "target": 999_999},
            {"feature": "chat", "target_type": "department", "target": "   "},
            {"feature": "chat", "target_type": "user", "target": "abc"},
        ):
            assert (await client.post(f"{BASE}/rules", json=body, headers=headers)).status_code == 400
        assert (
            await client.post(
                f"{BASE}/rules", json={"feature": "media", "target_type": "user", "target": 1}, headers=headers
            )
        ).status_code == 422


class TestCheck:
    async def test_says_what_a_person_gets_and_why(self, client, admin, user, db_session):
        group = await _group(db_session, "Contractors", user.id)
        headers = _sign_in(client, admin)
        await client.post(
            f"{BASE}/rules", json={"feature": "projects", "target_type": "group", "target": group.id}, headers=headers
        )
        body = (await client.get(f"{BASE}/check", params={"user_id": user.id})).json()
        by_key = {f["feature"]: f for f in body["features"]}
        assert by_key["chat"]["allowed"] is True and by_key["chat"]["reason"] == "default"
        assert by_key["projects"]["allowed"] is False
        assert by_key["projects"]["reason"] == "group_deny"
        assert by_key["projects"]["via"] == "Contractors"

    async def test_options_list_groups_and_departments(self, client, admin, user, db_session):
        user.department = "Finance"
        await db_session.commit()
        await _group(db_session, "Ops", user.id)
        _sign_in(client, admin)
        options = (await client.get(f"{BASE}/options")).json()
        assert {"name": "Ops", "member_count": 1}.items() <= options["groups"][0].items()
        assert {"name": "Finance", "user_count": 1} in options["departments"]
        users = (await client.get(f"{BASE}/user-options", params={"q": "fixture_u"})).json()
        assert [row["username"] for row in users] == ["fixture_user"]


class TestWhoMayUseIt:
    async def test_a_plain_user_reaches_none_of_it(self, client, user):
        headers = _sign_in(client, user)
        assert (await client.get(BASE)).status_code == 403
        assert (await client.get(f"{BASE}/check", params={"user_id": user.id})).status_code == 403
        resp = await client.post(
            f"{BASE}/rules", json={"feature": "chat", "target_type": "user", "target": user.id}, headers=headers
        )
        assert resp.status_code == 403
