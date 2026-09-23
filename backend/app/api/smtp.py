"""Dedicated SMTP server configuration (admin only)."""

from __future__ import annotations

import datetime
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_smtp, require_smtp_write
from app.database import get_db
from app.models.system import SmtpSettings
from app.models.user import User
from app.services.secret_crypto import decrypt_secret, encrypt_secret
from app.services.smtp_service import (
    SECURITY_NONE,
    SECURITY_SSL,
    SECURITY_STARTTLS,
    SmtpConnection,
    SmtpNotConfiguredError,
    SmtpSendError,
    close_quietly,
    describe_smtp_error,
    negotiated_tls_version,
    normalize_security,
    open_smtp,
    same_server,
    security_from_legacy,
    send_email,
)

router = APIRouter(prefix="/api/admin/smtp", tags=["smtp"])

#: What the page shows in place of a saved password, and sends back to mean
#: "keep the one you have".
PASSWORD_MASK = "********"

_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+$")


class SmtpIn(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1024)
    from_address: str = Field(min_length=3, max_length=255)
    security: Literal["starttls", "ssl", "none"] | None = None
    #: Off accepts a self-signed (or any other) certificate.
    verify_certificate: bool = True
    #: Sent by a page loaded before ``security`` existed. Read only when
    #: ``security`` is absent, with the same rule the migration applied.
    use_tls: bool | None = None

    @field_validator("host")
    @classmethod
    def _plain_host_name(cls, value: str) -> str:
        host = value.strip()
        if not host or "://" in host or "/" in host or any(ch.isspace() for ch in host):
            raise ValueError("Enter the server's host name only, for example mail.example.com.")
        return host

    @field_validator("from_address")
    @classmethod
    def _an_address(cls, value: str) -> str:
        address = value.strip()
        if not _ADDRESS.match(address):
            raise ValueError("The From address must be an email address, for example reports@example.com.")
        return address

    @field_validator("username")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        return text or None

    def resolved_security(self) -> str:
        if self.security is not None:
            return self.security
        if self.use_tls is None:
            return SECURITY_STARTTLS
        return security_from_legacy(self.use_tls, self.port)

    def typed_password(self) -> str | None:
        """The password as typed, or None when the field was left alone."""

        if not self.password or self.password == PASSWORD_MASK:
            return None
        return self.password


@router.get("")
async def get_smtp(db: AsyncSession = Depends(get_db), _: User = Depends(require_smtp)):
    row = (await db.execute(select(SmtpSettings).limit(1))).scalars().first()
    if not row:
        return None
    return {
        "host": row.host,
        "port": row.port,
        "username": row.username,
        "password": PASSWORD_MASK if row.password_encrypted else None,
        "from_address": row.from_address,
        "security": normalize_security(row.security),
        "verify_certificate": row.verify_certificate is not False,
    }


#: Refused when the host changes and the password was left alone.
PASSWORD_BOUND_TO_SERVER = (
    "Enter the password again: a saved password is only ever sent to the server it was saved for."
)


async def _saved_row(db: AsyncSession) -> SmtpSettings | None:
    return (await db.execute(select(SmtpSettings).limit(1))).scalars().first()


#: What the audit trail compares between two saves. Never the password.
_AUDITED_FIELDS = ("host", "port", "username", "from_address", "security", "verify_certificate")


def _snapshot(row: SmtpSettings | None) -> dict[str, object]:
    if row is None:
        return {}
    return {name: getattr(row, name) for name in _AUDITED_FIELDS}


@router.put("")
async def save_smtp(
    body: SmtpIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_smtp_write),
):
    """Save the settings.

    A saved password stays with the server it was saved for. Pointing the
    settings at another host without typing it again is refused: otherwise
    anyone allowed to edit this page could learn the mailbox password, which
    the page never shows, by saving their own host and waiting for the next
    report email to log in there. Clearing the username means no login at
    all, and the saved password is discarded.

    Every save that changes something is audited as ``smtp_settings_changed``
    with the fields before and after. These settings decide where report
    emails, API keys sent to their owners and security alerts go, and on
    what terms: turning certificate verification off or choosing no TLS is
    exactly the change an auditor needs to find. The password itself is only
    ever recorded as changed or removed.
    """

    from app.services.client_ip import resolve_client_ip
    from app.services.security_audit import log_security_event

    row = await _saved_row(db)
    before = _snapshot(row)
    had_password = row is not None and bool(row.password_encrypted)
    typed = body.typed_password()
    if (
        row is not None
        and row.password_encrypted
        and typed is None
        and body.username is not None
        and not same_server(body.host, row.host)
    ):
        raise HTTPException(400, detail=PASSWORD_BOUND_TO_SERVER)
    if not row:
        row = SmtpSettings(host=body.host, port=body.port, from_address=body.from_address)
        db.add(row)
    row.host = body.host
    row.port = body.port
    row.username = body.username
    if body.username is None:
        row.password_encrypted = None
    elif typed is not None:
        row.password_encrypted = encrypt_secret(typed)
    row.from_address = body.from_address
    row.security = body.resolved_security()
    row.verify_certificate = body.verify_certificate
    row.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    after = _snapshot(row)
    changes = {
        name: {"from": before.get(name), "to": after[name]}
        for name in _AUDITED_FIELDS
        if before.get(name) != after[name]
    }
    if typed is not None and body.username is not None:
        password = "changed"
    elif had_password and not row.password_encrypted:
        password = "removed"
    else:
        password = "unchanged"
    if changes or password != "unchanged":
        await log_security_event(
            db,
            actor=admin,
            actor_ip=resolve_client_ip(request),
            action="smtp_settings_changed",
            resource_type="smtp",
            detail={"created": not before, "changes": changes, "password": password},
        )
    await db.commit()
    return {"ok": True, "security": row.security}


@router.post("/test")
async def test_smtp(body: SmtpIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_smtp_write)):
    """Connect with the values on the form, secure the connection as chosen
    and log in. Nothing is sent and nothing is saved.

    The password is the one typed, or else the saved one - but the saved one
    only for the server and username it was saved for, the same rule Save
    applies. Otherwise the connection is still tested, without a login, and
    ``login_skipped`` says why.
    """

    typed = body.typed_password()
    password = typed
    skipped: str | None = None
    if body.username is not None and typed is None:
        saved = await _saved_row(db)
        if saved is None or not saved.password_encrypted:
            skipped = "no_password"
        elif not same_server(body.host, saved.host) or body.username != (saved.username or "").strip():
            skipped = "saved_for_another_server"
        else:
            try:
                password = decrypt_secret(saved.password_encrypted)
            except Exception as exc:  # noqa: BLE001 -- reported to the administrator
                return {"ok": False, "error": f"The saved SMTP password could not be decrypted: {exc}"}

    conn = SmtpConnection(
        host=body.host,
        port=body.port,
        security=body.resolved_security(),
        username=body.username,
        password=password,
        verify_certificate=body.verify_certificate,
    )
    try:
        client = await open_smtp(conn)
    except Exception as exc:  # noqa: BLE001 -- the reason is reported to the administrator
        return {"ok": False, "error": describe_smtp_error(exc, conn)}
    tls_version = negotiated_tls_version(client)
    await close_quietly(client)
    return {
        "ok": True,
        "security": conn.security,
        "tls_version": tls_version,
        "certificate_verified": conn.certificate_checked,
        "login_tested": bool(conn.username and conn.password),
        "login_skipped": skipped,
    }


TEST_EMAIL_SUBJECT = "Alpharouter test email"

_SECURITY_NAMES = {SECURITY_STARTTLS: "STARTTLS", SECURITY_SSL: "SSL/TLS", SECURITY_NONE: "no encryption"}


def _test_email_text(row: SmtpSettings, admin: User, sent_at: datetime.datetime) -> str:
    security = normalize_security(row.security)
    how = _SECURITY_NAMES[security]
    if security != SECURITY_NONE and row.verify_certificate is False:
        how += " (certificate not verified)"
    return (
        "This is a test email from Alpharouter.\n\n"
        f"{admin.username} sent it from Admin > SMTP Server at {sent_at:%Y-%m-%d %H:%M} UTC, "
        f"through {row.host}:{row.port} with {how}.\n\n"
        "If it arrived, the saved SMTP settings work: scheduled reports, API keys sent to "
        "their owners and security alerts are sent the same way.\n"
    )


@router.post("/test-email")
async def send_test_email(db: AsyncSession = Depends(get_db), admin: User = Depends(require_smtp_write)):
    """Send a short email to the signed-in administrator with the saved settings.

    Test connection proves the server answers and accepts the login; this
    proves a message actually leaves, by the same path as scheduled reports
    and alerts. The recipient is always the administrator's own address,
    never one from the request, so the button cannot mail anyone else.
    """

    address = (admin.email or "").strip()
    if not address:
        raise HTTPException(400, detail="Your account has no email address to send the test to.")
    row = await _saved_row(db)
    if row is None or not (row.host or "").strip():
        raise HTTPException(400, detail="Save the SMTP settings first.")
    text = _test_email_text(row, admin, datetime.datetime.now(datetime.UTC))
    try:
        await send_email(db, to_address=address, subject=TEST_EMAIL_SUBJECT, body_text=text)
    except SmtpNotConfiguredError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except SmtpSendError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "to": address}
