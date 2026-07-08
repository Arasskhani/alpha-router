"""Send email using admin-configured SMTP settings."""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SmtpSettings


class SmtpNotConfiguredError(Exception):
    pass


class SmtpSendError(Exception):
    pass


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

    msg = EmailMessage()
    msg["From"] = row.from_address
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body_text)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)

    recipients = [to_address, *cc_addrs]

    try:
        client = aiosmtplib.SMTP(hostname=row.host, port=row.port, use_tls=bool(row.use_tls))
        await client.connect()
        if row.username and row.password_encrypted:
            await client.login(row.username, row.password_encrypted)
        await client.send_message(msg, recipients=recipients)
        await client.quit()
    except SmtpNotConfiguredError:
        raise
    except Exception as exc:
        raise SmtpSendError(str(exc)) from exc
