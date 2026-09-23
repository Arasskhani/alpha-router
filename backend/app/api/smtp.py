"""Dedicated SMTP server configuration (admin only)."""

from __future__ import annotations

import datetime
import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_smtp, require_smtp_write
from app.database import get_db
from app.models.system import SmtpSettings
from app.models.user import User
from app.services.secret_crypto import encrypt_secret
from app.services.smtp_service import (
    SECURITY_STARTTLS,
    SmtpConnection,
    close_quietly,
    describe_smtp_error,
    negotiated_tls_version,
    normalize_security,
    open_smtp,
    security_from_legacy,
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
    }


@router.put("")
async def save_smtp(body: SmtpIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_smtp_write)):
    row = (await db.execute(select(SmtpSettings).limit(1))).scalars().first()
    if not row:
        row = SmtpSettings(host=body.host, port=body.port, from_address=body.from_address)
        db.add(row)
    row.host = body.host
    row.port = body.port
    row.username = body.username
    typed = body.typed_password()
    if typed is not None:
        row.password_encrypted = encrypt_secret(typed)
    row.from_address = body.from_address
    row.security = body.resolved_security()
    row.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await db.commit()
    return {"ok": True, "security": row.security}


@router.post("/test")
async def test_smtp(body: SmtpIn, _: User = Depends(require_smtp_write)):
    """Connect, secure the connection as configured and, when a password was
    typed, log in. Nothing is sent and nothing is saved."""

    conn = SmtpConnection(
        host=body.host,
        port=body.port,
        security=body.resolved_security(),
        username=body.username,
        password=body.typed_password(),
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
        "login_tested": bool(conn.username and conn.password),
    }
