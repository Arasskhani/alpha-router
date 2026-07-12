"""Authentication: local, LDAP, Keycloak OIDC."""

import asyncio
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
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
from app.services.oidc import (
    OIDCFlowParams,
    clear_state_cookie_params,
    generate_flow_params,
    issuer_for,
    sign_state_cookie,
    state_cookie_params,
    validate_id_token,
    validate_realm,
    validate_server_url,
    verify_state_cookie,
)
from app.services.oidc_exchange import consume_code, generate_code, store_token
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
        "auth_provider": user.auth_provider or "local",
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
    try:
        server = validate_server_url(kc["server_url"])
        realm = validate_realm(kc["realm"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Generate a fresh state/nonce/PKCE triplet and bind it to the user's
    # browser via a short-lived signed cookie. The callback verifies the
    # cookie + the IdP-echoed ``state`` to prevent login CSRF, and uses the
    # PKCE verifier + nonce to protect the code exchange and ID token.
    params = generate_flow_params()
    cookie_value = sign_state_cookie(params)

    url = (
        f"{server}/realms/{realm}/protocol/openid-connect/auth"
        f"?client_id={quote(kc['client_id'])}"
        f"&response_type=code"
        f"&scope={quote('openid profile email')}"
        f"&redirect_uri={quote(kc['redirect_uri'])}"
        f"&state={params.state}"
        f"&nonce={params.nonce}"
        f"&code_challenge={params.code_challenge}"
        f"&code_challenge_method=S256"
    )
    resp = RedirectResponse(url)
    resp.set_cookie(value=cookie_value, **state_cookie_params())
    return resp


@router.get("/keycloak/callback")
async def keycloak_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    kc = await get_provider_config(db, "keycloak")
    if not kc.get("enabled"):
        raise HTTPException(status_code=400, detail="Keycloak disabled")
    try:
        server = validate_server_url(kc["server_url"])
        realm = validate_realm(kc["realm"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 1) Verify the signed state cookie + the IdP-echoed state (CSRF).
    cookie_value = request.cookies.get("alpha_router_oidc_state")
    flow = verify_state_cookie(cookie_value, state or "")
    if flow is None or not code:
        raise HTTPException(status_code=400, detail="Invalid or expired OIDC state")

    issuer = issuer_for(server, realm)
    token_url = f"{issuer}/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 2) Exchange the authorization code WITH the PKCE verifier.
        token_resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": kc["client_id"],
                "client_secret": kc["client_secret"],
                "redirect_uri": kc["redirect_uri"],
                "code_verifier": flow.code_verifier,
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Keycloak token exchange failed")
        tokens = token_resp.json()
        access = tokens.get("access_token")
        id_token = tokens.get("id_token")
        if not access or not id_token:
            raise HTTPException(status_code=401, detail="Keycloak did not return tokens")

        # 3) Validate the ID token: signature (JWKS) + iss/aud/exp/nonce.
        try:
            claims = validate_id_token(
                id_token,
                issuer=issuer,
                audience=kc["client_id"],
                nonce=flow.nonce,
            )
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        # 4) Fetch verified profile claims from the userinfo endpoint.
        userinfo = await client.get(
            f"{issuer}/protocol/openid-connect/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
        if userinfo.status_code != 200:
            raise HTTPException(status_code=401, detail="Keycloak userinfo failed")

    info = userinfo.json()
    # The OIDC identity is the subject (``sub``); it MUST match the ID-token sub.
    sub = claims.get("sub") or info.get("sub")
    if not sub or info.get("sub") and info.get("sub") != sub:
        raise HTTPException(status_code=401, detail="OIDC subject mismatch")
    profile = {
        "username": info.get("preferred_username") or info.get("email"),
        "email": info.get("email"),
        "display_name": info.get("name"),
        "job_title": info.get("title") or info.get("job_title"),
        "department": info.get("department"),
        "office": info.get("office"),
        "reporting_to": info.get("manager") or info.get("reporting_to"),
        "external_id": sub,
    }
    user = await _upsert_directory_user(db, profile, "keycloak")
    slugs = await get_user_role_slugs(db, user.id)
    await record_user_login(db, user)
    await db.commit()
    jwt_token = create_access_token(user.username, primary_role_slug(slugs))

    # 5) Deliver the JWT via a one-time exchange code (NOT in the URL).
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
    redirect = RedirectResponse(f"{settings.frontend_url}/login?code={xchg_code}")
    redirect.delete_cookie(**clear_state_cookie_params())
    return redirect


@router.post("/keycloak/exchange")
async def keycloak_exchange(body: "ExchangeRequest", db: AsyncSession = Depends(get_db)):
    """Exchange a one-time OIDC code for the Alpha Router JWT (keeps JWT out of the URL)."""
    payload = await consume_code(body.code)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired login code")
    return TokenResponse(
        access_token=payload["token"],
        token_type="bearer",
        role=payload.get("role", "user"),
        is_active=bool(payload.get("is_active", True)),
    )


@router.get("/keycloak/logout")
async def keycloak_logout(db: AsyncSession = Depends(get_db)):
    """Redirect to the Keycloak end_session endpoint to terminate the SSO session."""
    kc = await get_provider_config(db, "keycloak")
    if not kc.get("enabled"):
        # If Keycloak is disabled, just point the SPA at its own logout screen.
        return RedirectResponse(f"{settings.frontend_url}/login")
    try:
        server = validate_server_url(kc["server_url"])
        realm = validate_realm(kc["realm"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    url = (
        f"{server}/realms/{realm}/protocol/openid-connect/logout"
        f"?client_id={quote(kc['client_id'])}"
        f"&post_logout_redirect_uri={quote(settings.frontend_url + '/login')}"
    )
    return RedirectResponse(url)


class ExchangeRequest(BaseModel):
    code: str


async def _upsert_directory_user(db: AsyncSession, profile: dict, provider: str) -> User:
    """Upsert a directory (LDAP/Keycloak) user WITHOUT cross-provider takeover.

    Identity binding rules (Phase 6 hardening):

    * Keycloak: the stable identity is the OIDC ``sub`` (external_id). We first
      look up by ``(auth_provider='keycloak', external_id=sub)``. Only if that
      fails do we consider the username — and if a user with the same username
      exists under a *different* provider (local/ldap), we REJECT rather than
      silently taking over that account (which would be account takeover /
      privilege escalation).
    * LDAP: keeps the legacy username-based binding (no stable sub).
    """
    username = profile["username"]
    if not username:
        raise HTTPException(401, "Invalid directory profile")

    external_id = (profile.get("external_id") or "").strip() or None
    user: User | None = None

    if provider == "keycloak" and external_id:
        # 1) Bind by stable OIDC subject.
        user = (
            await db.execute(
                select(User).where(
                    User.auth_provider == "keycloak",
                    User.external_id == external_id,
                )
            )
        ).scalars().first()

    if user is None:
        # 2) Fall back to username lookup, but guard against cross-provider
        #    collisions so a Keycloak user cannot hijack a local/ldap account
        #    (including an admin) that merely shares a username.
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
            # Same provider — safe to claim/backfill external_id.
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
