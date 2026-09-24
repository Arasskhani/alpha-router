"""The SMTP settings API: what is saved, what is read back, what Test reports.

The connection itself is exercised against a real local SMTP server (see
``tests/smtp_test_server.py``); these tests are about the administrative
surface: the explicit security mode, a page loaded before it existed, input
that must never be saved, and who may change any of it.
"""

from __future__ import annotations

import email
import email.policy
import json

import aiosmtplib
import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.security import SecurityAuditEvent
from app.models.system import SmtpSettings
from app.models.user import User
from app.services import smtp_service
from app.services.secret_crypto import decrypt_secret
from app.services.user_role_service import set_user_roles
from tests.smtp_test_server import MODE_STARTTLS, SmtpTestServer, TlsMaterial, make_tls_material

URL = "/api/admin/smtp"
TEST_URL = "/api/admin/smtp/test"
TEST_EMAIL_URL = "/api/admin/smtp/test-email"


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

    @pytest.mark.parametrize(
        "sender",
        [
            "Alpharouter <reports@example.com>",
            '"Reports, Alpharouter" <reports@example.com>',
            "گزارش‌ها <reports@example.com>",
        ],
    )
    async def test_a_from_address_may_carry_a_name(self, client, db_session, admin, sender):
        headers = _sign_in(client, admin)
        resp = await client.put(URL, headers=headers, json=_body(from_address=sender))
        assert resp.status_code == 200, resp.text
        assert (await _saved(db_session)).from_address == sender

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
            # Pass a simple pattern, but the email package cannot put them in a header.
            {"from_address": "reports@["},
            {"from_address": "reports@example.com;x"},
            # A name needs the address in angle brackets, and one mailbox only.
            {"from_address": "Alpharouter reports@example.com"},
            {"from_address": "Alpharouter <reports@example.com"},
            {"from_address": "Alpha <a@example.com>, Beta <b@example.com>"},
            {"from_address": "Alpharouter <>"},
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

    async def test_a_server_that_hangs_up_after_the_login_is_reported_not_a_crash(
        self, client, admin, tls, monkeypatch
    ):
        def hung_up(_client):
            raise aiosmtplib.SMTPServerDisconnected("Server not connected")

        # What reading the TLS version does once the server has closed the connection.
        monkeypatch.setattr("app.api.smtp.negotiated_tls_version", hung_up)
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            resp = await client.post(TEST_URL, headers=headers, json=_body(host="127.0.0.1", port=server.port))
        assert resp.status_code == 200
        assert resp.json() == {"ok": False, "error": f"127.0.0.1:{server.port} closed the connection unexpectedly."}

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
        assert (await client.post(TEST_EMAIL_URL, headers=headers)).status_code == 403

    async def test_a_read_only_super_admin_may_look_but_not_change_or_test(self, client, db_session):
        viewer = await _user(db_session, "viewer", roles=["read_only_super_admin"])
        headers = _sign_in(client, viewer)
        assert (await client.get(URL, headers=headers)).status_code == 200
        assert (await client.put(URL, headers=headers, json=_body())).status_code == 403
        assert (await client.post(TEST_URL, headers=headers, json=_body())).status_code == 403
        assert (await client.post(TEST_EMAIL_URL, headers=headers)).status_code == 403


class TestThePasswordStaysWithItsServer:
    """A saved password is only used with the server and username it was saved
    for, and never over a less secure connection than the one it was saved with.

    The page never shows it; without this rule, anyone allowed to edit the
    page could learn it by saving a host of their own, or by switching to no
    encryption (or an unchecked certificate) and listening on the network.
    """

    SERVER_OR_USERNAME = (
        "Enter the password again: a saved password is only used with the server and username it was saved for."
    )
    LESS_SECURE = (
        "Enter the password again: a saved password is never sent over a less secure connection "
        "than the one it was saved for."
    )

    async def _save_first(self, client, headers, **overrides):
        resp = await client.put(URL, headers=headers, json=_body(**overrides))
        assert resp.status_code == 200, resp.text

    async def test_a_new_host_needs_the_password_typed_again(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await self._save_first(client, headers)
        resp = await client.put(URL, headers=headers, json=_body(host="collector.example.net", password="********"))
        assert resp.status_code == 400
        assert resp.json()["detail"] == self.SERVER_OR_USERNAME
        assert (await _saved(db_session)).host == "mail.example.com"

    async def test_another_username_needs_the_password_typed_again(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await self._save_first(client, headers)
        resp = await client.put(URL, headers=headers, json=_body(username="bob", password="********"))
        assert resp.status_code == 400
        assert resp.json()["detail"] == self.SERVER_OR_USERNAME
        assert (await _saved(db_session)).username == "alpha"

    @pytest.mark.parametrize("weaker", [{"security": "none", "port": 25}, {"verify_certificate": False}])
    async def test_a_less_secure_connection_needs_the_password_typed_again(self, client, db_session, admin, weaker):
        headers = _sign_in(client, admin)
        await self._save_first(client, headers)
        resp = await client.put(URL, headers=headers, json=_body(password="********", **weaker))
        assert resp.status_code == 400
        assert resp.json()["detail"] == self.LESS_SECURE
        row = await _saved(db_session)
        assert (row.security, row.verify_certificate) == ("starttls", True)

        typed = await client.put(URL, headers=headers, json=_body(password="s3cret", **weaker))
        assert typed.status_code == 200, typed.text

    @pytest.mark.parametrize(
        ("first", "then"),
        [
            ({"verify_certificate": False}, {}),
            ({"security": "none", "port": 25}, {}),
            ({"security": "none", "port": 25}, {"verify_certificate": False}),
        ],
    )
    async def test_a_more_secure_connection_keeps_the_password(self, client, db_session, admin, first, then):
        headers = _sign_in(client, admin)
        await self._save_first(client, headers, **first)
        resp = await client.put(URL, headers=headers, json=_body(password="********", **then))
        assert resp.status_code == 200, resp.text
        assert decrypt_secret((await _saved(db_session)).password_encrypted) == "s3cret"

    async def test_with_the_password_typed_the_new_host_is_saved(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await self._save_first(client, headers)
        resp = await client.put(URL, headers=headers, json=_body(host="smtp.example.net", password="n3w"))
        assert resp.status_code == 200
        row = await _saved(db_session)
        assert (row.host, decrypt_secret(row.password_encrypted)) == ("smtp.example.net", "n3w")

    @pytest.mark.parametrize("same", [{"host": "MAIL.example.com."}, {"port": 465, "security": "ssl"}])
    async def test_the_same_server_keeps_its_password(self, client, db_session, admin, same):
        headers = _sign_in(client, admin)
        await self._save_first(client, headers)
        resp = await client.put(URL, headers=headers, json=_body(password="********", **same))
        assert resp.status_code == 200, resp.text
        assert decrypt_secret((await _saved(db_session)).password_encrypted) == "s3cret"

    async def test_a_stored_secret_is_not_taken_for_a_new_password(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await self._save_first(client, headers)
        stolen = (await _saved(db_session)).password_encrypted
        resp = await client.put(URL, headers=headers, json=_body(host="collector.example.net", password=stolen))
        assert resp.status_code == 400
        assert resp.json()["detail"] == (
            "That is an encrypted value from Alpharouter's own database, not a password. Type the SMTP password itself."
        )
        row = await _saved(db_session)
        assert (row.host, decrypt_secret(row.password_encrypted)) == ("mail.example.com", "s3cret")

    async def test_a_password_that_only_looks_like_a_token_is_saved_as_typed(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        lookalike = "gAAAAAB" + "Q" * 93
        resp = await client.put(URL, headers=headers, json=_body(password=lookalike))
        assert resp.status_code == 200, resp.text
        assert decrypt_secret((await _saved(db_session)).password_encrypted) == lookalike

    async def test_no_username_means_no_login_and_the_password_goes(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await self._save_first(client, headers)
        resp = await client.put(
            URL, headers=headers, json=_body(host="relay.internal", username="", password="********")
        )
        assert resp.status_code == 200, resp.text
        row = await _saved(db_session)
        assert row.username is None and row.password_encrypted is None
        assert (await client.get(URL, headers=headers)).json()["password"] is None

    async def test_test_logs_in_with_the_saved_password_on_its_own_server(self, client, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await self._save_first(client, headers, host="127.0.0.1", port=server.port)
            resp = await client.post(
                TEST_URL, headers=headers, json=_body(host="127.0.0.1", port=server.port, password="********")
            )
        body = resp.json()
        assert body["ok"] is True
        assert (body["login_tested"], body["login_skipped"]) == (True, None)
        assert [(a.password, a.tls) for a in server.auth_attempts] == [("s3cret", True)]

    @pytest.mark.parametrize("elsewhere", [{"host": "localhost"}, {"username": "someone-else"}])
    async def test_test_never_takes_the_saved_password_elsewhere(self, client, admin, tls, elsewhere):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await self._save_first(client, headers, host="127.0.0.1", port=server.port)
            probe = _body(host="127.0.0.1", port=server.port, password="********")
            probe.update(elsewhere)
            resp = await client.post(TEST_URL, headers=headers, json=probe)
        body = resp.json()
        # The connection is still tested, just without a login.
        assert body["ok"] is True
        assert (body["login_tested"], body["login_skipped"]) == (False, "saved_for_another_server")
        assert server.auth_attempts == []

    @pytest.mark.parametrize("weaker", [{"security": "none"}, {"verify_certificate": False}])
    async def test_test_never_sends_the_saved_password_over_a_less_secure_connection(self, client, admin, tls, weaker):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await self._save_first(client, headers, host="127.0.0.1", port=server.port)
            probe = _body(host="127.0.0.1", port=server.port, password="********", **weaker)
            resp = await client.post(TEST_URL, headers=headers, json=probe)
        body = resp.json()
        assert body["ok"] is True
        assert (body["login_tested"], body["login_skipped"]) == (False, "less_secure_connection")
        assert server.auth_attempts == []

    async def test_test_with_nothing_to_log_in_with_says_so(self, client, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            resp = await client.post(
                TEST_URL, headers=headers, json=_body(host="127.0.0.1", port=server.port, password=None)
            )
        body = resp.json()
        assert (body["ok"], body["login_tested"], body["login_skipped"]) == (True, False, "no_password")


class TestTheAuditTrail:
    async def _events(self, db_session) -> list[dict]:
        db_session.expire_all()
        rows = (
            (
                await db_session.execute(
                    select(SecurityAuditEvent)
                    .where(SecurityAuditEvent.action == "smtp_settings_changed")
                    .order_by(SecurityAuditEvent.id)
                )
            )
            .scalars()
            .all()
        )
        return [{"actor": r.actor_username, "type": r.resource_type, **json.loads(r.detail_json)} for r in rows]

    async def test_the_first_save_records_every_field_and_that_a_password_was_set(self, client, db_session, admin):
        username = admin.username
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        (event,) = await self._events(db_session)
        assert event["actor"] == username
        assert event["type"] == "smtp"
        assert event["created"] is True
        assert event["password"] == "changed"
        assert event["changes"]["host"] == {"from": None, "to": "mail.example.com"}
        assert event["changes"]["security"] == {"from": None, "to": "starttls"}

    async def test_turning_verification_off_is_recorded_on_its_own(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        # A less secure connection needs the password typed again.
        await client.put(URL, headers=headers, json=_body(verify_certificate=False))
        event = (await self._events(db_session))[-1]
        assert event["created"] is False
        assert event["changes"] == {"verify_certificate": {"from": True, "to": False}}
        assert event["password"] == "changed"

    async def test_a_save_that_keeps_the_password_says_so(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        await client.put(URL, headers=headers, json=_body(password="********", from_address="alerts@example.com"))
        event = (await self._events(db_session))[-1]
        assert event["changes"] == {"from_address": {"from": "reports@example.com", "to": "alerts@example.com"}}
        assert event["password"] == "unchanged"

    async def test_a_save_that_changes_nothing_records_nothing(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        await client.put(URL, headers=headers, json=_body(password="********"))
        assert len(await self._events(db_session)) == 1

    async def test_removing_the_login_records_the_password_as_removed(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        await client.put(URL, headers=headers, json=_body(username="", password="********"))
        event = (await self._events(db_session))[-1]
        assert event["password"] == "removed"
        assert event["changes"]["username"] == {"from": "alpha", "to": None}

    async def test_the_password_never_reaches_the_trail(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body(password="Sup3r-S3cret-Value"))
        await client.put(URL, headers=headers, json=_body(password="An0ther-S3cret-Value"))
        stored = (await _saved(db_session)).password_encrypted
        db_session.expire_all()
        raw = [r.detail_json for r in (await db_session.execute(select(SecurityAuditEvent))).scalars()]
        assert raw
        for detail in raw:
            assert "Sup3r-S3cret-Value" not in detail
            assert "An0ther-S3cret-Value" not in detail
            assert stored not in detail

    async def test_a_refused_save_records_nothing(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        await client.put(URL, headers=headers, json=_body(host="collector.example.net", password="********"))
        assert len(await self._events(db_session)) == 1


class TestTheTestEmail:
    """The "Send test email to me" button: a real message, sent with the saved
    settings, to the administrator's own address and to nobody else."""

    async def test_a_real_message_reaches_the_administrator_through_the_saved_settings(self, client, admin, tls):
        address, username = admin.email, admin.username
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            saved = await client.put(URL, headers=headers, json=_body(host="127.0.0.1", port=server.port))
            assert saved.status_code == 200, saved.text
            resp = await client.post(TEST_EMAIL_URL, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "to": address}

        (message,) = server.messages
        assert (message.mail_from, message.recipients, message.tls) == ("reports@example.com", (address,), True)
        assert [(a.password, a.tls) for a in server.auth_attempts] == [("s3cret", True)]
        parsed = email.message_from_bytes(message.data, policy=email.policy.default)
        assert parsed["Subject"] == "Alpharouter test email"
        assert parsed["To"] == address
        text = parsed.get_content()
        assert username in text
        assert f"127.0.0.1:{server.port} with STARTTLS." in text

    async def test_a_named_sender_keeps_its_name_and_the_envelope_gets_the_address(self, client, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await client.put(
                URL,
                headers=headers,
                json=_body(host="127.0.0.1", port=server.port, from_address="Alpharouter <reports@example.com>"),
            )
            resp = await client.post(TEST_EMAIL_URL, headers=headers)
        assert resp.json()["ok"] is True
        (message,) = server.messages
        assert message.mail_from == "reports@example.com"
        parsed = email.message_from_bytes(message.data, policy=email.policy.default)
        assert parsed["From"] == "Alpharouter <reports@example.com>"

    async def test_the_body_says_when_the_certificate_was_not_checked(self, client, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.self_signed_context) as server:
            await client.put(
                URL, headers=headers, json=_body(host="127.0.0.1", port=server.port, verify_certificate=False)
            )
            resp = await client.post(TEST_EMAIL_URL, headers=headers)
        assert resp.json()["ok"] is True
        (message,) = server.messages
        text = email.message_from_bytes(message.data, policy=email.policy.default).get_content()
        assert "with STARTTLS (certificate not verified)." in text

    async def test_the_recipient_is_never_taken_from_the_request(self, client, admin, tls):
        address = admin.email
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await client.put(URL, headers=headers, json=_body(host="127.0.0.1", port=server.port))
            resp = await client.post(
                TEST_EMAIL_URL,
                headers=headers,
                json={"to": "someone@elsewhere.example", "to_address": "someone@elsewhere.example"},
            )
        assert resp.json() == {"ok": True, "to": address}
        assert [m.recipients for m in server.messages] == [(address,)]

    async def test_a_failure_comes_back_explained(self, client, admin, tls):
        headers = _sign_in(client, admin)
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await client.put(URL, headers=headers, json=_body(host="127.0.0.1", port=server.port, security="ssl"))
            resp = await client.post(TEST_EMAIL_URL, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "choose STARTTLS" in body["error"]
        assert server.messages == []

    async def test_a_from_address_saved_before_it_was_checked_is_explained(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        row = await _saved(db_session)
        row.from_address = "reports@["
        await db_session.commit()
        resp = await client.post(TEST_EMAIL_URL, headers=headers)
        assert resp.status_code == 200
        assert resp.json() == {
            "ok": False,
            "error": "The message could not be sent from reports@[: check that it is a plain email address.",
        }

    async def test_nothing_is_sent_before_the_settings_are_saved(self, client, admin):
        headers = _sign_in(client, admin)
        resp = await client.post(TEST_EMAIL_URL, headers=headers)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Save the SMTP settings first."

    async def test_an_account_without_an_address_is_told_so(self, client, db_session, admin, tls):
        headers = _sign_in(client, admin)
        await client.put(URL, headers=headers, json=_body())
        nobody = await _user(db_session, "no_address", roles=["super_admin"])
        nobody.email = None
        await db_session.commit()
        resp = await client.post(TEST_EMAIL_URL, headers=_sign_in(client, nobody))
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Your account has no email address to send the test to."
