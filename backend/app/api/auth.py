"""Authentication: local, LDAP, SAML 2.0 SP."""

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
from app.services.saml_sp import (
    login_redirect_url,
    logout_redirect_url,
    process_acs,
    sp_metadata_xml,
)
from app.services.storage_service import ensure_user_media_directory
from app.services.user_chat_storage_service import ensure_user_chat_store
from app.services.user_lifecycle_service import record_user_login
from app.services.session_cookie import clear_session_cookies, new_csrf_token, set_session_cookies

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    is_active: bool = True


class ExchangeRequest(BaseModel):
    code: str


@router.get("/session")
async def auth_session(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    slugs = await get_user_role_slugs(db, user.id)
    return {
        "username": user.username,
        "role": primary_role_slug(slugs),
        "is_active": bool(user.is_active),
        "auth_provider": user.auth_provider or "local",
        **session_payload_for_slugs(slugs),
    }


@router.post("/logout")
async def logout_local(
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all previously-issued JWTs for this user."""
    user.token_version = int(user.token_version or 0) + 1
    await db.commit()
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/methods")
async def auth_methods(db: AsyncSession = Depends(get_db)):
    ldap_cfg = await get_provider_config(db, "ldap")
    saml_cfg = await get_provider_config(db, "saml")
    return {"ldap": bool(ldap_cfg.get("enabled")), "saml": bool(saml_cfg.get("enabled"))}


async def _token_response(db: AsyncSession, user: User, response: Response) -> TokenResponse:
    if user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account removed")
    await record_user_login(db, user)
    await db.commit()
    slugs = await get_user_role_slugs(db, user.id)
    primary = primary_role_slug(slugs)
    token = create_access_token(user.username, primary, token_version=user.token_version)
    set_session_cookies(response, access_token=token)
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

    source_ip = request.client.host if request.client else None
    await check_login_rate_limit(username, source_ip)
    user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    if user and user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account removed")
    if user and user.hashed_password:
        if verify_password(body.password, user.hashed_password):
            ensure_user_media_directory(user.username)
            await ensure_user_chat_store(db, user.id)
            return await _token_response(db, user, response)
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
            return await _token_response(db, user, response)

    raise HTTPException(status_code=401, detail="Invalid username or password")


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


@router.post("/saml/exchange")
async def saml_exchange(
    body: ExchangeRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a one-time SSO code for the Alpha Router session (keeps JWT out of the URL)."""
    del db
    payload = await consume_code(body.code)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired login code")
    set_session_cookies(response, access_token=payload["token"])
    settings = get_settings()
    body_token = payload["token"] if settings.allow_legacy_bearer_auth else ""
    return TokenResponse(
        access_token=body_token,
        token_type="bearer",
        role=payload.get("role", "user"),
        is_active=bool(payload.get("is_active", True)),
    )


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
    """Terminate Alpha Router session and optionally redirect to IdP SLO."""
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
    clear_session_cookies(response)
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
    """Upsert a directory (LDAP/SAML) user WITHOUT cross-provider takeover.

    * SAML: stable identity is NameID (external_id). Lookup by
      ``(auth_provider='saml', external_id=NameID)`` first; username collision
      with a different provider is rejected (409).
    * LDAP: username-based binding.
    """
    username = profile["username"]
    if not username:
        raise HTTPException(401, "Invalid directory profile")

    external_id = (profile.get("external_id") or "").strip() or None
    user: User | None = None

    if provider == "saml" and external_id:
        user = (
            await db.execute(
                select(User).where(
                    User.auth_provider == "saml",
                    User.external_id == external_id,
                )
            )
        ).scalars().first()

    if user is None:
        by_username = (
            await db.execute(select(User).where(User.username == username))
        ).scalars().first()
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
        user = User(username=username, role="user", auth_provider=provider)
        db.add(user)
    user.email = mapped.get("email") or user.email
    user.display_name = mapped.get("display_name") or user.display_name
    for field in ("job_title", "department", "office", "reporting_to"):
        val = mapped.get(field)
        if val is not None and str(val).strip():
            setattr(user, field, str(val).strip())
    if mapped.get("external_id"):
        user.external_id = mapped.get("external_id")
    user.auth_provider = provider
    await db.commit()
    await db.refresh(user)
    ensure_user_media_directory(user.username)
    await ensure_user_chat_store(db, user.id)
    return user
