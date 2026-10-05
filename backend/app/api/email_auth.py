"""Create an account, or reset a forgotten password, with a code sent by email.

Sign-up (when an administrator turned it on, Admin -> Authentication -> Email
sign-up):

1. ``POST /api/auth/signup/start``: the email address; a 6-digit code is sent
   to it and the browser gets an opaque ``token`` for the next steps. An
   address that already has an account is told so (and whether its password
   can be reset by email) instead of getting a code.
2. ``POST /api/auth/signup/verify``: the token and the code.
3. ``POST /api/auth/signup/complete``: the token, a username nobody has and a
   password that meets the policy. The account is made, active, with the
   default plan, and the person is signed in.

Password reset (when turned on, for local accounts only): the same three
steps under ``/api/auth/password-reset``; the last sets the new password and
signs the account out everywhere, and the person then signs in with it.

Every refusal answers ``{"detail": {"code", "message", ...}}`` and is written
to Sign-in Activity with its reason.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.database import get_db
from app.models.auth_event import (
    EVENT_PASSWORD_RESET,
    EVENT_PASSWORD_RESET_FAILED,
    EVENT_SESSION_REVOKED,
    EVENT_SIGNUP_COMPLETED,
    EVENT_SIGNUP_FAILED,
)
from app.models.email_verification import PURPOSE_PASSWORD_RESET, PURPOSE_SIGNUP
from app.models.user import User
from app.services.auth_events_service import method_for, record_auth_event
from app.services.client_ip import resolve_client_ip
from app.services.email_signup_service import (
    CODE_TTL,
    RESEND_COOLDOWN,
    CodeError,
    check_code,
    consume,
    domain_allowed,
    issue_code,
    load_email_signup_settings,
    normalize_email,
    send_code_email,
    smtp_configured,
    suggested_username,
    user_by_email,
    username_problem,
    valid_email,
    verified_row,
)
from app.services.password_policy import PasswordPolicyError, validate_password
from app.services.rate_limit import check_rate_limit
from app.services.username_norm import normalize_username, username_taken_ci

router = APIRouter(prefix="/api/auth", tags=["auth-email"])

#: Codes sent from one address, and to one email, per window.
START_PER_IP = (10, 600)
START_PER_EMAIL = (5, 3600)
#: Codes typed, names checked and last steps, per address and minute.
VERIFY_PER_IP = (30, 60)
CHECK_PER_IP = (60, 60)
COMPLETE_PER_IP = (20, 60)


class EmailIn(BaseModel):
    email: str = Field(max_length=320)


class CodeIn(BaseModel):
    token: str = Field(max_length=128)
    code: str = Field(max_length=32)


class UsernameIn(BaseModel):
    token: str = Field(max_length=128)
    username: str = Field(max_length=128)


class SignupCompleteIn(BaseModel):
    token: str = Field(max_length=128)
    username: str = Field(max_length=128)
    password: str = Field(max_length=256)
    display_name: str | None = Field(default=None, max_length=255)


class ResetCompleteIn(BaseModel):
    token: str = Field(max_length=128)
    password: str = Field(max_length=256)


def _refuse(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


async def _limit(request: Request, key: str, window: tuple[int, int]) -> None:
    limit, seconds = window
    await check_rate_limit(key, limit=limit, window_seconds=seconds)


def _started(row: Any) -> dict[str, Any]:
    return {
        "token": str(row.token),
        "email": str(row.email),
        "expires_in": int(CODE_TTL.total_seconds()),
        "resend_in": int(RESEND_COOLDOWN.total_seconds()),
        "code_length": 6,
    }


async def _failed(
    request: Request,
    event_type: str,
    reason: str,
    *,
    user: User | None = None,
    username: str | None = None,
    detail: str | None = None,
) -> None:
    await record_auth_event(
        event_type=event_type,
        user=user,
        username=username,
        reason_code=reason,
        reason_detail=detail,
        auth_method=method_for(user) if user is not None else "local",
        request=request,
    )


async def _limited(request: Request, event_type: str, keys: list[tuple[str, tuple[int, int]]], who: str | None) -> None:
    try:
        for key, window in keys:
            await _limit(request, key, window)
    except HTTPException as exc:
        if exc.status_code == 429:
            await _failed(request, event_type, "rate_limited", username=who)
            raise _refuse(429, "rate_limited", "Too many attempts. Wait a few minutes and try again.") from exc
        raise


async def _send_or_refuse(db: AsyncSession, request: Request, event_type: str, row: Any, code: str) -> None:
    from app.services.smtp_service import SmtpNotConfiguredError, SmtpSendError

    try:
        await send_code_email(db, email=str(row.email), code=code, purpose=str(row.purpose))
    except (SmtpNotConfiguredError, SmtpSendError) as exc:
        await db.rollback()
        await _failed(request, event_type, "email_send_failed", username=str(row.email), detail=str(exc)[:500])
        raise _refuse(503, "email_send_failed", "The email could not be sent right now. Try again later.") from exc


async def _wait_or_refuse(db: AsyncSession, *, email: str, purpose: str) -> None:
    from app.services.email_signup_service import seconds_until_resend

    wait = await seconds_until_resend(db, email=email, purpose=purpose)
    if wait > 0:
        raise _refuse(
            429, "resend_wait", f"A code was just sent. You can ask for another in {wait} seconds.", retry_after=wait
        )


# ── Sign-up ───────────────────────────────────────────────────────────────


async def _signup_settings_or_refuse(db: AsyncSession, request: Request, who: str | None):
    settings = await load_email_signup_settings(db)
    if not settings.enabled or not await smtp_configured(db):
        await _failed(request, EVENT_SIGNUP_FAILED, "signup_disabled", username=who)
        raise _refuse(403, "signup_disabled", "Creating an account by email is not available.")
    return settings


def _domain_message(settings: Any) -> str:
    domains = ", ".join(settings.allowed_domains)
    return f"Accounts can be created only with an email address at {domains}."


@router.post("/signup/start")
async def signup_start(body: EmailIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    email = normalize_email(body.email)
    ip = resolve_client_ip(request) or "unknown"
    await _limited(
        request,
        EVENT_SIGNUP_FAILED,
        [(f"signup:start:ip:{ip}", START_PER_IP), (f"signup:start:email:{email}", START_PER_EMAIL)],
        email or None,
    )
    settings = await _signup_settings_or_refuse(db, request, email or None)
    if not valid_email(email):
        await _failed(request, EVENT_SIGNUP_FAILED, "email_invalid", username=email or None)
        raise _refuse(400, "email_invalid", "Enter a valid email address.")
    if not domain_allowed(email, settings):
        await _failed(request, EVENT_SIGNUP_FAILED, "domain_not_allowed", username=email)
        raise _refuse(400, "domain_not_allowed", _domain_message(settings))
    existing = await user_by_email(db, email)
    if existing is not None:
        await _failed(request, EVENT_SIGNUP_FAILED, "email_taken", user=existing, username=email)
        raise _email_taken(existing, reset_on=settings.reset_enabled)
    await _wait_or_refuse(db, email=email, purpose=PURPOSE_SIGNUP)
    row, code = await issue_code(db, email=email, purpose=PURPOSE_SIGNUP, ip=ip)
    await _send_or_refuse(db, request, EVENT_SIGNUP_FAILED, row, code)
    await db.commit()
    return _started(row)


def _email_taken(user: User, *, reset_on: bool) -> HTTPException:
    """The address has an account: say which kind, and whether its password can be reset by email."""
    if user.deleted_at is not None:
        return _refuse(
            409,
            "email_taken",
            "This email belongs to a removed account. Ask your administrator.",
            reset_available=False,
        )
    local = (user.auth_provider or "local") == "local" and bool(user.hashed_password)
    if not local:
        return _refuse(
            409,
            "email_taken",
            "An account already uses this email. It signs in through your organization's directory: "
            "sign in with your directory username and password, or with single sign-on.",
            reset_available=False,
        )
    can_reset = reset_on and bool(user.is_active)
    message = "An account already uses this email. Sign in"
    message += ", or reset its password if you have forgotten it." if can_reset else "."
    return _refuse(409, "email_taken", message, reset_available=can_reset)


async def _verify(
    db: AsyncSession, request: Request, body: CodeIn, *, purpose: str, event_type: str
) -> tuple[Any, User | None]:
    ip = resolve_client_ip(request) or "unknown"
    await _limited(request, event_type, [(f"{purpose}:verify:ip:{ip}", VERIFY_PER_IP)], None)
    try:
        row = await check_code(db, token=body.token, code=body.code, purpose=purpose)
    except CodeError as exc:
        await db.commit()  # the wrong try counts
        await _failed(request, event_type, exc.reason)
        raise _refuse(exc.status, exc.reason, str(exc)) from exc
    await db.commit()
    user = await db.get(User, int(row.user_id)) if row.user_id is not None else None
    return row, user


@router.post("/signup/verify")
async def signup_verify(body: CodeIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row, _user = await _verify(db, request, body, purpose=PURPOSE_SIGNUP, event_type=EVENT_SIGNUP_FAILED)
    return {"verified": True, "email": str(row.email), "suggested_username": suggested_username(str(row.email))}


async def _verified_or_refuse(db: AsyncSession, request: Request, token: str, *, purpose: str, event_type: str):
    try:
        return await verified_row(db, token=token, purpose=purpose)
    except CodeError as exc:
        await db.commit()
        await _failed(request, event_type, exc.reason)
        raise _refuse(exc.status, exc.reason, str(exc)) from exc


async def _consumed_or_refuse(db: AsyncSession, request: Request, row: Any, *, event_type: str) -> None:
    """Use the token once; a second request racing with the same token is refused."""
    try:
        await consume(db, row)
    except CodeError as exc:
        await db.rollback()
        await _failed(request, event_type, exc.reason)
        raise _refuse(exc.status, exc.reason, str(exc)) from exc


async def _username_check(db: AsyncSession, raw: str) -> tuple[str, str | None, str | None]:
    """The normalized name, and (code, message) when it cannot be taken."""
    username = normalize_username(raw)
    problem = username_problem(username)
    if problem:
        return username, "username_invalid", problem
    if await username_taken_ci(db, username):
        return username, "username_taken", "That username is taken. Choose another."
    return username, None, None


@router.post("/signup/username-available")
async def signup_username_available(
    body: UsernameIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    ip = resolve_client_ip(request) or "unknown"
    await _limited(request, EVENT_SIGNUP_FAILED, [(f"signup:name:ip:{ip}", CHECK_PER_IP)], None)
    await _verified_or_refuse(db, request, body.token, purpose=PURPOSE_SIGNUP, event_type=EVENT_SIGNUP_FAILED)
    username, code, message = await _username_check(db, body.username)
    return {"username": username, "available": code is None, "code": code, "message": message}


@router.post("/signup/complete")
async def signup_complete(
    body: SignupCompleteIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    from app.api.auth import _token_response
    from app.services.budget_service import resolve_monthly_budget
    from app.services.plan_assignment_service import upsert_user_plan
    from app.services.security_audit import log_security_event
    from app.services.user_chat_storage_service import ensure_user_chat_store
    from app.services.user_role_service import set_user_roles

    ip = resolve_client_ip(request) or "unknown"
    await _limited(request, EVENT_SIGNUP_FAILED, [(f"signup:complete:ip:{ip}", COMPLETE_PER_IP)], None)
    settings = await _signup_settings_or_refuse(db, request, None)
    row = await _verified_or_refuse(db, request, body.token, purpose=PURPOSE_SIGNUP, event_type=EVENT_SIGNUP_FAILED)
    email = str(row.email)
    if not domain_allowed(email, settings):
        await _failed(request, EVENT_SIGNUP_FAILED, "domain_not_allowed", username=email)
        raise _refuse(400, "domain_not_allowed", _domain_message(settings))
    existing = await user_by_email(db, email)
    if existing is not None:
        await _failed(request, EVENT_SIGNUP_FAILED, "email_taken", user=existing, username=email)
        raise _email_taken(existing, reset_on=settings.reset_enabled)
    username, code, message = await _username_check(db, body.username)
    if code:
        await _failed(request, EVENT_SIGNUP_FAILED, code, username=username or email)
        raise _refuse(409 if code == "username_taken" else 400, code, message or "")
    try:
        password = validate_password(body.password, username=username, email=email)
    except PasswordPolicyError as exc:
        await _failed(request, EVENT_SIGNUP_FAILED, "weak_password", username=username)
        raise _refuse(400, "weak_password", str(exc)) from exc

    display_name = " ".join((body.display_name or "").split()) or username
    user = User(
        username=username,
        email=email,
        display_name=display_name[:255],
        hashed_password=hash_password(password),
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Someone took the name or the address a moment ago.
        await db.rollback()
        await _failed(request, EVENT_SIGNUP_FAILED, "username_taken", username=username)
        raise _refuse(409, "username_taken", "That username or email was just taken. Choose another username.") from exc
    await set_user_roles(db, user, ["user"])
    if settings.default_plan_id is not None:
        from app.models.budget import BudgetPlan

        if await db.get(BudgetPlan, settings.default_plan_id) is not None:
            await upsert_user_plan(db, int(user.id), int(settings.default_plan_id))
    user.monthly_budget_usd = await resolve_monthly_budget(db, user)  # type: ignore[assignment]
    await _consumed_or_refuse(db, request, row, event_type=EVENT_SIGNUP_FAILED)
    await ensure_user_chat_store(db, int(user.id))
    await log_security_event(
        db,
        actor=user,
        actor_ip=ip,
        action="user_self_registered",
        resource_type="user",
        resource_id=str(user.id),
        detail={"username": username, "email_domain": email.rsplit("@", 1)[-1], "plan_id": settings.default_plan_id},
    )
    await db.commit()
    await record_auth_event(event_type=EVENT_SIGNUP_COMPLETED, user=user, auth_method="local", request=request)
    return await _token_response(db, user, response, request)


# ── Password reset ────────────────────────────────────────────────────────


async def _reset_settings_or_refuse(db: AsyncSession, request: Request, who: str | None):
    settings = await load_email_signup_settings(db)
    if not settings.reset_enabled or not await smtp_configured(db):
        await _failed(request, EVENT_PASSWORD_RESET_FAILED, "reset_disabled", username=who)
        raise _refuse(403, "reset_disabled", "Resetting a password by email is not available. Ask your administrator.")
    return settings


def _not_resettable(user: User | None) -> tuple[str, str, int] | None:
    """Why this account's password cannot be reset by email: (reason, message, status), or None."""
    if user is None or user.deleted_at is not None:
        return "email_unknown", "No account uses this email address.", 404
    if (user.auth_provider or "local") != "local" or not user.hashed_password:
        return (
            "not_local_account",
            "This account signs in through your organization's directory. Reset the password there, "
            "or ask your administrator.",
            400,
        )
    if not user.is_active:
        return "account_inactive", "This account is deactivated. Ask your administrator.", 403
    return None


@router.post("/password-reset/start")
async def password_reset_start(body: EmailIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    email = normalize_email(body.email)
    ip = resolve_client_ip(request) or "unknown"
    await _limited(
        request,
        EVENT_PASSWORD_RESET_FAILED,
        [(f"reset:start:ip:{ip}", START_PER_IP), (f"reset:start:email:{email}", START_PER_EMAIL)],
        email or None,
    )
    await _reset_settings_or_refuse(db, request, email or None)
    if not valid_email(email):
        await _failed(request, EVENT_PASSWORD_RESET_FAILED, "email_invalid", username=email or None)
        raise _refuse(400, "email_invalid", "Enter a valid email address.")
    user = await user_by_email(db, email)
    refusal = _not_resettable(user)
    if refusal is not None:
        reason, message, status = refusal
        await _failed(request, EVENT_PASSWORD_RESET_FAILED, reason, user=user, username=email)
        raise _refuse(status, reason, message)
    assert user is not None
    await _wait_or_refuse(db, email=email, purpose=PURPOSE_PASSWORD_RESET)
    row, code = await issue_code(db, email=email, purpose=PURPOSE_PASSWORD_RESET, user_id=int(user.id), ip=ip)
    await _send_or_refuse(db, request, EVENT_PASSWORD_RESET_FAILED, row, code)
    await db.commit()
    return _started(row)


@router.post("/password-reset/verify")
async def password_reset_verify(body: CodeIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row, user = await _verify(db, request, body, purpose=PURPOSE_PASSWORD_RESET, event_type=EVENT_PASSWORD_RESET_FAILED)
    return {"verified": True, "email": str(row.email), "username": str(user.username) if user else None}


@router.post("/password-reset/complete")
async def password_reset_complete(
    body: ResetCompleteIn, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from sqlalchemy import update

    from app.models.email_verification import EmailVerification
    from app.services.email_signup_service import utcnow
    from app.services.security_audit import log_security_event

    ip = resolve_client_ip(request) or "unknown"
    await _limited(request, EVENT_PASSWORD_RESET_FAILED, [(f"reset:complete:ip:{ip}", COMPLETE_PER_IP)], None)
    await _reset_settings_or_refuse(db, request, None)
    row = await _verified_or_refuse(
        db, request, body.token, purpose=PURPOSE_PASSWORD_RESET, event_type=EVENT_PASSWORD_RESET_FAILED
    )
    user = await db.get(User, int(row.user_id)) if row.user_id is not None else None
    refusal = _not_resettable(user)
    if refusal is not None:
        reason, message, status = refusal
        await _failed(request, EVENT_PASSWORD_RESET_FAILED, reason, user=user)
        raise _refuse(status, reason, message)
    assert user is not None
    try:
        password = validate_password(body.password, username=str(user.username), email=str(user.email or ""))
    except PasswordPolicyError as exc:
        await _failed(request, EVENT_PASSWORD_RESET_FAILED, "weak_password", user=user)
        raise _refuse(400, "weak_password", str(exc)) from exc
    if user.hashed_password and verify_password(password, str(user.hashed_password)):
        await _failed(request, EVENT_PASSWORD_RESET_FAILED, "weak_password", user=user)
        raise _refuse(400, "weak_password", "Choose a password different from your current one.")

    await _consumed_or_refuse(db, request, row, event_type=EVENT_PASSWORD_RESET_FAILED)
    now = utcnow()
    user.hashed_password = hash_password(password)  # type: ignore[assignment]
    # Every session ends: whoever had the old password is signed out everywhere.
    user.token_version = int(user.token_version or 0) + 1  # type: ignore[assignment]
    await db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.purpose == PURPOSE_PASSWORD_RESET,
            EmailVerification.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    await log_security_event(
        db,
        actor=user,
        actor_ip=ip,
        action="user_password_reset_by_email",
        resource_type="user",
        resource_id=str(user.id),
        detail={"sessions_revoked": True},
    )
    await db.commit()
    await record_auth_event(event_type=EVENT_PASSWORD_RESET, user=user, auth_method="local", request=request)
    await record_auth_event(
        event_type=EVENT_SESSION_REVOKED,
        user=user,
        reason_code="password_reset_by_email",
        auth_method="local",
        request=request,
    )
    return {"ok": True, "username": str(user.username)}
