"""Authentication: local, LDAP, SAML 2.0 SP, generic OIDC."""

import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, Response as RawResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import create_access_token, verify_password
from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.rbac import primary_role_slug, session_payload_for_slugs
from app.services.user_role_service import get_user_role_slugs
from app.services.auth_config import get_provider_config
from app.services.ldap_auth import (
    LDAP_UNAVAILABLE_MESSAGE,
    LdapUnavailableError,
    authenticate_ldap_sync,
    map_ldap_profile,
)
from app.services.auth_exchange import consume_code, generate_code, store_token
from app.services.auth_urls import validate_frontend_url
from app.services.oidc_client import (
    STATE_COOKIE_NAME,
    build_authorize_url,
    build_profile_from_claims,
    clear_state_cookie_params,
    end_session_url,
    exchange_code_for_tokens,
    fetch_userinfo,
    generate_flow_params,
    sign_state_cookie,
    state_cookie_params,
    validate_id_token,
    validate_issuer_url,
    verify_state_cookie,
)
from app.services.saml_sp import (
    login_redirect_url,
    logout_redirect_url,
    process_acs,
    sp_metadata_xml,
)
from app.services.user_chat_storage_service import ensure_user_chat_store
from app.services.username_norm import find_user_by_username_ci, normalize_username
from app.services.user_lifecycle_service import record_user_login
from app.services.session_cookie import clear_session_cookies, new_csrf_token, set_session_cookies

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str = ""
    token_type: str = "bearer"
    role: str = ""
    is_active: bool = True
    requires_2fa: bool = False
    pending_token: str | None = None


class ExchangeRequest(BaseModel):
    code: str


class TwoFaLoginRequest(BaseModel):
    pending_token: str
    code: str


@router.get("/session")
async def auth_session(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    slugs = await get_user_role_slugs(db, user.id)
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": primary_role_slug(slugs),
        "is_active": bool(user.is_active),
        "auth_provider": user.auth_provider or "local",
        **session_payload_for_slugs(slugs),
    }


@router.post("/logout")
async def logout_local(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all previously-issued JWTs for this user."""
    from app.services.presence_service import clear_presence

    user.token_version = int(user.token_version or 0) + 1
    await db.commit()
    await clear_presence(user.id)
    clear_session_cookies(response, request=request)
    return {"ok": True}


@router.get("/methods")
async def auth_methods(db: AsyncSession = Depends(get_db)):
    ldap_cfg = await get_provider_config(db, "ldap")
    saml_cfg = await get_provider_config(db, "saml")
    oidc_cfg = await get_provider_config(db, "oidc")
    return {
        "ldap": bool(ldap_cfg.get("enabled")),
        "saml": bool(saml_cfg.get("enabled")),
        "oidc": bool(oidc_cfg.get("enabled")),
    }


async def _token_response(
    db: AsyncSession,
    user: User,
    response: Response,
    request: Request,
) -> TokenResponse:
    if user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account removed")
    await record_user_login(db, user)
    await db.commit()
    slugs = await get_user_role_slugs(db, user.id)
    primary = primary_role_slug(slugs)
    token = create_access_token(user.username, primary, token_version=user.token_version)
    set_session_cookies(response, access_token=token, request=request)
    settings = get_settings()
    body_token = token if settings.allow_legacy_bearer_auth else ""
    return TokenResponse(
        access_token=body_token,
        role=primary,
        is_active=bool(user.is_active),
    )


@router.post("/login", response_model=TokenResponse)
async def login_local(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    username = body.username.strip()
    from app.services.rate_limit import check_login_rate_limit

    from app.services.client_ip import resolve_client_ip

    source_ip = resolve_client_ip(request)
    await check_login_rate_limit(normalize_username(username) or username, source_ip)
    user = await find_user_by_username_ci(db, username)
    if user and user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account removed")
    if user and user.hashed_password:
        if verify_password(body.password, user.hashed_password):
            await ensure_user_chat_store(db, user.id)
            if bool(user.totp_enabled) and (user.auth_provider or "local") == "local":
                from app.services.twofa_pending import generate_pending_token, store_pending

                pending = generate_pending_token()
                await store_pending(
                    pending,
                    {"user_id": user.id, "username": user.username, "purpose": "login_2fa"},
                )
                return TokenResponse(
                    access_token="",
                    token_type="2fa_pending",
                    role="",
                    is_active=bool(user.is_active),
                    requires_2fa=True,
                    pending_token=pending,
                )
            return await _token_response(db, user, response, request)
        if (user.auth_provider or "local") == "local":
            raise HTTPException(status_code=401, detail="Invalid username or password")

    ldap_cfg = await get_provider_config(db, "ldap")
    if ldap_cfg.get("enabled"):
        timeout = max(3, int(settings.ldap_login_timeout_seconds))
        try:
            profile = await asyncio.wait_for(
                asyncio.to_thread(authenticate_ldap_sync, username, body.password, ldap_cfg),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=503, detail=LDAP_UNAVAILABLE_MESSAGE) from exc
        except LdapUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc) or LDAP_UNAVAILABLE_MESSAGE) from exc
        if profile:
            user = await _upsert_directory_user(db, profile, "ldap")
            return await _token_response(db, user, response, request)

    raise HTTPException(status_code=401, detail="Invalid username or password")


@router.post("/login/2fa", response_model=TokenResponse)
async def login_2fa(
    body: TwoFaLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Complete local login after password when TOTP is enabled."""
    from app.services.rate_limit import check_rate_limit
    from app.services.totp_service import (
        consume_backup_code,
        decrypt_totp_secret,
        verify_totp_code,
    )
    from app.services.twofa_pending import consume_pending

    from app.services.client_ip import resolve_client_ip

    source_ip = resolve_client_ip(request)
    await check_rate_limit(
        f"login2fa:ip:{source_ip or 'unknown'}",
        limit=30,
        window_seconds=60,
        fail_closed=True,
    )
    pending = await consume_pending(body.pending_token.strip())
    if not pending or pending.get("purpose") != "login_2fa":
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA session")
    user = (await db.execute(select(User).where(User.id == int(pending["user_id"])))).scalars().first()
    if not user or user.deleted_at is not None or not user.totp_enabled:
        raise HTTPException(status_code=401, detail="Invalid or expired 2FA session")
    await check_rate_limit(
        f"login2fa:user:{user.id}",
        limit=15,
        window_seconds=60,
        fail_closed=True,
    )

    secret = decrypt_totp_secret(user.totp_secret_encrypted)
    code = body.code.strip()
    ok = bool(secret and verify_totp_code(secret, code))
    if not ok:
        remaining = consume_backup_code(
            user.totp_backup_codes_hashed if isinstance(user.totp_backup_codes_hashed, list) else None,
            code,
        )
        if remaining is None:
            raise HTTPException(status_code=401, detail="Invalid authentication code")
        user.totp_backup_codes_hashed = remaining
        await db.commit()

    await ensure_user_chat_store(db, user.id)
    return await _token_response(db, user, response, request)


def _request_public_url(request: Request) -> str:
    """Absolute URL for the current request path (for python3-saml)."""
    from app.services.auth_urls import public_api_base

    return f"{public_api_base()}{request.url.path}"


@router.get("/saml/login")
async def saml_login(request: Request, db: AsyncSession = Depends(get_db)):
    cfg = await get_provider_config(db, "saml")
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="SAML is disabled")
    try:
        url = await asyncio.to_thread(login_redirect_url, cfg, _request_public_url(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"SAML login failed: {exc}") from exc
    return RedirectResponse(url)


@router.post("/saml/acs")
async def saml_acs(
    request: Request,
    SAMLResponse: str = Form(...),
    RelayState: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    del RelayState
    cfg = await get_provider_config(db, "saml")
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="SAML is disabled")
    form = {"SAMLResponse": SAMLResponse}
    try:
        profile = await asyncio.to_thread(process_acs, cfg, _request_public_url(request), form)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"SAML ACS failed: {exc}") from exc

    user = await _upsert_directory_user(db, profile, "saml")
    slugs = await get_user_role_slugs(db, user.id)
    await record_user_login(db, user)
    await db.commit()
    jwt_token = create_access_token(
        user.username, primary_role_slug(slugs), token_version=user.token_version
    )
    xchg_code = generate_code()
    await store_token(
        xchg_code,
        {
            "token": jwt_token,
            "role": primary_role_slug(slugs),
            "username": user.username,
            "is_active": bool(user.is_active),
        },
    )
    try:
        frontend_url = validate_frontend_url(settings.frontend_url)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid frontend redirect configuration") from exc
    return RedirectResponse(f"{frontend_url}/login?code={xchg_code}")


async def _sso_exchange(
    body: ExchangeRequest,
    response: Response,
    request: Request,
) -> TokenResponse:
    """Exchange a one-time SSO code for the Alpharouter session (keeps JWT out of the URL)."""
    payload = await consume_code(body.code)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired login code")
    set_session_cookies(response, access_token=payload["token"], request=request)
    settings = get_settings()
    body_token = payload["token"] if settings.allow_legacy_bearer_auth else ""
    return TokenResponse(
        access_token=body_token,
        token_type="bearer",
        role=payload.get("role", "user"),
        is_active=bool(payload.get("is_active", True)),
    )


@router.post("/sso/exchange")
async def sso_exchange(body: ExchangeRequest, response: Response, request: Request):
    return await _sso_exchange(body, response, request)


@router.post("/saml/exchange")
async def saml_exchange(body: ExchangeRequest, response: Response, request: Request):
    """Compatibility alias for shared SSO exchange."""
    return await _sso_exchange(body, response, request)


@router.get("/oidc/login")
async def oidc_login(db: AsyncSession = Depends(get_db)):
    cfg = await get_provider_config(db, "oidc")
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="OIDC is disabled")
    try:
        validate_issuer_url(cfg.get("issuer") or "")
        if not (cfg.get("client_id") or "").strip():
            raise ValueError("OIDC client_id is not configured")
        params = generate_flow_params()
        url = await asyncio.to_thread(build_authorize_url, cfg, params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="OIDC configuration error") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="OIDC login failed") from exc
    resp = RedirectResponse(url)
    resp.set_cookie(value=sign_state_cookie(params), **state_cookie_params())
    return resp


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    cfg = await get_provider_config(db, "oidc")
    if not cfg.get("enabled"):
        raise HTTPException(status_code=400, detail="OIDC is disabled")
    cookie_value = request.cookies.get(STATE_COOKIE_NAME)
    flow = verify_state_cookie(cookie_value, state or "")
    if flow is None or not code:
        raise HTTPException(status_code=400, detail="Invalid or expired OIDC state")
    try:
        tokens = await asyncio.to_thread(
            exchange_code_for_tokens, cfg, code=code, code_verifier=flow.code_verifier
        )
        claims = await asyncio.to_thread(
            validate_id_token,
            tokens["id_token"],
            issuer=cfg["issuer"],
            audience=cfg["client_id"],
            nonce=flow.nonce,
        )
        userinfo: dict = {}
        access = tokens.get("access_token")
        if access:
            userinfo = await asyncio.to_thread(fetch_userinfo, cfg, access) or {}
        profile = build_profile_from_claims(cfg, claims, userinfo)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="OIDC authentication failed") from exc

    user = await _upsert_directory_user(db, profile, "oidc")
    slugs = await get_user_role_slugs(db, user.id)
    await record_user_login(db, user)
    await db.commit()
    jwt_token = create_access_token(
        user.username, primary_role_slug(slugs), token_version=user.token_version
    )
    xchg_code = generate_code()
    await store_token(
        xchg_code,
        {
            "token": jwt_token,
            "role": primary_role_slug(slugs),
            "username": user.username,
            "is_active": bool(user.is_active),
        },
    )
    try:
        frontend_url = validate_frontend_url(settings.frontend_url)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid frontend redirect configuration") from exc
    redirect = RedirectResponse(f"{frontend_url}/login?code={xchg_code}")
    redirect.delete_cookie(**clear_state_cookie_params())
    return redirect


@router.get("/oidc/logout")
async def oidc_logout(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        username = payload.get("sub") if payload else None
        if username:
            user = (
                await db.execute(select(User).where(User.username == username))
            ).scalars().first()
            if user:
                user.token_version = int(user.token_version or 0) + 1
                await db.commit()
    try:
        frontend_url = validate_frontend_url(settings.frontend_url)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid frontend redirect configuration") from exc
    cfg = await get_provider_config(db, "oidc")
    slo = None
    if cfg.get("enabled"):
        try:
            slo = await asyncio.to_thread(end_session_url, cfg)
        except Exception:
            slo = None
    response = RedirectResponse(slo or f"{frontend_url}/login")
    clear_session_cookies(response, request=request)
    return response


@router.get("/saml/metadata")
async def saml_metadata(db: AsyncSession = Depends(get_db)):
    """Public SP metadata when SAML is enabled; opaque 404 otherwise.

    SP metadata is intentionally unauthenticated (standard SAML practice) but
    is not advertised while the provider is disabled. Generation does not
    require IdP metadata.
    """
    cfg = await get_provider_config(db, "saml")
    if not cfg.get("enabled"):
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        xml = await asyncio.to_thread(sp_metadata_xml, cfg)
    except Exception:
        # Avoid leaking configuration details on a public endpoint.
        raise HTTPException(status_code=404, detail="Not Found") from None
    return RawResponse(content=xml, media_type="application/samlmetadata+xml")


@router.get("/saml/logout")
async def saml_logout(request: Request, db: AsyncSession = Depends(get_db)):
    """Terminate the Alpharouter session and optionally redirect to IdP SLO."""
    token = request.cookies.get(settings.session_cookie_name)
    name_id: str | None = None
    if token:
        from app.core.security import decode_access_token

        payload = decode_access_token(token)
        username = payload.get("sub") if payload else None
        if username:
            user = (
                await db.execute(select(User).where(User.username == username))
            ).scalars().first()
            if user:
                name_id = user.external_id
                user.token_version = int(user.token_version or 0) + 1
                await db.commit()

    try:
        frontend_url = validate_frontend_url(settings.frontend_url)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid frontend redirect configuration") from exc

    cfg = await get_provider_config(db, "saml")
    slo_url = None
    if cfg.get("enabled"):
        try:
            slo_url = await asyncio.to_thread(
                logout_redirect_url, cfg, _request_public_url(request), name_id
            )
        except Exception:
            slo_url = None

    response = RedirectResponse(slo_url or f"{frontend_url}/login")
    clear_session_cookies(response, request=request)
    return response


@router.get("/csrf")
async def csrf_token(
    response: Response,
    user: User = Depends(get_current_user),
):
    """Refresh the readable double-submit token without exposing the JWT."""
    del user
    csrf = new_csrf_token()
    settings = get_settings()
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf,
        httponly=False,
        secure=settings.environment.lower() == "production",
        samesite="lax",
        path="/",
        max_age=max(300, int(settings.jwt_expire_minutes) * 60),
    )
    return {"csrf_token": csrf}


async def _upsert_directory_user(db: AsyncSession, profile: dict, provider: str) -> User:
    """Upsert a directory (LDAP/SAML/OIDC) user WITHOUT cross-provider takeover.

    * SAML: stable identity is NameID (external_id).
    * OIDC: stable identity is ``sub`` (external_id).
    * LDAP: username-based binding.
    Username collision with a different provider is rejected (409).
    Existing usernames are matched case-insensitively and not auto-renamed.
    """
    from app.services.username_norm import find_user_by_username_ci, normalize_username

    raw_username = (profile.get("username") or "").strip()
    username = normalize_username(raw_username)
    if not username:
        raise HTTPException(401, "Invalid directory profile")

    external_id = (profile.get("external_id") or "").strip() or None
    user: User | None = None

    if provider in {"saml", "oidc"} and external_id:
        user = (
            await db.execute(
                select(User).where(
                    User.auth_provider == provider,
                    User.external_id == external_id,
                )
            )
        ).scalars().first()

    if user is None:
        by_username = await find_user_by_username_ci(db, username)
        if by_username is not None:
            existing_provider = (by_username.auth_provider or "local")
            if existing_provider != provider:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Username '{username}' is already in use by a {existing_provider} account. "
                        "Refusing cross-provider account takeover."
                    ),
                )
            user = by_username

    if user and user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account removed")

    mapped = map_ldap_profile(profile) if provider == "ldap" else profile
    if not user:
        user = User(username=username, auth_provider=provider)
        db.add(user)
    user.email = mapped.get("email") or user.email
    user.display_name = mapped.get("display_name") or user.display_name
    for field in ("company", "job_title", "department", "office", "reporting_to"):
        val = mapped.get(field)
        if val is not None and str(val).strip():
            setattr(user, field, str(val).strip())
    if mapped.get("external_id"):
        user.external_id = mapped.get("external_id")
    user.auth_provider = provider
    await db.commit()
    await db.refresh(user)
    await ensure_user_chat_store(db, user.id)
    return user
