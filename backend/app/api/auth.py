"""Authentication: local, LDAP, Keycloak OIDC."""

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import create_access_token, verify_password
from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.rbac import normalize_role_slug, primary_role_slug, session_payload_for_slugs
from app.services.user_role_service import get_user_role_slugs
from app.services.auth_config import get_provider_config
from app.services.ldap_auth import (
    LDAP_UNAVAILABLE_MESSAGE,
    LdapUnavailableError,
    authenticate_ldap_sync,
    map_ldap_profile,
)
from app.services.storage_service import ensure_user_media_directory
from app.services.user_chat_storage_service import ensure_user_chat_store
from app.services.user_lifecycle_service import record_user_login

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


@router.get("/session")
async def auth_session(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    slugs = await get_user_role_slugs(db, user.id)
    return {
        "username": user.username,
        "role": primary_role_slug(slugs),
        "is_active": bool(user.is_active),
        **session_payload_for_slugs(slugs),
    }


@router.get("/methods")
async def auth_methods(db: AsyncSession = Depends(get_db)):
    ldap_cfg = await get_provider_config(db, "ldap")
    kc_cfg = await get_provider_config(db, "keycloak")
    return {"ldap": bool(ldap_cfg.get("enabled")), "keycloak": bool(kc_cfg.get("enabled"))}


async def _token_response(db: AsyncSession, user: User) -> TokenResponse:
    if user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account removed")
    await record_user_login(db, user)
    await db.commit()
    slugs = await get_user_role_slugs(db, user.id)
    primary = primary_role_slug(slugs)
    return TokenResponse(
        access_token=create_access_token(user.username, primary),
        role=primary,
        is_active=bool(user.is_active),
    )


@router.post("/login", response_model=TokenResponse)
async def login_local(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    username = body.username.strip()
    user = (await db.execute(select(User).where(User.username == username))).scalars().first()
    if user and user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="Account removed")
    if user and user.hashed_password:
        if verify_password(body.password, user.hashed_password):
            ensure_user_media_directory(user.username)
            await ensure_user_chat_store(db, user.id)
            return await _token_response(db, user)
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
            return await _token_response(db, user)

    raise HTTPException(status_code=401, detail="Invalid username or password")


@router.get("/keycloak/login")
async def keycloak_login(db: AsyncSession = Depends(get_db)):
    kc = await get_provider_config(db, "keycloak")
    if not kc.get("enabled"):
        raise HTTPException(status_code=400, detail="Keycloak disabled")
    url = (
        f"{kc['server_url'].rstrip('/')}/realms/{kc['realm']}"
        f"/protocol/openid-connect/auth"
        f"?client_id={kc['client_id']}"
        f"&response_type=code&scope=openid profile email"
        f"&redirect_uri={kc['redirect_uri']}"
    )
    return RedirectResponse(url)


@router.get("/keycloak/callback")
async def keycloak_callback(code: str, db: AsyncSession = Depends(get_db)):
    kc = await get_provider_config(db, "keycloak")
    if not kc.get("enabled"):
        raise HTTPException(status_code=400, detail="Keycloak disabled")
    server = kc["server_url"].rstrip("/")
    realm = kc["realm"]
    token_url = f"{server}/realms/{realm}/protocol/openid-connect/token"
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": kc["client_id"],
                "client_secret": kc["client_secret"],
                "redirect_uri": kc["redirect_uri"],
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Keycloak token exchange failed")
        access = token_resp.json().get("access_token")
        userinfo = await client.get(
            f"{server}/realms/{realm}/protocol/openid-connect/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
    info = userinfo.json()
    profile = {
        "username": info.get("preferred_username") or info.get("email"),
        "email": info.get("email"),
        "display_name": info.get("name"),
        "job_title": info.get("title") or info.get("job_title"),
        "department": info.get("department"),
        "office": info.get("office"),
        "reporting_to": info.get("manager") or info.get("reporting_to"),
        "external_id": info.get("sub"),
    }
    user = await _upsert_directory_user(db, profile, "keycloak")
    slugs = await get_user_role_slugs(db, user.id)
    await record_user_login(db, user)
    await db.commit()
    jwt_token = create_access_token(user.username, primary_role_slug(slugs))
    return RedirectResponse(f"{settings.frontend_url}/login?token={jwt_token}")


async def _upsert_directory_user(db: AsyncSession, profile: dict, provider: str) -> User:
    username = profile["username"]
    if not username:
        raise HTTPException(401, "Invalid directory profile")
    q = select(User).where(User.username == username)
    user = (await db.execute(q)).scalars().first()
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
