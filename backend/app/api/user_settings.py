"""Per-user profile settings: export/import chats, password, TOTP 2FA."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_active_user
from app.branding import LOGGER_NAMESPACE
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.user import User
from app.services.chat_import_export import (
    MAX_IMPORT_BYTES,
    ChatImportError,
    export_user_chats,
    import_user_chats,
)
from app.services.password_policy import PasswordPolicyError, validate_password
from app.services.rate_limit import check_rate_limit
from app.services.rbac import primary_role_slug
from app.services.session_cookie import set_session_cookies
from app.services.totp_service import (
    audit,
    consume_backup_code,
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_codes,
    is_local_user,
    provisioning_uri,
    qr_png_base64,
    verify_totp_code,
)
from app.services.user_role_service import get_user_role_slugs

router = APIRouter(prefix="/api/user/settings", tags=["user-settings"])
logger = logging.getLogger(f"{LOGGER_NAMESPACE}.security.settings")


def _require_local(user: User) -> None:
    if not is_local_user(user):
        raise HTTPException(
            status_code=403,
            detail="This action is only available for local accounts",
        )


@router.get("/security")
async def security_status(user: User = Depends(get_current_user)):
    local = is_local_user(user)
    return {
        "auth_provider": user.auth_provider or "local",
        "is_local": local,
        "totp_enabled": bool(local and user.totp_enabled),
        "password_change_available": local,
        "two_factor_available": local,
    }


@router.get("/chats/export")
async def export_chats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(f"settings:export:{user.id}", limit=10, window_seconds=60)
    payload = await export_user_chats(db, user.id)
    audit("chats_export", username=user.username, detail=f"sessions={len(payload.get('sessions') or [])}")
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Disposition": 'attachment; filename="alpha-router-chats-export.json"',
        "Cache-Control": "no-store",
    }
    return Response(content=body, media_type="application/json", headers=headers)


class ImportChatsIn(BaseModel):
    data: object


@router.post("/chats/import")
async def import_chats(
    body: ImportChatsIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    await check_rate_limit(f"settings:import:{user.id}", limit=5, window_seconds=60)
    raw = json.dumps(body.data, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Import file too large")
    try:
        result = await import_user_chats(db, user.id, body.data)
        await db.commit()
    except ChatImportError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("chat import failed for user=%s", user.username)
        raise HTTPException(status_code=400, detail="Import failed") from exc
    audit(
        "chats_import",
        username=user.username,
        detail=f"imported={result.get('imported')} skipped={result.get('skipped')} format={result.get('format')}",
    )
    return result


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


@router.post("/password")
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    response: Response,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    _require_local(user)
    await check_rate_limit(f"settings:password:{user.id}", limit=10, window_seconds=60, fail_closed=True)

    if not user.hashed_password or not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="New password confirmation does not match")
    try:
        pwd = validate_password(body.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if verify_password(pwd, user.hashed_password):
        raise HTTPException(status_code=400, detail="New password must be different from the current password")

    user.hashed_password = hash_password(pwd)
    user.token_version = int(user.token_version or 0) + 1
    await db.commit()
    await db.refresh(user)

    slugs = await get_user_role_slugs(db, user.id)
    primary = primary_role_slug(slugs)
    token = create_access_token(user.username, primary, token_version=user.token_version)
    set_session_cookies(response, access_token=token, request=request)
    audit("password_change", username=user.username)
    return {"ok": True}


@router.post("/2fa/setup")
async def setup_2fa(
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    _require_local(user)
    await check_rate_limit(f"settings:2fa-setup:{user.id}", limit=10, window_seconds=60)
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled")

    secret = generate_totp_secret()
    user.totp_secret_encrypted = encrypt_totp_secret(secret)
    user.totp_enabled = False
    user.totp_backup_codes_hashed = None
    await db.commit()

    uri = provisioning_uri(secret, user.username)
    audit("2fa_setup_started", username=user.username)
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_png_base64": qr_png_base64(uri),
    }


class TwoFaCodeIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


@router.post("/2fa/enable")
async def enable_2fa(
    body: TwoFaCodeIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    _require_local(user)
    await check_rate_limit(f"settings:2fa-enable:{user.id}", limit=20, window_seconds=60, fail_closed=True)
    if user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is already enabled")
    secret = decrypt_totp_secret(user.totp_secret_encrypted)
    if not secret:
        raise HTTPException(status_code=400, detail="Start 2FA setup first")
    if not verify_totp_code(secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid verification code")

    codes = generate_backup_codes()
    user.totp_enabled = True
    user.totp_backup_codes_hashed = hash_backup_codes(codes)
    await db.commit()
    audit("2fa_enabled", username=user.username)
    return {"ok": True, "backup_codes": codes}


class TwoFaDisableIn(BaseModel):
    password: str
    code: str | None = None


@router.post("/2fa/disable")
async def disable_2fa(
    body: TwoFaDisableIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    _require_local(user)
    await check_rate_limit(f"settings:2fa-disable:{user.id}", limit=10, window_seconds=60, fail_closed=True)
    if not user.totp_enabled:
        raise HTTPException(status_code=400, detail="Two-factor authentication is not enabled")
    if not user.hashed_password or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Password is incorrect")

    secret = decrypt_totp_secret(user.totp_secret_encrypted)
    code = (body.code or "").strip()
    ok = bool(secret and verify_totp_code(secret, code))
    remaining = None
    if not ok:
        remaining = consume_backup_code(
            user.totp_backup_codes_hashed if isinstance(user.totp_backup_codes_hashed, list) else None,
            code,
        )
        ok = remaining is not None
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid authenticator or backup code")

    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.totp_backup_codes_hashed = None
    await db.commit()
    audit("2fa_disabled", username=user.username)
    return {"ok": True}
