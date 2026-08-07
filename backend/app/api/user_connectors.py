"""Per-user third-party Connectors: connect/disconnect via OAuth.

Each user supplies their own OAuth Client ID/Secret (decision ب=2). Alpharouter
stores them encrypted, runs the Authorization Code dance on the user's
behalf, and persists the access/refresh tokens encrypted.

Security:
- Every query is scoped by ``user.id`` from the session (IDOR guard).
- ``state`` is a signed JWT bound to ``user_id`` + ``provider_id`` + a
  single-use nonce (replay & cross-user protection).
- ``provider_id`` must exist in the registry allowlist (SSRF guard); the
  user never supplies the MCP URL.
- Secrets are never returned to the client; only status metadata is.
- Mutating routes go through the existing CSRF double-submit middleware.
"""

from __future__ import annotations

import datetime
import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user
from app.branding import CONNECTOR_STATE_COOKIE_NAME, LOGGER_NAMESPACE
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.models.user_connector import UserConnector
from app.services.connector_registry import ConnectorSpec, get_connector, list_connectors
from app.services.connector_state import consume_state, new_state_nonce, store_state
from app.services.secret_crypto import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api/user/connectors", tags=["user-connectors"])
logger = logging.getLogger(f"{LOGGER_NAMESPACE}.connectors")

_STATE_TTL_SECONDS = 600


class ConnectorCredentialsIn(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=512)
    client_secret: str = Field(..., min_length=1, max_length=512)


class ConnectorApiKeyIn(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=512)


def _public_view(row: UserConnector | None, spec: ConnectorSpec) -> dict:
    """Shape returned to the client — never includes secrets."""
    return {
        "provider_id": spec.provider_id,
        "label": spec.label,
        "auth_type": spec.auth_type,
        "mcp_url": spec.mcp_url,
        "docs_url": spec.docs_url,
        "scopes_required": list(spec.scopes),
        "category": list(spec.category),
        "subtitle": spec.subtitle,
        "connected": row is not None and row.revoked_at is None,
        "connected_at": row.created_at.isoformat() if row and row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row and row.expires_at else None,
        "scopes_granted": row.scope if row else None,
    }


def _make_state(user_id: int, provider_id: str, nonce: str) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "provider": provider_id,
        "nonce": nonce,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=_STATE_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def _decode_state(state: str) -> dict | None:
    settings = get_settings()
    try:
        return jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def _redirect_url(request: Request) -> str:
    """Public callback URL. Prefers configured frontend URL, falls back to request base."""
    settings = get_settings()
    base = (settings.frontend_url or "").rstrip("/")
    if not base:
        scheme = request.url.scheme
        host = request.headers.get("x-forwarded-host") or request.url.netloc
        base = f"{scheme}://{host}"
    return f"{base}/api/user/connectors/oauth/callback"


async def _get_row(db: AsyncSession, user_id: int, provider_id: str) -> UserConnector | None:
    return (
        await db.execute(
            select(UserConnector).where(
                UserConnector.user_id == user_id,
                UserConnector.provider_id == provider_id,
            )
        )
    ).scalars().first()


@router.get("")
async def list_user_connectors(
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all registered connectors with the current user's connection status."""
    rows = {
        r.provider_id: r
        for r in (
            await db.execute(
                select(UserConnector).where(UserConnector.user_id == user.id)
            )
        ).scalars().all()
    }
    return {"connectors": [_public_view(rows.get(spec.provider_id), spec) for spec in list_connectors()]}


@router.post("/{provider_id}/credentials")
async def store_credentials(
    provider_id: str,
    body: ConnectorCredentialsIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Store (or update) the user's OAuth Client ID/Secret for a connector."""
    spec = get_connector(provider_id)
    if spec is None:
        raise HTTPException(404, "Unknown connector")
    if spec.auth_type != "oauth":
        raise HTTPException(400, "This connector does not use OAuth credentials")
    row = await _get_row(db, user.id, provider_id)
    if row is None:
        row = UserConnector(user_id=user.id, provider_id=provider_id)
        db.add(row)
    row.client_id_encrypted = encrypt_secret(body.client_id)
    row.client_secret_encrypted = encrypt_secret(body.client_secret)
    await db.commit()
    logger.info("connector credentials stored user=%s provider=%s", user.id, provider_id)
    return {"ok": True}


@router.get("/{provider_id}/begin")
async def begin_connect(
    provider_id: str,
    request: Request,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Build the provider OAuth URL with a signed, single-use ``state``."""
    spec = get_connector(provider_id)
    if spec is None:
        raise HTTPException(404, "Unknown connector")
    if spec.auth_type != "oauth":
        raise HTTPException(400, "This connector does not use OAuth")
    row = await _get_row(db, user.id, provider_id)
    if row is None or not row.client_id_encrypted:
        raise HTTPException(400, "Store OAuth Client ID/Secret first")
    client_id = decrypt_secret(row.client_id_encrypted) or ""
    if not client_id:
        raise HTTPException(400, "Stored Client ID is unavailable")

    nonce = new_state_nonce()
    state = _make_state(user.id, provider_id, nonce)
    await store_state(nonce, {"user_id": user.id, "provider_id": provider_id})

    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_url(request),
        "response_type": "code",
        "scope": " ".join(spec.scopes),
        "state": state,
    }
    params.update(spec.extra_auth_params)
    auth_url = f"{spec.auth_endpoint}?{urlencode(params)}"
    response = JSONResponse({"auth_url": auth_url})
    response.set_cookie(
        key=CONNECTOR_STATE_COOKIE_NAME,
        value=nonce,
        httponly=True,
        secure=get_settings().environment.lower() == "production",
        samesite="lax",
        path="/api",
        max_age=_STATE_TTL_SECONDS,
    )
    return response


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """OAuth redirect target. Exchanges the code for tokens and stores them."""
    settings = get_settings()
    frontend_url = (settings.frontend_url or "").rstrip("/") or "/app"
    if error:
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason={error}")
    if not code or not state:
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=missing_params")

    payload = _decode_state(state)
    if payload is None:
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=invalid_state")
    provider_id = payload.get("provider")
    user_id = payload.get("sub")
    nonce = payload.get("nonce")
    if not provider_id or not user_id or not nonce:
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=malformed_state")

    # Single-use nonce: cookie must match the signed state, and the nonce must
    # be consumable from the store. This blocks replay and cross-user state.
    cookie_nonce = request.cookies.get(CONNECTOR_STATE_COOKIE_NAME) or ""
    if not cookie_nonce or cookie_nonce != nonce:
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=state_cookie_mismatch")
    stored = await consume_state(nonce)
    if not stored or str(stored.get("user_id")) != str(user_id) or stored.get("provider_id") != provider_id:
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=state_consumed")

    spec = get_connector(provider_id)
    if spec is None or spec.auth_type != "oauth":
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=unknown_provider")

    row = await _get_row(db, int(user_id), provider_id)
    if row is None or not row.client_secret_encrypted:
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=no_credentials")
    client_id = decrypt_secret(row.client_id_encrypted) or ""
    client_secret = decrypt_secret(row.client_secret_encrypted) or ""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                spec.token_endpoint,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": _redirect_url(request),
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            logger.warning("connector token exchange failed user=%s provider=%s status=%s", user_id, provider_id, resp.status_code)
            return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=token_exchange")
        token_data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.exception("connector token exchange error user=%s provider=%s: %s", user_id, provider_id, exc)
        return RedirectResponse(f"{frontend_url}/app?connectors=error&reason=token_exchange")

    row.access_token_encrypted = encrypt_secret(token_data.get("access_token") or "")
    row.refresh_token_encrypted = encrypt_secret(token_data.get("refresh_token") or "")
    row.scope = token_data.get("scope") or " ".join(spec.scopes)
    expires_in = token_data.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        row.expires_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=int(expires_in))
    row.revoked_at = None
    await db.commit()

    response = RedirectResponse(f"{frontend_url}/app?connectors=connected&provider={provider_id}")
    response.delete_cookie(key=CONNECTOR_STATE_COOKIE_NAME, path="/api")
    return response


@router.post("/{provider_id}/connect-api-key")
async def connect_api_key(
    provider_id: str,
    body: ConnectorApiKeyIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect a provider that authenticates with a user-supplied API key."""
    spec = get_connector(provider_id)
    if spec is None:
        raise HTTPException(404, "Unknown connector")
    if spec.auth_type != "api_key":
        raise HTTPException(400, "This connector does not use an API key")
    row = await _get_row(db, user.id, provider_id)
    if row is None:
        row = UserConnector(user_id=user.id, provider_id=provider_id)
        db.add(row)
    # Store the API key in the access_token slot (encrypted); no refresh for api_key.
    row.access_token_encrypted = encrypt_secret(body.api_key)
    row.refresh_token_encrypted = None
    row.expires_at = None
    row.revoked_at = None
    await db.commit()
    logger.info("connector api-key stored user=%s provider=%s", user.id, provider_id)
    return {"ok": True}


@router.post("/{provider_id}/connect")
async def connect_no_auth(
    provider_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect a public (no-auth) MCP server — just record the link."""
    spec = get_connector(provider_id)
    if spec is None:
        raise HTTPException(404, "Unknown connector")
    if spec.auth_type != "none":
        raise HTTPException(400, "This connector requires authentication")
    row = await _get_row(db, user.id, provider_id)
    if row is None:
        row = UserConnector(user_id=user.id, provider_id=provider_id)
        db.add(row)
    row.revoked_at = None
    await db.commit()
    logger.info("connector no-auth linked user=%s provider=%s", user.id, provider_id)
    return {"ok": True}


@router.delete("/{provider_id}")
async def disconnect(
    provider_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke at the provider (best-effort) and delete the local row."""
    spec = get_connector(provider_id)
    if spec is None:
        raise HTTPException(404, "Unknown connector")
    row = await _get_row(db, user.id, provider_id)
    if row is None:
        raise HTTPException(404, "Not connected")
    # Best-effort remote revoke.
    if spec.revoke_endpoint and row.access_token_encrypted:
        token = decrypt_secret(row.access_token_encrypted) or ""
        if token:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(spec.revoke_endpoint, data={"token": token})
            except Exception as exc:  # noqa: BLE001
                logger.warning("connector revoke failed user=%s provider=%s: %s", user.id, provider_id, exc)
    row.revoked_at = datetime.datetime.utcnow()
    row.access_token_encrypted = None
    row.refresh_token_encrypted = None
    await db.commit()
    logger.info("connector disconnected user=%s provider=%s", user.id, provider_id)
    return {"ok": True}
