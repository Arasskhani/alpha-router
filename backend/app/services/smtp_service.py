"""Send email using admin-configured SMTP settings.

How a connection is secured is one setting, ``security``, because SMTP has
two incompatible ways of using TLS and a client that guesses between them
either cannot connect or leaks:

* ``starttls`` (usually port 587): connect in plain text, then upgrade with
  STARTTLS. The upgrade is *required*. aiosmtplib's own default
  (``start_tls=None``) upgrades only when the server offers it and otherwise
  carries on in plain text — password included — so it is never used here.
* ``ssl`` (usually port 465): TLS from the first byte, often called SMTPS.
* ``none``: no TLS, chosen on purpose, for a relay on a trusted network.

Certificates are verified unless ``verify_certificate`` is off, for a server
with a self-signed certificate: the connection is still encrypted, but any
certificate is accepted, so the server's identity is no longer checked.

The settings page used to have one "Use TLS" switch that meant ``ssl``, and
it shipped switched on with port 587: a combination that can never connect
and fails with "[SSL: WRONG_VERSION_NUMBER]". ``describe_smtp_error`` turns
that and the other common failures into a sentence an administrator can act
on.
"""

from __future__ import annotations

import asyncio
import re
import ssl
from dataclasses import dataclass
from email.errors import HeaderParseError
from email.headerregistry import Address, HeaderRegistry
from email.message import EmailMessage

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SmtpSettings
from app.services.secret_crypto import decrypt_secret

SECURITY_STARTTLS = "starttls"
SECURITY_SSL = "ssl"
SECURITY_NONE = "none"
SECURITY_MODES: tuple[str, ...] = (SECURITY_STARTTLS, SECURITY_SSL, SECURITY_NONE)

#: The port each mode normally uses; the settings page suggests these.
STANDARD_PORTS: dict[str, int] = {SECURITY_STARTTLS: 587, SECURITY_SSL: 465, SECURITY_NONE: 25}

#: Ports that speak plain text first and upgrade with STARTTLS.
_STARTTLS_PORTS = frozenset({25, 587, 2525})

#: Per network operation (connect, each command). aiosmtplib's own default is
#: a minute, which is a long time to stare at a "Test connection" button.
TIMEOUT_SECONDS = 20.0


#: What the email package raises for an address it cannot use: several
#: unrelated types, AttributeError among them (for "reports@[", say).
_ADDRESS_ERRORS = (ValueError, IndexError, AttributeError, HeaderParseError)


def is_sendable_address(value: str) -> bool:
    """Whether ``value`` is one plain address the email package can put in a header."""

    try:
        Address(addr_spec=value)
    except _ADDRESS_ERRORS:
        return False
    return True


_HEADERS = HeaderRegistry()


def is_sendable_from(value: str) -> bool:
    """Whether ``value`` is one mailbox for a From header, with or without a
    name: "reports@example.com" or "Alpharouter <reports@example.com>"."""

    try:
        header = _HEADERS("From", value)
        addresses = header.addresses
    except _ADDRESS_ERRORS:
        return False
    if header.defects or len(addresses) != 1:
        return False
    address = addresses[0]
    return bool(address.username and address.domain) and is_sendable_address(address.addr_spec)


class SmtpNotConfiguredError(Exception):
    pass


class SmtpSendError(Exception):
    pass


@dataclass(frozen=True)
class SmtpConnection:
    """Everything needed to open one SMTP session."""

    host: str
    port: int
    security: str = SECURITY_STARTTLS
    username: str | None = None
    password: str | None = None
    #: Off accepts any certificate (a self-signed one included). Meaningless
    #: without TLS.
    verify_certificate: bool = True

    @property
    def certificate_checked(self) -> bool:
        return self.security != SECURITY_NONE and self.verify_certificate


def normalize_security(value: str | None) -> str:
    text = (value or "").strip().lower()
    return text if text in SECURITY_MODES else SECURITY_STARTTLS


def security_from_legacy(use_tls: bool | None, port: int | None) -> str:
    """What the old "Use TLS" switch meant, for a page loaded before ``security``.

    Kept in step with revision ``4ce0678f5e1c``, which applies the same rule to
    the saved row.
    """

    if use_tls and (port is None or port not in _STARTTLS_PORTS):
        return SECURITY_SSL
    return SECURITY_STARTTLS


def same_server(a: str | None, b: str | None) -> bool:
    """Whether two host names name the same server, as far as spelling goes."""

    def canonical(host: str | None) -> str:
        return (host or "").strip().lower().rstrip(".")

    return canonical(a) == canonical(b)


def protection_level(security: str, verify_certificate: bool) -> int:
    """How well a connection keeps a password from other ears: 2 over TLS with
    a verified certificate, 1 over TLS without verification (anyone able to
    intercept can pose as the server), 0 in plain text."""

    if security == SECURITY_NONE:
        return 0
    return 2 if verify_certificate else 1


def client_options(security: str) -> dict[str, bool]:
    """aiosmtplib's two TLS flags for a security mode.

    ``start_tls`` is always an explicit ``True`` or ``False``: its default,
    ``None``, is the silent fall-back to plain text this module exists to
    rule out.
    """

    if security == SECURITY_SSL:
        return {"use_tls": True, "start_tls": False}
    if security == SECURITY_NONE:
        return {"use_tls": False, "start_tls": False}
    return {"use_tls": False, "start_tls": True}


def connection_from_row(row: SmtpSettings) -> SmtpConnection:
    password = decrypt_secret(row.password_encrypted) if row.username and row.password_encrypted else None
    return SmtpConnection(
        host=(row.host or "").strip(),
        port=int(row.port or STANDARD_PORTS[normalize_security(row.security)]),
        security=normalize_security(row.security),
        username=(row.username or "").strip() or None,
        password=password,
        verify_certificate=row.verify_certificate is not False,
    )


async def open_smtp(conn: SmtpConnection, *, login: bool = True) -> aiosmtplib.SMTP:
    """Connect, secure the connection as configured, and log in when there is
    a username and password. The caller owns the returned client."""

    client = aiosmtplib.SMTP(
        hostname=conn.host,
        port=conn.port,
        timeout=TIMEOUT_SECONDS,
        validate_certs=conn.verify_certificate,
        **client_options(conn.security),
    )
    await client.connect()
    if login and conn.username and conn.password:
        try:
            await client.login(conn.username, conn.password)
        except BaseException:
            client.close()
            raise
    return client


def negotiated_tls_version(client: aiosmtplib.SMTP) -> str | None:
    """The negotiated protocol, such as "TLSv1.3", or None without TLS."""

    ssl_object = client.get_transport_info("ssl_object")
    version = ssl_object.version() if ssl_object is not None else None
    return str(version) if version else None


async def close_quietly(client: aiosmtplib.SMTP) -> None:
    """QUIT, or just drop the connection if the server is already gone."""

    try:
        await client.quit()
    except Exception:  # noqa: BLE001 -- the message was sent or the error is already being reported
        client.close()


def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen and len(seen) < 6:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


_VERIFY_FAILED = re.compile(r"certificate verify failed: ([^(\]]+)")

#: OpenSSL's words for a certificate that no trusted authority signed - the
#: case "Allow a self-signed certificate" exists for.
_UNKNOWN_ISSUER = ("self-signed", "self signed", "issuer certificate", "unable to verify the first certificate")


def _describe_certificate_failure(chain: list[BaseException], text: str, conn: SmtpConnection) -> str:
    cert_error = next((e for e in chain if isinstance(e, ssl.SSLCertVerificationError)), None)
    reason = (getattr(cert_error, "verify_message", "") or "").strip()
    if not reason:
        match = _VERIFY_FAILED.search(text)
        reason = match.group(1).strip() if match else ""
    reason = reason.rstrip(".")
    lowered = reason.lower()
    message = f"The certificate of {conn.host} could not be verified" + (f" ({reason})." if reason else ".")
    if "mismatch" in lowered:
        # A valid certificate for another name: switching verification off
        # would hide the mistake, not fix it.
        return message + " It was issued for another name: enter the server's name exactly as its certificate gives it."
    if "expired" in lowered:
        return message + " It has to be renewed on the mail server."
    if "not yet valid" in lowered:
        return message + " Check that the clocks of this server and of the mail server are right."
    if not reason or any(words in lowered for words in _UNKNOWN_ISSUER):
        return (
            message + " If this server uses a self-signed certificate and you trust the network between you, "
            "turn on “Allow a self-signed certificate”."
        )
    return message


def _describe_refused_recipients(exc: aiosmtplib.SMTPRecipientsRefused, conn: SmtpConnection) -> str:
    refused = "; ".join(f"{r.recipient} ({r.code} {r.message})" for r in exc.recipients)
    message = f"{conn.host} refused to deliver to {refused}."
    if "relay" not in refused.lower():
        return message
    if conn.username and conn.password:
        return message + " The login worked, but this account may not send there: ask the mail server's administrator."
    return message + (
        " It does not relay mail without a login: set a username and password it accepts, "
        "or ask its administrator to allow relaying from this server."
    )


def describe_smtp_error(exc: BaseException, conn: SmtpConnection) -> str:
    """A sentence that says what went wrong and what to change."""

    where = f"{conn.host}:{conn.port}"
    chain = _chain(exc)
    text = " ".join(str(e) for e in chain)

    if any(isinstance(e, ssl.SSLCertVerificationError) for e in chain) or "CERTIFICATE_VERIFY_FAILED" in text:
        return _describe_certificate_failure(chain, text, conn)

    if "WRONG_VERSION_NUMBER" in text:
        if conn.security == SECURITY_SSL:
            return (
                f"{where} did not answer with TLS. Port {conn.port} most likely expects STARTTLS: "
                "choose STARTTLS, or use port 465 for SSL/TLS."
            )
        return f"TLS could not be negotiated with {where}: {exc}"

    if isinstance(exc, aiosmtplib.SMTPAuthenticationError):
        return f"{conn.host} rejected the username or password ({exc.code} {exc.message})."

    if "starttls extension not supported" in text.lower():
        return (
            f"{where} does not offer STARTTLS, so nothing was sent. Use SSL/TLS (usually port 465), "
            "or choose None only for a relay on a trusted network."
        )

    if isinstance(
        exc, (aiosmtplib.SMTPTimeoutError, asyncio.TimeoutError, TimeoutError, aiosmtplib.SMTPServerDisconnected)
    ):
        hint = ""
        if conn.security != SECURITY_SSL and conn.port == STANDARD_PORTS[SECURITY_SSL]:
            hint = " Port 465 normally expects TLS from the first byte: choose SSL/TLS."
        if isinstance(exc, aiosmtplib.SMTPServerDisconnected):
            return f"{where} closed the connection unexpectedly.{hint}"
        return f"No answer from {where} within {int(TIMEOUT_SECONDS)} seconds.{hint}"

    if isinstance(exc, aiosmtplib.SMTPRecipientsRefused):
        return _describe_refused_recipients(exc, conn)

    if isinstance(exc, aiosmtplib.SMTPSenderRefused):
        return (
            f"{conn.host} refused the From address {exc.sender} ({exc.code} {exc.message}). "
            "Use an address this account may send as."
        )

    if isinstance(exc, aiosmtplib.SMTPDataError):
        return f"{where} refused the message ({exc.code} {exc.message})."

    if isinstance(exc, aiosmtplib.SMTPResponseException):
        return f"{where} refused the request ({exc.code} {exc.message})."

    if isinstance(exc, (aiosmtplib.SMTPConnectError, OSError)):
        return f"Could not connect to {where}: {exc}"

    return str(exc) or exc.__class__.__name__


async def _load_smtp_row(db: AsyncSession) -> SmtpSettings:
    row = (await db.execute(select(SmtpSettings).limit(1))).scalars().first()
    if not row or not (row.host or "").strip():
        raise SmtpNotConfiguredError("SMTP is not configured. Set it up under Admin → SMTP.")
    return row


async def send_email(
    db: AsyncSession,
    *,
    to_address: str,
    subject: str,
    body_text: str,
    cc: list[str] | None = None,
) -> None:
    row = await _load_smtp_row(db)
    to_address = (to_address or "").strip()
    if not to_address:
        raise SmtpSendError("Recipient email is missing.")

    cc_addrs = [a.strip() for a in (cc or []) if (a or "").strip()]
    cc_addrs = [a for a in cc_addrs if a.lower() != to_address.lower()]
    recipients = [to_address, *cc_addrs]

    msg = EmailMessage()
    try:
        msg["From"] = row.from_address
        msg["To"] = to_address
        if cc_addrs:
            msg["Cc"] = ", ".join(cc_addrs)
    except _ADDRESS_ERRORS as exc:
        # A From address saved before it was checked, or a malformed address
        # on an account: say so instead of failing every caller with a crash.
        raise SmtpSendError(
            f"The message could not be addressed from {row.from_address} to {', '.join(recipients)}: "
            "check that these are plain email addresses."
        ) from exc
    # A subject is one line, and some carry text from outside - the account
    # name a failed sign-in tried, for one. The email package refuses a line
    # break in a header with ValueError, which would stop the caller (the
    # sign-in alert job, and every alert after the one that tripped it).
    msg["Subject"] = " ".join(subject.splitlines())
    try:
        msg.set_content(body_text)
    except ValueError as exc:
        raise SmtpSendError(f"The message could not be built: {exc}") from exc
    try:
        conn = connection_from_row(row)
    except Exception as exc:
        raise SmtpSendError(f"The saved SMTP password could not be decrypted: {exc}") from exc

    try:
        client = await open_smtp(conn)
        try:
            await client.send_message(msg, recipients=recipients)
        finally:
            await close_quietly(client)
    except Exception as exc:
        raise SmtpSendError(describe_smtp_error(exc, conn)) from exc
