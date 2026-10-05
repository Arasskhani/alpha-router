"""Self sign-up and forgotten-password reset by an emailed code.

Settings (Admin -> Authentication -> Email sign-up) are kept like the other
sign-in methods, as the ``email_signup`` row of ``auth_providers``:

- ``enabled``: people may create their own account;
- ``allowed_domains``: the email domains that may (empty: any address);
- ``default_plan_id``: the plan a new account gets (none: no plan, so it
  cannot spend until an administrator assigns one);
- ``reset_enabled``: people with a local account may reset a forgotten
  password by email.

Both need SMTP (Admin -> SMTP Server). The codes are rows of
:class:`app.models.email_verification.EmailVerification`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import PRODUCT_NAME
from app.config import get_settings
from app.models.auth_provider import AuthProviderConfig
from app.models.budget import BudgetPlan
from app.models.email_verification import PURPOSE_PASSWORD_RESET, PURPOSE_SIGNUP, EmailVerification
from app.models.system import SmtpSettings
from app.models.user import User

PROVIDER = "email_signup"

#: How long an emailed code may be typed.
CODE_TTL = dt.timedelta(minutes=10)
#: How long after the code was accepted the last step may be finished.
COMPLETE_TTL = dt.timedelta(minutes=30)
#: Wrong codes before the row is ended and a new code must be asked for.
MAX_ATTEMPTS = 5
#: The least time between two codes for one address and purpose.
RESEND_COOLDOWN = dt.timedelta(seconds=60)
#: Rows older than this are removed when new ones are made.
KEEP_ROWS = dt.timedelta(days=1)

CODE_DIGITS = 6
USERNAME_MIN = 3
USERNAME_MAX = 64
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
#: Names a person may not take, besides the bootstrap administrator's.
_RESERVED_USERNAMES = frozenset(
    {"admin", "administrator", "root", "system", "support", "security", "gateway-service", "alpharouter"}
)


@dataclass
class EmailSignupSettings:
    enabled: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    default_plan_id: int | None = None
    reset_enabled: bool = False

    def as_config(self) -> dict[str, Any]:
        return {
            "allowed_domains": list(self.allowed_domains),
            "default_plan_id": self.default_plan_id,
            "reset_enabled": bool(self.reset_enabled),
        }


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


# ── Settings ───────────────────────────────────────────────────────────────


async def load_email_signup_settings(db: AsyncSession) -> EmailSignupSettings:
    row = await db.get(AuthProviderConfig, PROVIDER)
    if row is None:
        return EmailSignupSettings()
    try:
        raw = json.loads(str(row.config_json or "{}"))
    except ValueError:
        raw = {}
    plan = raw.get("default_plan_id")
    return EmailSignupSettings(
        enabled=bool(row.enabled),
        allowed_domains=[str(d) for d in raw.get("allowed_domains") or [] if str(d).strip()],
        default_plan_id=int(plan) if isinstance(plan, int) or (isinstance(plan, str) and plan.isdigit()) else None,
        reset_enabled=bool(raw.get("reset_enabled")),
    )


def normalize_domains(values: list[str]) -> list[str]:
    """Lowercased, without a leading @ or spaces, each a valid domain; raises ValueError naming a bad one."""
    out: list[str] = []
    for value in values:
        domain = str(value or "").strip().lower().lstrip("@").strip()
        if not domain:
            continue
        if not _DOMAIN_RE.match(domain):
            raise ValueError(f"'{value}' is not a domain name (for example: example.com).")
        if domain not in out:
            out.append(domain)
    return out


async def smtp_configured(db: AsyncSession) -> bool:
    row = (await db.execute(select(SmtpSettings).limit(1))).scalars().first()
    return bool(row and (row.host or "").strip() and (row.from_address or "").strip())


async def save_email_signup_settings(db: AsyncSession, settings: EmailSignupSettings) -> EmailSignupSettings:
    """Check and store the settings (not committed: the caller commits with its audit row)."""
    settings.allowed_domains = normalize_domains(settings.allowed_domains)
    if settings.default_plan_id is not None and await db.get(BudgetPlan, settings.default_plan_id) is None:
        raise ValueError("That plan does not exist.")
    if (settings.enabled or settings.reset_enabled) and not await smtp_configured(db):
        raise ValueError("Set up the SMTP server first (Admin -> SMTP Server): the codes are sent by email.")
    row = await db.get(AuthProviderConfig, PROVIDER)
    payload = json.dumps(settings.as_config())
    if row is None:
        db.add(AuthProviderConfig(provider=PROVIDER, enabled=settings.enabled, config_json=payload))
    else:
        row.enabled = settings.enabled  # type: ignore[assignment]
        row.config_json = payload  # type: ignore[assignment]
    return settings


async def methods_available(db: AsyncSession) -> dict[str, bool]:
    """What the sign-in page offers: each needs its switch and SMTP."""
    settings = await load_email_signup_settings(db)
    if not (settings.enabled or settings.reset_enabled):
        return {"email_signup": False, "password_reset": False}
    smtp = await smtp_configured(db)
    return {"email_signup": settings.enabled and smtp, "password_reset": settings.reset_enabled and smtp}


# ── Addresses and names ───────────────────────────────────────────────────


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def valid_email(email: str) -> bool:
    from app.services.smtp_service import is_sendable_address

    return bool(email) and len(email) <= 254 and bool(_EMAIL_RE.match(email)) and is_sendable_address(email)


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1]


def domain_allowed(email: str, settings: EmailSignupSettings) -> bool:
    return not settings.allowed_domains or email_domain(email) in settings.allowed_domains


async def user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(func.lower(User.email) == email))).scalars().first()


def username_problem(username: str) -> str | None:
    """Why a username cannot be chosen (its form, or a reserved name), or None."""
    if len(username) < USERNAME_MIN or len(username) > USERNAME_MAX:
        return f"A username is {USERNAME_MIN} to {USERNAME_MAX} characters."
    if not _USERNAME_RE.match(username):
        return "A username uses lowercase letters, digits, dots, hyphens and underscores, and starts with a letter or digit."
    reserved = _RESERVED_USERNAMES | {(get_settings().admin_username or "").strip().lower()}
    if username in reserved:
        return "That username is reserved. Choose another."
    return None


def suggested_username(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    cleaned = re.sub(r"[^a-z0-9._-]", "", local).lstrip("._-")
    return cleaned[:USERNAME_MAX]


# ── Codes ──────────────────────────────────────────────────────────────────


def _code_hash(token: str, code: str) -> str:
    key = (get_settings().secret_key or "").encode()
    return hmac.new(key, f"{token}:{code}".encode(), hashlib.sha256).hexdigest()


def _new_code() -> str:
    return str(secrets.randbelow(10**CODE_DIGITS)).zfill(CODE_DIGITS)


async def seconds_until_resend(db: AsyncSession, *, email: str, purpose: str) -> int:
    """How long before another code may be sent to this address for this purpose (0: now)."""
    last = (
        await db.execute(
            select(func.max(EmailVerification.created_at)).where(
                EmailVerification.email == email, EmailVerification.purpose == purpose
            )
        )
    ).scalar_one_or_none()
    if last is None:
        return 0
    wait = (last + RESEND_COOLDOWN - utcnow()).total_seconds()
    return max(0, int(wait + 0.999))


async def issue_code(
    db: AsyncSession,
    *,
    email: str,
    purpose: str,
    user_id: int | None = None,
    ip: str | None = None,
) -> tuple[EmailVerification, str]:
    """End the address's earlier codes not yet entered for this purpose and make a new one (not committed)."""
    now = utcnow()
    await db.execute(delete(EmailVerification).where(EmailVerification.created_at < now - KEEP_ROWS))
    await db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.email == email,
            EmailVerification.purpose == purpose,
            EmailVerification.consumed_at.is_(None),
            # A code already entered stays usable for its last step: asking for codes for someone
            # else's address must not end the step they are on.
            EmailVerification.verified_at.is_(None),
        )
        .values(consumed_at=now)
    )
    token = secrets.token_urlsafe(32)
    code = _new_code()
    row = EmailVerification(
        token=token,
        purpose=purpose,
        email=email,
        user_id=user_id,
        code_hash=_code_hash(token, code),
        attempts=0,
        expires_at=now + CODE_TTL,
        created_at=now,
        ip=(ip or "")[:64] or None,
    )
    db.add(row)
    await db.flush()
    return row, code


class CodeError(Exception):
    """A code step that cannot go on; ``reason`` is the auth event reason code, ``str()`` the message.

    ``email`` and ``user_id`` name what the code was for, when the token was found, so a run of wrong
    codes shows in Sign-in Activity against the address or the account being tried.
    """

    def __init__(
        self,
        reason: str,
        message: str,
        status: int = 400,
        *,
        row: EmailVerification | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.status = status
        self.email: str | None = str(row.email) if row is not None else None
        self.user_id: int | None = int(row.user_id) if row is not None and row.user_id is not None else None


async def _live_row(db: AsyncSession, token: str, purpose: str) -> EmailVerification:
    row = (
        (
            await db.execute(
                select(EmailVerification).where(EmailVerification.token == token, EmailVerification.purpose == purpose)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise CodeError("code_invalid", "This code is no longer valid. Ask for a new one.")
    if row.consumed_at is not None:
        raise CodeError("code_invalid", "This code is no longer valid. Ask for a new one.", row=row)
    return row


async def _count_try(db: AsyncSession, row: EmailVerification) -> int | None:
    """Count one try in the database, before the code is compared: the number of tries so far, or None
    when the code has none left (or was used meanwhile).

    One UPDATE that reads and raises the count where the row is, so parallel guesses each take a try.
    Reading the count into Python and writing it back let thirty concurrent guesses be compared while
    the stored count rose by one.
    """
    counted = await db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.id == row.id,
            EmailVerification.consumed_at.is_(None),
            EmailVerification.attempts < MAX_ATTEMPTS,
        )
        .values(attempts=EmailVerification.attempts + 1)
        .returning(EmailVerification.attempts)
        .execution_options(synchronize_session=False)
    )
    value = counted.scalar_one_or_none()
    return int(value) if value is not None else None


async def check_code(db: AsyncSession, *, token: str, code: str, purpose: str) -> EmailVerification:
    """Accept the code for this token (marks it verified), or raise CodeError (counting the try; not committed).

    Every try is counted, the right one included, so a code is compared at most ``MAX_ATTEMPTS`` times.
    """
    row = await _live_row(db, (token or "").strip(), purpose)
    now = utcnow()
    if row.verified_at is not None:
        return row
    if row.expires_at <= now:
        row.consumed_at = now  # type: ignore[assignment]
        raise CodeError("code_expired", "This code has expired. Ask for a new one.", row=row)
    tries = await _count_try(db, row)
    if tries is None:
        raise CodeError("code_invalid", "Too many wrong codes. Ask for a new one.", row=row)
    typed = re.sub(r"\s+", "", code or "")
    if hmac.compare_digest(_code_hash(str(row.token), typed), str(row.code_hash)):
        row.verified_at = now  # type: ignore[assignment]
        return row
    left = MAX_ATTEMPTS - tries
    if left <= 0:
        row.consumed_at = now  # type: ignore[assignment]
        raise CodeError("code_invalid", "Too many wrong codes. Ask for a new one.", row=row)
    raise CodeError("code_invalid", f"That code is not right. {left} {'try' if left == 1 else 'tries'} left.", row=row)


async def consume(db: AsyncSession, row: EmailVerification) -> None:
    """Mark the row used, once: a second request finishing with the same token at the same moment
    finds it already used and is refused (not committed)."""
    used = await db.execute(
        update(EmailVerification)
        .where(EmailVerification.id == row.id, EmailVerification.consumed_at.is_(None))
        .values(consumed_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if used.rowcount != 1:  # type: ignore[attr-defined]
        raise CodeError("code_invalid", "This code is no longer valid. Ask for a new one.", row=row)


async def verified_row(db: AsyncSession, *, token: str, purpose: str) -> EmailVerification:
    """The row whose code was accepted and whose last step is still open, or raise CodeError."""
    row = await _live_row(db, (token or "").strip(), purpose)
    if row.verified_at is None:
        raise CodeError("code_invalid", "Enter the code from the email first.", row=row)
    if row.verified_at + COMPLETE_TTL <= utcnow():
        row.consumed_at = utcnow()  # type: ignore[assignment]
        raise CodeError("code_expired", "This step has expired. Start again.", row=row)
    return row


# ── The emails ─────────────────────────────────────────────────────────────


async def send_code_email(db: AsyncSession, *, email: str, code: str, purpose: str) -> None:
    from app.services.smtp_service import send_email

    minutes = int(CODE_TTL.total_seconds() // 60)
    if purpose == PURPOSE_SIGNUP:
        subject = f"Your {PRODUCT_NAME} sign-up code"
        lead = f"Use this code to finish creating your {PRODUCT_NAME} account:"
        tail = "If you did not ask to create an account, ignore this email: nothing is created without the code."
    else:
        # Never the code in a subject: a phone's lock screen shows subjects to anyone nearby.
        subject = f"Your {PRODUCT_NAME} password reset code"
        lead = f"Use this code to reset the password of your {PRODUCT_NAME} account:"
        tail = "If you did not ask to reset your password, ignore this email: your password stays as it is."
    body = f"{lead}\n\n    {code}\n\nThe code works for {minutes} minutes and only once.\n\n{tail}\n"
    await send_email(db, to_address=email, subject=subject, body_text=body)


__all__ = [
    "CODE_TTL",
    "COMPLETE_TTL",
    "MAX_ATTEMPTS",
    "PROVIDER",
    "PURPOSE_PASSWORD_RESET",
    "PURPOSE_SIGNUP",
    "CodeError",
    "EmailSignupSettings",
    "check_code",
    "consume",
    "domain_allowed",
    "issue_code",
    "load_email_signup_settings",
    "methods_available",
    "normalize_domains",
    "normalize_email",
    "save_email_signup_settings",
    "seconds_until_resend",
    "send_code_email",
    "smtp_configured",
    "suggested_username",
    "user_by_email",
    "username_problem",
    "valid_email",
    "verified_row",
]
