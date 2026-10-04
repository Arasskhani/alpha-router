"""Feature Access governs a person's own API keys.

Closed for a person: they cannot make a personal key, and the keys they
already have are refused at the gateway - kept, not revoked, so they work
again when the section opens. Keys an administrator issues on the API Keys
page are not personal keys and are left alone, and an administrator's own
personal keys always work.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from app.config import get_settings
from app.core.security import create_access_token, generate_api_key_for_user
from app.models.api_key import AlphaRouterApiKey, UserApiKey
from app.models.feature_access import FeatureAccessRule
from app.services.feature_access_service import FEATURE_FORBIDDEN_CODE

CSRF = "csrf-token"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


async def _personal_key(db, account) -> tuple[str, UserApiKey]:
    raw, prefix, key_hash = generate_api_key_for_user(account.username)
    key = UserApiKey(user_id=account.id, name="mine", key_prefix=prefix, key_hash=key_hash)
    db.add(key)
    await db.commit()
    return raw, key


async def _issued_key(db, owner) -> str:
    raw, prefix, key_hash = generate_api_key_for_user("svc")
    db.add(
        AlphaRouterApiKey(
            name="svc", key_prefix=prefix, key_hash=key_hash, owner_user_id=owner.id, unlimited_budget=True
        )
    )
    await db.commit()
    return raw


async def _close(db, account) -> None:
    db.add(FeatureAccessRule(feature="api_keys", effect="deny", user_id=account.id))
    await db.commit()


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


def _refused(resp) -> None:
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == FEATURE_FORBIDDEN_CODE
    assert detail["feature"] == "api_keys"


class TestTheGateway:
    async def test_a_personal_key_is_refused_while_closed_and_works_again_after(self, client, db_session, user):
        raw, key = await _personal_key(db_session, user)
        assert (await client.get("/v1/models", headers=_bearer(raw))).status_code == 200

        await _close(db_session, user)
        _refused(await client.get("/v1/models", headers=_bearer(raw)))
        _refused(
            await client.post(
                "/v1/chat/completions",
                json={"model": "any", "messages": [{"role": "user", "content": "hi"}]},
                headers=_bearer(raw),
            )
        )
        _refused(await client.post("/v1/embeddings", json={"model": "any", "input": "hi"}, headers=_bearer(raw)))
        # Kept, not revoked.
        await db_session.refresh(key)
        assert key.is_active is True

        await db_session.execute(delete(FeatureAccessRule))
        await db_session.commit()
        assert (await client.get("/v1/models", headers=_bearer(raw))).status_code == 200

    async def test_a_group_or_department_closes_it_too(self, client, db_session, user):
        raw, _key = await _personal_key(db_session, user)
        user.department = "Contractors"
        await db_session.commit()
        db_session.add(FeatureAccessRule(feature="api_keys", effect="deny", department="contractors"))
        await db_session.commit()
        _refused(await client.get("/v1/models", headers=_bearer(raw)))

    async def test_a_key_an_administrator_issued_is_left_alone(self, client, db_session, user):
        raw = await _issued_key(db_session, user)
        await _close(db_session, user)
        assert (await client.get("/v1/models", headers=_bearer(raw))).status_code == 200

    async def test_an_administrator_s_own_key_always_works(self, client, db_session, admin):
        raw, _key = await _personal_key(db_session, admin)
        await _close(db_session, admin)
        assert (await client.get("/v1/models", headers=_bearer(raw))).status_code == 200

    async def test_closing_chat_or_projects_leaves_keys_alone(self, client, db_session, user):
        raw, _key = await _personal_key(db_session, user)
        for feature in ("chat", "projects"):
            db_session.add(FeatureAccessRule(feature=feature, effect="deny", user_id=user.id))
        await db_session.commit()
        assert (await client.get("/v1/models", headers=_bearer(raw))).status_code == 200


def _sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


class TestTheWebApp:
    async def test_no_new_key_while_closed(self, client, db_session, user):
        await _close(db_session, user)
        headers = _sign_in(client, user)
        _refused(await client.post("/api/user/api-keys", json={"name": "k"}, headers=headers))

    async def test_the_person_can_still_see_and_revoke_their_keys(self, client, db_session, user):
        _raw, key = await _personal_key(db_session, user)
        await _close(db_session, user)
        headers = _sign_in(client, user)
        listed = await client.get("/api/user/api-keys/list")
        assert listed.status_code == 200, listed.text
        assert (await client.delete(f"/api/user/api-keys/{key.id}", headers=headers)).status_code in (200, 204)

    async def test_the_session_says_so(self, client, db_session, user):
        _sign_in(client, user)
        assert (await client.get("/api/auth/session")).json()["features"]["api_keys"] is True
        await _close(db_session, user)
        assert (await client.get("/api/auth/session")).json()["features"]["api_keys"] is False

    async def test_the_admin_page_lists_and_takes_the_section(self, client, admin, user):
        headers = _sign_in(client, admin)
        listed = (await client.get("/api/admin/feature-access")).json()["features"]
        assert [f["key"] for f in listed] == ["chat", "projects", "api_keys"]
        assert listed[2]["title"] == "API keys"
        added = await client.post(
            "/api/admin/feature-access/rules",
            json={"feature": "api_keys", "target_type": "user", "target": user.id},
            headers=headers,
        )
        assert added.status_code == 201, added.text
        check = (await client.get("/api/admin/feature-access/check", params={"user_id": user.id})).json()
        by_key = {f["feature"]: f for f in check["features"]}
        assert by_key["api_keys"]["allowed"] is False and by_key["api_keys"]["reason"] == "user_deny"
