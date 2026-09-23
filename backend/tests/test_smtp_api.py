"""The SMTP settings API: what is saved, what is read back, what Test reports.

The connection itself is exercised against a real local SMTP server (see
``tests/smtp_test_server.py``); these tests are about the administrative
surface: the explicit security mode, a page loaded before it existed, input
that must never be saved, and who may change any of it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.system import SmtpSettings
from app.models.user import User
from app.services import smtp_service
from app.services.secret_crypto import decrypt_secret
from app.services.user_role_service import set_user_roles
from tests.smtp_test_server import MODE_STARTTLS, SmtpTestServer, TlsMaterial, make_tls_material

URL = "/api/admin/smtp"
TEST_URL = "/api/admin/smtp/test"


@pytest.fixture(autouse=True)
def _guard_on_the_test_engine(session_factory, monkeypatch):
    from app.services import admin_ip_allowlist_service

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    admin_ip_allowlist_service.invalidate_restriction_cache()
    yield
    admin_ip_allowlist_service.invalidate_restriction_cache()


@pytest.fixture(scope="module")
def tls(tmp_path_factory) -> TlsMaterial:
    return make_tls_material(tmp_path_factory.mktemp("smtp-api-tls"))


@pytest.fixture(autouse=True)
def _trust_the_test_ca(tls, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", str(tls.ca_path))
    monkeypatch.setattr(smtp_service, "TIMEOUT_SECONDS", 5.0)


def _sign_in(client, user: User) -> dict[str, str]:
    from app.config import get_settings

    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, "csrf-token")
    return {settings.csrf_header_name: "csrf-token"}


async def _user(db, username: str, roles: list[str] | None = None) -> User:
    row = User(username=username, email=f"{username}@test", hashed_password="x", auth_provider="local", is_active=True)
    db.add(row)
    await db.flush()
    if roles:
        await set_user_roles(db, row, roles)
    await db.commit()
    return row


def _body(**overrides) -> dict:
    body = {
        "host": "mail.example.com",
        "port": 587,
        "username": "alpha",
        "password": "s3cret",
        "from_address": "reports@example.com",
        "security": "starttls",
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not ...}


async def _saved(db_session) -> SmtpSettings:
    db_session.expire_all()
    row = (await db_session.execute(select(SmtpSettings))).scalars().one()
    return row


class TestSaveAndRead:
    async def test_nothing_until_configured(self, client, admin):
        headers = _sign_in(client, admin)
        resp = await client.get(URL, headers=headers)
        assert resp.status_code == 200
        assert resp.json() is None

    async def test_the_mode_is_stored_and_read_back_without_the_secret(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        resp = await client.put(URL, headers=headers, json=_body(security="ssl", port=465))
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "security": "ssl"}

        row = await _saved(db_session)
        assert row.security == "ssl"
        assert decrypt_secret(row.password_encrypted) == "s3cret"
        assert row.updated_at is not None

        got = (await client.get(URL, headers=headers)).json()
        assert got == {
            "host": "mail.example.com",
            "port": 465,
            "username": "alpha",
            "password": "********",
            "from_address": "reports@example.com",
            "security": "ssl",
            "verify_certificate": True,
        }
        assert row.password_encrypted not in str(got)

    async def test_certificate_verification_can_be_turned_off_and_back_on(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body(verify_certificate=False))
        assert (await _saved(db_session)).verify_certificate is False
        assert (await client.get(URL, headers=headers)).json()["verify_certificate"] is False
        await client.put(URL, headers=headers, json=_body())
        assert (await _saved(db_session)).verify_certificate is True

    async def test_the_mask_keeps_the_saved_password(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        await client.put(URL, headers=headers, json=_body(password="********", from_address="other@example.com"))
        row = await _saved(db_session)
        assert decrypt_secret(row.password_encrypted) == "s3cret"
        assert row.from_address == "other@example.com"

    @pytest.mark.parametrize(
        ("legacy", "expected"),
        [
            ({"use_tls": True, "port": 587}, "starttls"),  # the combination that never connected
            ({"use_tls": True, "port": 465}, "ssl"),
            ({"use_tls": False, "port": 25}, "starttls"),
            ({"port": 587}, "starttls"),
        ],
    )
    async def test_a_page_from_before_the_upgrade_saves_what_it_meant(
        self, client, db_session, admin, legacy, expected
    ):
        headers = _sign_in(client, admin)
        resp = await client.put(URL, headers=headers, json=_body(security=..., **legacy))
        assert resp.status_code == 200, resp.text
        assert (await _saved(db_session)).security == expected

    @pytest.mark.parametrize(
        "bad",
        [
            {"host": "smtp://mail.example.com"},
            {"host": "mail.example.com/path"},
            {"host": "mail example.com"},
            {"host": "  "},
            {"port": 0},
            {"port": 70000},
            {"from_address": "reports"},
            {"from_address": "reports at example.com"},
            {"security": "tls"},
        ],
    )
    async def test_nonsense_is_refused_before_it_is_saved(self, client, db_session, admin, bad):
        headers = _sign_in(client, admin)
        resp = await client.put(URL, headers=headers, json=_body(**bad))
        assert resp.status_code == 422, resp.text
        assert (await db_session.execute(select(SmtpSettings))).scalars().first() is None


class TestTestConnection:
    async def test_reports_the_negotiated_tls_and_the_login(self, client, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            resp = await client.post(TEST_URL, headers=headers, json=_body(host="127.0.0.1", port=server.port))
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["security"] == "starttls"
        assert body["tls_version"] in {"TLSv1.2", "TLSv1.3"}
        assert body["certificate_verified"] is True
        assert body["login_tested"] is True
        assert [a.tls for a in server.auth_attempts] == [True]

    async def test_explains_the_reported_error_instead_of_repeating_it(self, client, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            resp = await client.post(
                TEST_URL, headers=headers, json=_body(host="127.0.0.1", port=server.port, security="ssl")
            )
        body = resp.json()
        assert body["ok"] is False
        assert "choose STARTTLS" in body["error"]

    async def test_a_self_signed_server_passes_only_when_verification_is_off(self, client, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.self_signed_context) as server:
            strict = (
                await client.post(TEST_URL, headers=headers, json=_body(host="127.0.0.1", port=server.port))
            ).json()
            lenient = (
                await client.post(
                    TEST_URL,
                    headers=headers,
                    json=_body(host="127.0.0.1", port=server.port, verify_certificate=False),
                )
            ).json()
        assert strict["ok"] is False
        assert "Allow a self-signed certificate" in strict["error"]
        assert lenient["ok"] is True
        assert lenient["certificate_verified"] is False
        assert lenient["tls_version"] in {"TLSv1.2", "TLSv1.3"}

    async def test_nothing_is_saved_by_a_test(self, client, db_session, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await client.post(TEST_URL, headers=headers, json=_body(host="127.0.0.1", port=server.port))
        assert (await db_session.execute(select(SmtpSettings))).scalars().first() is None


class TestWhoMay:
    async def test_an_account_without_the_smtp_menu_is_refused_everywhere(self, client, db_session):
        plain = await _user(db_session, "plain")
        headers = _sign_in(client, plain)
        assert (await client.get(URL, headers=headers)).status_code == 403
        assert (await client.put(URL, headers=headers, json=_body())).status_code == 403
        assert (await client.post(TEST_URL, headers=headers, json=_body())).status_code == 403

    async def test_a_read_only_super_admin_may_look_but_not_change_or_test(self, client, db_session):
        viewer = await _user(db_session, "viewer", roles=["read_only_super_admin"])
        headers = _sign_in(client, viewer)
        assert (await client.get(URL, headers=headers)).status_code == 200
        assert (await client.put(URL, headers=headers, json=_body())).status_code == 403
        assert (await client.post(TEST_URL, headers=headers, json=_body())).status_code == 403
