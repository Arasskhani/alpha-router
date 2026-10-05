"""One password policy wherever a password is chosen: admin create, admin reset, Settings.

The forms read the rules from /api/auth/password-policy; the server checks
them again on every path that sets a password.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password

CSRF = "csrf-token"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


def _sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(
        settings.session_cookie_name,
        create_access_token(account.username, "user", token_version=int(account.token_version or 0)),
    )
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def test_the_rules_are_public_for_the_forms(client):
    body = (await client.get("/api/auth/password-policy")).json()
    assert body["min_length"] >= 8
    assert [rule["key"] for rule in body["rules"]] == ["length", "upper", "lower", "digit", "symbol", "personal"]


class TestAdministrators:
    async def test_creating_a_user_needs_a_complex_password(self, client, admin):
        headers = _sign_in(client, admin)
        weak = await client.post(
            "/api/admin/users",
            json={"username": "newbie", "email": "newbie@example.com", "password": "longbutsimple1"},
            headers=headers,
        )
        assert weak.status_code == 400
        assert weak.json()["detail"] == "Password must include an uppercase letter and a symbol"
        personal = await client.post(
            "/api/admin/users",
            json={"username": "newbie", "email": "newbie@example.com", "password": "Newbie-2026-pass!"},
            headers=headers,
        )
        assert personal.status_code == 400
        assert "username" in personal.json()["detail"]
        ok = await client.post(
            "/api/admin/users",
            json={"username": "newbie", "email": "newbie@example.com", "password": "Strong-Pass-2026!"},
            headers=headers,
        )
        assert ok.status_code == 200, ok.text

    async def test_resetting_a_password_needs_a_complex_one(self, client, admin, user):
        headers = _sign_in(client, admin)
        weak = await client.post(
            f"/api/admin/users/{user.id}/reset-password", json={"password": "nosymbols12A"}, headers=headers
        )
        assert weak.status_code == 400
        assert weak.json()["detail"] == "Password must include a symbol"


class TestSettings:
    async def test_changing_one_s_own_password_needs_a_complex_one(self, client, db_session, user, monkeypatch):
        async def no_limit(*_a, **_k):
            return None

        # The route's limiter fails closed without Redis, which tests do not run.
        monkeypatch.setattr("app.api.user_settings.check_rate_limit", no_limit)
        user.hashed_password = hash_password("Current-Pass-1!")
        await db_session.commit()
        headers = _sign_in(client, user)
        weak = await client.post(
            "/api/user/settings/password",
            json={
                "current_password": "Current-Pass-1!",
                "new_password": "alllowercase1!",
                "confirm_password": "alllowercase1!",
            },
            headers=headers,
        )
        assert weak.status_code == 400
        assert weak.json()["detail"] == "Password must include an uppercase letter"
        ok = await client.post(
            "/api/user/settings/password",
            json={
                "current_password": "Current-Pass-1!",
                "new_password": "Brand-New-Pass-2!",
                "confirm_password": "Brand-New-Pass-2!",
            },
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        await db_session.refresh(user)
        assert verify_password("Brand-New-Pass-2!", user.hashed_password)
