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
    is_sendable_address,
    is_sendable_from,
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
        assert "Allow a self-signed certificate" in message

    async def test_a_certificate_for_another_name_is_not_excused_as_self_signed(self, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.wrong_name_context) as server:
            conn = _conn(server, SECURITY_STARTTLS)
            with pytest.raises(Exception) as caught:
                await open_smtp(conn)
        assert server.auth_attempts == []
        message = describe_smtp_error(caught.value, conn)
        assert message.startswith("The certificate of 127.0.0.1 could not be verified (IP address mismatch")
        assert "It was issued for another name" in message
        assert "Allow a self-signed certificate" not in message

    async def test_an_expired_certificate_is_named_as_such(self, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.expired_context) as server:
            conn = _conn(server, SECURITY_STARTTLS)
            with pytest.raises(Exception) as caught:
                await open_smtp(conn)
        message = describe_smtp_error(caught.value, conn)
        assert "(certificate has expired)" in message
        assert "renewed on the mail server" in message
        assert "Allow a self-signed certificate" not in message

    async def test_a_self_signed_certificate_is_accepted_when_verification_is_off(self, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.self_signed_context) as server:
            conn = _conn(server, SECURITY_STARTTLS, verify_certificate=False)
            client = await open_smtp(conn)
            assert negotiated_tls_version(client) in {"TLSv1.2", "TLSv1.3"}
            await close_quietly(client)
        # Still encrypted: only the identity check was given up.
        assert server.auth_attempts == [AuthAttempt("alpha", "s3cret", tls=True)]
        assert conn.certificate_checked is False

    async def test_the_same_goes_for_ssl(self, tls):
        async with SmtpTestServer(mode=MODE_SSL, tls_context=tls.self_signed_context) as server:
            client = await open_smtp(_conn(server, SECURITY_SSL, verify_certificate=False))
            await close_quietly(client)
        assert server.auth_attempts == [AuthAttempt("alpha", "s3cret", tls=True)]

    async def test_not_verifying_never_means_falling_back_to_plain_text(self, tls):
        async with SmtpTestServer(
            mode=MODE_STARTTLS, tls_context=tls.self_signed_context, advertise_starttls=False
        ) as server:
            with pytest.raises(aiosmtplib.SMTPException):
                await open_smtp(_conn(server, SECURITY_STARTTLS, verify_certificate=False))
        assert server.auth_attempts == []

    def test_without_tls_there_is_no_certificate_to_check(self):
        assert SmtpConnection(host="h", port=25, security=SECURITY_NONE).certificate_checked is False
        assert SmtpConnection(host="h", port=587, security=SECURITY_STARTTLS).certificate_checked is True

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
    async def _row(self, db_session, server: SmtpTestServer, security: str, *, verify: bool = True) -> SmtpSettings:
        row = SmtpSettings(
            host="127.0.0.1",
            port=server.port,
            username="alpha",
            password_encrypted=encrypt_secret("s3cret"),
            from_address="reports@example.com",
            security=security,
            verify_certificate=verify,
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

    async def test_a_saved_self_signed_exception_is_honoured(self, db_session, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.self_signed_context) as server:
            await self._row(db_session, server, SECURITY_STARTTLS, verify=False)
            await send_email(db_session, to_address="owner@example.com", subject="s", body_text="b")
        assert [m.tls for m in server.messages] == [True]

    @pytest.mark.parametrize(
        ("login", "hint"),
        [
            (True, "The login worked, but this account may not send there"),
            (False, "It does not relay mail without a login: set a username and password it accepts"),
        ],
    )
    async def test_a_refused_recipient_is_named_with_the_server_s_reason(self, db_session, tls, login, hint):
        async with SmtpTestServer(
            mode=MODE_STARTTLS, tls_context=tls.server_context, refuse_recipients=frozenset({"owner@elsewhere.example"})
        ) as server:
            row = await self._row(db_session, server, SECURITY_STARTTLS)
            if not login:
                row.username = None
                await db_session.commit()
            with pytest.raises(SmtpSendError) as caught:
                await send_email(db_session, to_address="owner@elsewhere.example", subject="s", body_text="b")
        assert str(caught.value).startswith(
            "127.0.0.1 refused to deliver to owner@elsewhere.example (554 5.7.1 <owner@elsewhere.example>: "
            f"Relay access denied). {hint}"
        )
        assert len(server.auth_attempts) == (1 if login else 0)
        assert server.messages == []

    async def test_a_refused_sender_is_named_as_the_from_address(self, db_session, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context, refuse_sender=True) as server:
            await self._row(db_session, server, SECURITY_STARTTLS)
            with pytest.raises(SmtpSendError) as caught:
                await send_email(db_session, to_address="owner@example.com", subject="s", body_text="b")
        assert str(caught.value).startswith("127.0.0.1 refused the From address reports@example.com (553")
        assert "Use an address this account may send as." in str(caught.value)

    async def test_an_address_the_email_package_cannot_use_is_reported_before_connecting(self, db_session, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            row = await self._row(db_session, server, SECURITY_STARTTLS)
            row.from_address = "reports@["
            await db_session.commit()
            with pytest.raises(SmtpSendError) as caught:
                await send_email(db_session, to_address="owner@example.com", subject="s", body_text="b")
        assert "could not be addressed from reports@[ to owner@example.com" in str(caught.value)
        assert server.commands == []

    async def test_a_line_break_in_the_subject_does_not_stop_the_message(self, db_session, tls):
        async with SmtpTestServer(mode=MODE_STARTTLS, tls_context=tls.server_context) as server:
            await self._row(db_session, server, SECURITY_STARTTLS)
            await send_email(
                db_session, to_address="owner@example.com", subject="failed sign-ins for '!x\r\nBcc: y'", body_text="b"
            )
        (message,) = server.messages
        assert b"Subject: failed sign-ins for '!x Bcc: y'\r\n" in message.data
        assert b"\r\nBcc:" not in message.data

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

    def test_a_certificate_reason_is_found_in_the_text_too(self):
        exc = OSError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1000)"
        )
        assert describe_smtp_error(exc, self.conn) == (
            "The certificate of mail.example.com could not be verified (certificate has expired). "
            "It has to be renewed on the mail server."
        )

    def test_other_certificate_failures_do_not_suggest_giving_up_the_check(self):
        exc = OSError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unsupported certificate purpose (_ssl.c:1000)"
        )
        assert describe_smtp_error(exc, self.conn) == (
            "The certificate of mail.example.com could not be verified (unsupported certificate purpose)."
        )

    def test_refused_data_is_called_the_message(self):
        exc = aiosmtplib.SMTPDataError(552, "Message size exceeds fixed limit")
        assert describe_smtp_error(exc, self.conn) == (
            "mail.example.com:587 refused the message (552 Message size exceeds fixed limit)."
        )

    @pytest.mark.parametrize(
        ("value", "sendable"),
        [
            ("reports@example.com", True),
            ("reports@مثال.ایران", True),
            ("reports@[", False),
            ("reports@example.com;x", False),
            ("x@y>", False),
        ],
    )
    def test_which_addresses_can_go_in_a_header(self, value, sendable):
        assert is_sendable_address(value) is sendable

    @pytest.mark.parametrize(
        ("value", "sendable"),
        [
            ("reports@example.com", True),
            ("Alpharouter <reports@example.com>", True),
            ('"Doe, Jane" <jane@example.com>', True),
            ("<reports@example.com>", True),
            ("reports", False),
            ("reports@", False),
            ("reports@[", False),
            ("Alpharouter <reports@[>", False),
            ("Alpharouter reports@example.com", False),
            ("Alpha, Router <r@example.com>", False),
            ("Alpharouter <reports>", False),
        ],
    )
    def test_which_senders_can_go_in_a_from_header(self, value, sendable):
        assert is_sendable_from(value) is sendable

    def test_anything_else_keeps_the_library_text(self):
        assert describe_smtp_error(RuntimeError("odd"), self.conn) == "odd"
