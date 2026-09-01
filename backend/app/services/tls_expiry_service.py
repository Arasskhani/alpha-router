"""Daily TLS certificate expiry notices."""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.security import TlsCertificate
from app.models.system import SystemSetting
from app.models.user import User, UserRoleAssignment
from app.services.observability import increment
from app.services.rbac import SUPER_ADMIN_SLUG
from app.services.smtp_service import SmtpNotConfiguredError, SmtpSendError, send_email

logger = logging.getLogger(__name__)

NOTICE_DAYS = (30, 14, 7, 1)
KEY_LAST_NOTICE = "tls_expiry_last_notice"


async def _notice_recipients(db: AsyncSession) -> list[str]:
    rows = (
        await db.execute(
            select(User.email)
            .join(UserRoleAssignment, UserRoleAssignment.user_id == User.id)
            .where(
                UserRoleAssignment.role_slug == SUPER_ADMIN_SLUG,
                User.email.isnot(None),
                User.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    return sorted({(email or "").strip() for email in rows if (email or "").strip()})


async def notify_expiring_certificates(db: AsyncSession, *, now: datetime.datetime | None = None) -> dict[str, int]:
    moment = now or datetime.datetime.utcnow()
    today = moment.date().isoformat()
    row = (
        await db.execute(select(TlsCertificate).where(TlsCertificate.is_active.is_(True)))
    ).scalars().first()
    if row is None or row.not_after is None:
        return {"sent": 0}
    days = int((row.not_after - moment).total_seconds() // 86400)
    should_notify = days <= 0 or days in NOTICE_DAYS
    if not should_notify:
        return {"sent": 0}
    last = await db.get(SystemSetting, KEY_LAST_NOTICE)
    stamp = f"{row.sha256_fingerprint}:{today}:{days}"
    if last and last.value == stamp:
        return {"sent": 0}
    recipients = await _notice_recipients(db)
    subject = (
        "Alpharouter TLS certificate has expired"
        if days <= 0
        else f"Alpharouter TLS certificate expires in {days} day{'s' if days != 1 else ''}"
    )
    body = (
        f"The active TLS certificate ({row.label}) expires on {row.not_after.isoformat()}Z.\n"
        f"Fingerprint: {row.sha256_fingerprint}\n"
        "Upload a replacement in Admin → Security → Security Settings.\n"
    )
    sent = 0
    smtp_failed = False
    for address in recipients:
        try:
            await send_email(db, to_address=address, subject=subject, body_text=body)
            sent += 1
        except (SmtpNotConfiguredError, SmtpSendError) as exc:
            logger.warning("TLS expiry notice not sent to %s: %s", address, exc)
            smtp_failed = True
            break
    if smtp_failed:
        return {"sent": sent, "days_remaining": days}
    if not recipients:
        logger.warning("TLS expiry notice skipped: no Super Admin email addresses.")
        return {"sent": 0, "days_remaining": days}
    if last:
        last.value = stamp
    else:
        db.add(SystemSetting(key=KEY_LAST_NOTICE, value=stamp))
    increment("tls_expiry_notice")
    return {"sent": sent, "days_remaining": days}
