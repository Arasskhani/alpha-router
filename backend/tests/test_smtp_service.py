"""How an SMTP connection is secured, tested against a real server over real TLS.

The settings page offered one "Use TLS" switch. It meant TLS from the first
byte (port 465) and shipped switched on with port 587, where the server
speaks plain text first and upgrades with STARTTLS: the combination fails
with "[SSL: WRONG_VERSION_NUMBER]" and never worked. Switched off, it meant
"upgrade if offered", which carries on in plain text — password included —
when a server does not offer STARTTLS. These tests pin the replacement: an
explicit mode, a required upgrade, and an error that says what to change.
"""

from __future__ import annotations

import aiosmtplib
import pytest

from app.models.system import SmtpSettings
from app.services import smtp_service
from app.services.secret_crypto import encrypt_secret
from app.services.smtp_service import (
    SECURITY_NONE,
    SECURITY_SSL,
    SECURITY_STARTTLS,
    SmtpConnection,
    SmtpSendError,
    client_options,
    close_quietly,
    describe_smtp_error,
    negotiated_tls_version,
    open_smtp,
    security_from_legacy,
    send_email,
)
from tests.smtp_test_server import (
    MODE_PLAIN,
    MODE_SSL,
    MODE_STARTTLS,
    AuthAttempt,
    SmtpTestServer,
    TlsMaterial,
    make_tls_material,
)


@pytest.fixture(scope="module")
def tls(tmp_path_factory) -> TlsMaterial:
    return make_tls_material(tmp_path_factory.mktemp("smtp-tls"))


@pytest.fixture(autouse=True)
def _trust_the_test_ca(tls, monkeypatch):
    """The client trusts the test CA the way it trusts any CA; nothing is patched."""

    monkeypatch.setenv("SSL_CERT_FILE", str(tls.ca_path))
    # A hung handshake should fail a test in seconds, not in twenty.
    monkeypatch.setattr(smtp_service, "TIMEOUT_SECONDS", 5.0)


def _conn(server: SmtpTestServer, security: str, *, password: str | None = "s3cret", **kw) -> SmtpConnection:
    return SmtpConnection(
        host="127.0.0.1",
        port=server.port,
        security=security,
        username="alpha" if password is not None else None,
        password=password,
        **kw,
    )


class TestTheModes:
    def test_start_tls_is_never_left_to_the_library(self):
        # aiosmtplib's default for start_tls, None, is the silent plain-text fall-back.
        for security in (SECURITY_STARTTLS, SECURITY_SSL, SECURITY_NONE):
            options = client_options(security)
            assert isinstance(options["start_tls"], bool)
            assert isinstance(options["use_tls"], bool)
        assert client_options(SECURITY_STARTTLS) == {"use_tls": False, "start_tls": True}
        assert client_options(SECURITY_SSL) == {"use_tls": True, "start_tls": False}
        assert client_options(SECURITY_NONE) == {"use_tls": False, "start_tls": False}

    @pytest.mark.parametrize(
        ("use_tls", "port", "expected"),
        [
            (True, 587, SECURITY_STARTTLS),
            (True, 25, SECURITY_STARTTLS),
            (True, 2525, SECURITY_STARTTLS),
            (True, 465, SECURITY_SSL),
            (True, 2465, SECURITY_SSL),
            (True, None, SECURITY_SSL),
            (False, 587, SECURITY_STARTTLS),
            (False, 465, SECURITY_STARTTLS),
            (None, 587, SECURITY_STARTTLS),
        ],
    )
    def test_the_old_switch_keeps_what_it_evidently_meant(self, use_tls, port, expected):
        assert security_from_legacy(use_tls, port) == expected


class TestAgainstARealServer:
    async def test_the_reported_error_is_implicit_tls_on_a_starttls_port(self, tls):
        """The screenshot: "Use TLS" (implicit TLS) against port 587 (STARTTLS)."""

        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            conn = _conn(server, SECURITY_SSL)
            with pytest.raises(aiosmtplib.SMTPConnectError) as caught:
                await open_smtp(conn)
            assert "WRONG_VERSION_NUMBER" in str(caught.value)
            message = describe_smtp_error(caught.value, conn)
            assert "did not answer with TLS" in message
            assert "choose STARTTLS" in message
            assert server.auth_attempts == []

    async def test_starttls_on_the_same_server_logs_in_after_the_upgrade(self, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            client = await open_smtp(_conn(server, SECURITY_STARTTLS))
            assert negotiated_tls_version(client) in {"TLSv1.2", "TLSv1.3"}
            await close_quietly(client)
        assert server.auth_attempts == [AuthAttempt("alpha", "s3cret", tls=True)]
        assert ("STARTTLS", False) in server.commands
        assert all(tls_on for verb, tls_on in server.commands if verb == "AUTH")

    async def test_ssl_speaks_tls_from_the_first_byte(self, tls):
        async with SmtpTestServer(mode=MODE_SSL, tls_context=tls.server_context) as server:
            client = await open_smtp(_conn(server, SECURITY_SSL))
            await close_quietly(client)
        assert server.auth_attempts == [AuthAttempt("alpha", "s3cret", tls=True)]
        assert all(tls_on for _verb, tls_on in server.commands)

    async def test_starttls_against_an_implicit_tls_port_gives_up_and_says_why(self, tls, monkeypatch):
        monkeypatch.setattr(smtp_service, "TIMEOUT_SECONDS", 2.0)
        async with SmtpTestServer(mode=MODE_SSL, tls_context=tls.server_context) as server:
            conn = _conn(server, SECURITY_STARTTLS)
            with pytest.raises(aiosmtplib.SMTPTimeoutError) as caught:
                await open_smtp(conn)
        assert describe_smtp_error(caught.value, conn) == f"No answer from 127.0.0.1:{server.port} within 2 seconds."
        # On the port where this mistake happens in practice, the hint names the fix.
        on_465 = SmtpConnection(host="mail.example.com", port=465, security=SECURITY_STARTTLS)
        assert "choose SSL/TLS" in describe_smtp_error(caught.value, on_465)

    async def test_a_server_without_starttls_never_sees_the_password(self, tls):
        async with SmtpTestServer(
            mode=MODE_STARTTLS, tls_context=tls.server_context, advertise_starttls=False
        ) as server:
            conn = _conn(server, SECURITY_STARTTLS)
            with pytest.raises(aiosmtplib.SMTPException) as caught:
                await open_smtp(conn)
        assert server.auth_attempts == []
        message = describe_smtp_error(caught.value, conn)
        assert "does not offer STARTTLS, so nothing was sent" in message

    async def test_the_library_default_is_the_leak_this_module_rules_out(self, tls):
        """Why start_tls is never left at None: that is what "Use TLS" off did."""

        async with SmtpTestServer(
            mode=MODE_STARTTLS, tls_context=tls.server_context, advertise_starttls=False
        ) as server:
            client = aiosmtplib.SMTP(hostname="127.0.0.1", port=server.port, timeout=5)
            await client.connect()
            await client.login("alpha", "s3cret")
            await client.quit()
        assert server.auth_attempts == [AuthAttempt("alpha", "s3cret", tls=False)]

    async def test_none_is_plain_text_on_purpose(self):
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            client = await open_smtp(_conn(server, SECURITY_NONE))
            assert negotiated_tls_version(client) is None
            await close_quietly(client)
        assert server.auth_attempts == [AuthAttempt("alpha", "s3cret", tls=False)]

    async def test_an_untrusted_certificate_is_refused_with_the_reason(self, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.self_signed_context) as server:
            conn = _conn(server, SECURITY_STARTTLS)
            with pytest.raises(Exception) as caught:
                await open_smtp(conn)
        assert server.auth_attempts == []
        message = describe_smtp_error(caught.value, conn)
        assert message.startswith("The certificate of 127.0.0.1 could not be verified")

    async def test_a_wrong_password_is_named_as_such(self, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            conn = _conn(server, SECURITY_STARTTLS, password="wrong")
            with pytest.raises(aiosmtplib.SMTPAuthenticationError) as caught:
                await open_smtp(conn)
        assert describe_smtp_error(caught.value, conn).startswith("127.0.0.1 rejected the username or password (535")

    async def test_nothing_listening_is_a_connection_error_with_the_address(self, tls):
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            port = server.port
        conn = SmtpConnection(host="127.0.0.1", port=port, security=SECURITY_NONE)
        with pytest.raises(aiosmtplib.SMTPConnectError) as caught:
            await open_smtp(conn)
        assert describe_smtp_error(caught.value, conn).startswith(f"Could not connect to 127.0.0.1:{port}")


class TestSendEmail:
    async def _row(self, db_session, server: SmtpTestServer, security: str) -> SmtpSettings:
        row = SmtpSettings(
            host="127.0.0.1",
            port=server.port,
            username="alpha",
            password_encrypted=encrypt_secret("s3cret"),
            from_address="reports@example.com",
            security=security,
        )
        db_session.add(row)
        await db_session.commit()
        return row

    async def test_delivers_over_starttls_with_the_saved_settings(self, db_session, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await self._row(db_session, server, SECURITY_STARTTLS)
            await send_email(db_session, to_address="owner@example.com", subject="Weekly usage", body_text="hi")
        assert len(server.messages) == 1
        message = server.messages[0]
        assert message.tls is True
        assert message.mail_from == "reports@example.com"
        assert message.recipients == ("owner@example.com",)
        assert b"Subject: Weekly usage" in message.data
        assert server.auth_attempts == [AuthAttempt("alpha", "s3cret", tls=True)]

    async def test_a_failure_is_reported_as_the_readable_reason(self, db_session, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await self._row(db_session, server, SECURITY_SSL)
            with pytest.raises(SmtpSendError) as caught:
                await send_email(db_session, to_address="owner@example.com", subject="s", body_text="b")
        assert "choose STARTTLS" in str(caught.value)
        assert server.messages == []


class TestDescribeSmtpError:
    conn = SmtpConnection(host="mail.example.com", port=587, security=SECURITY_STARTTLS)

    def test_a_refusal_carries_the_code(self):
        exc = aiosmtplib.SMTPResponseException(550, "Relaying denied")
        assert describe_smtp_error(exc, self.conn) == "mail.example.com:587 refused the request (550 Relaying denied)."

    def test_a_dropped_connection_on_465_suggests_ssl(self):
        conn = SmtpConnection(host="mail.example.com", port=465, security=SECURITY_STARTTLS)
        message = describe_smtp_error(aiosmtplib.SMTPServerDisconnected("gone"), conn)
        assert message.startswith("mail.example.com:465 closed the connection unexpectedly.")
        assert "choose SSL/TLS" in message

    def test_anything_else_keeps_the_library_text(self):
        assert describe_smtp_error(RuntimeError("odd"), self.conn) == "odd"
