"""Connecting a browser extension, and the connections a user has.

The web app's consent page asks ``/api/extension/authorize`` for a one-time
code (session cookie and CSRF, like every other web call) and sends the tab to
the extension's ``connected.html`` with it. The extension trades the code and
its PKCE verifier at ``/api/extension/token`` - no cookie, no user session: the
code is the proof - and refreshes there later. With its access token it asks
``/api/extension/me`` what it may offer, and ``/api/extension/revoke`` ends its
own connection. Settings → Extension lists a user's connections and ends any
of them.

Every connection made or ended is in the security audit trail.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_active_user
from app.branding import PRODUCT_NAME
from app.config import get_settings
from app.database import get_db
from app.models.extension import ExtensionSession
from app.models.user import User
from app.services.client_ip import resolve_client_ip
from app.services.extension_access import extension_features, extension_permitted
from app.services.extension_distribution import ExtensionUnavailable, current_build
from app.services.extension_keys import ExtensionKeyUnavailable, get_signing_key
from app.services.extension_package import CONNECTED_PAGE, MIN_SUPPORTED_VERSION, normalize_origin
from app.services.extension_settings import load_extension_settings
from app.services.extension_tokens import (
    AUDIT_CONNECTED,
    AUDIT_DISCONNECTED,
    AUDIT_RESOURCE,
    REVOKED_BY_USER,
    ExtensionTokenError,
    TokenPair,
    clean_device_name,
    create_auth_code,
    create_session,
    is_valid_challenge,
    list_sessions,
    redeem_auth_code,
    refresh_session,
    revoke_session,
    token_hash,
)
from app.services.rate_limit import check_rate_limit, failure_limit_reached, record_failure
from app.services.security_audit import log_security_event

router = APIRouter(tags=["extension"])

AUTHORIZE_LIMIT_PER_USER = 20
REFRESH_LIMIT_PER_TOKEN = 10
#: Failed code exchanges and refreshes from one address in a minute. Only
#: failures count, so a whole office behind one NAT connecting and refreshing
#: at once never fills it; a stream of junk from one host does.
TOKEN_FAILURES_PER_IP = 60

_STATE_RE = r"^[A-Za-z0-9_-]{16,128}$"
_EXTENSION_SCHEMES = ("chrome-extension", "extension")
_TOKEN_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _refusal(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def _extension_id(db: AsyncSession) -> str:
    try:
        key = await get_signing_key(db)
    except ExtensionKeyUnavailable as exc:
        raise _refusal(503, "unavailable", str(exc)) from None
    if key is None:
        raise _refusal(400, "invalid_request", "This server has not handed out the browser extension yet.")
    return key.extension_id


def _is_connected_page(redirect_uri: str, extension_id: str) -> bool:
    """Only this installation's extension, and only its connected.html - character for character."""
    return redirect_uri in {f"{scheme}://{extension_id}/{CONNECTED_PAGE}" for scheme in _EXTENSION_SCHEMES}


class AuthorizeIn(BaseModel):
    redirect_uri: str = Field(max_length=200)
    code_challenge: str = Field(max_length=128)
    code_challenge_method: str = Field(max_length=16)
    state: str = Field(pattern=_STATE_RE)
    deny: bool = False


@router.post("/api/extension/authorize")
async def authorize_extension(
    body: AuthorizeIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Allow (or deny) the extension this browser is connecting; where to send the tab next."""
    await check_rate_limit(f"extension:authorize:{int(user.id)}", limit=AUTHORIZE_LIMIT_PER_USER)
    # The address is checked before anything is sent to it, a refusal included.
    if not _is_connected_page(body.redirect_uri, await _extension_id(db)):
        raise _refusal(400, "invalid_request", "That is not this server's browser extension.")
    if body.deny:
        return {"redirect_to": f"{body.redirect_uri}?{urlencode({'error': 'access_denied', 'state': body.state})}"}
    if body.code_challenge_method != "S256" or not is_valid_challenge(body.code_challenge):
        raise _refusal(400, "invalid_request", "The extension sent an unusable PKCE challenge.")
    if not await extension_permitted(db, user):
        raise _refusal(403, "not_permitted", "The browser extension is not enabled for your account.")
    code = await create_auth_code(user=user, redirect_uri=body.redirect_uri, code_challenge=body.code_challenge)
    return {"redirect_to": f"{body.redirect_uri}?{urlencode({'code': code, 'state': body.state})}"}


class TokenIn(BaseModel):
    grant_type: str = Field(max_length=32)
    code: str | None = Field(default=None, max_length=256)
    code_verifier: str | None = Field(default=None, max_length=256)
    redirect_uri: str | None = Field(default=None, max_length=200)
    device_name: str | None = Field(default=None, max_length=256)
    refresh_token: str | None = Field(default=None, max_length=256)


def _token_refusal(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message}, headers=_TOKEN_HEADERS)


async def _exchange_code(db: AsyncSession, body: TokenIn, request: Request, ip: str | None) -> TokenPair:
    if not (body.code and body.code_verifier and body.redirect_uri):
        raise ExtensionTokenError("invalid_request", "code, code_verifier and redirect_uri are required.")
    user = await redeem_auth_code(db, code=body.code, code_verifier=body.code_verifier, redirect_uri=body.redirect_uri)
    if not await extension_permitted(db, user):
        raise ExtensionTokenError("not_permitted", "The browser extension is not enabled for your account.")
    pair = await create_session(
        db,
        user=user,
        device_name=body.device_name,
        user_agent=request.headers.get("user-agent"),
        ip=ip,
    )
    await log_security_event(
        db,
        actor=user,
        actor_ip=ip,
        action=AUDIT_CONNECTED,
        resource_type=AUDIT_RESOURCE,
        resource_id=pair.session_id,
        detail={"device_name": clean_device_name(body.device_name)},
    )
    return pair


async def _refresh(db: AsyncSession, body: TokenIn, ip: str | None) -> TokenPair:
    if not body.refresh_token:
        raise ExtensionTokenError("invalid_request", "refresh_token is required.")
    await check_rate_limit(f"extension:refresh:{token_hash(body.refresh_token)[:32]}", limit=REFRESH_LIMIT_PER_TOKEN)
    return await refresh_session(db, body.refresh_token, ip=ip)


@router.post("/api/extension/token")
async def extension_token(body: TokenIn, request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Trade a connect code, or a refresh token, for a new pair of tokens."""
    ip = resolve_client_ip(request)
    failures = f"extension:token-failures:{ip or 'unknown'}"
    if await failure_limit_reached(failures, limit=TOKEN_FAILURES_PER_IP):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts from this address. Try again shortly.",
            headers=_TOKEN_HEADERS,
        )
    try:
        if body.grant_type == "authorization_code":
            pair = await _exchange_code(db, body, request, ip)
        elif body.grant_type == "refresh_token":
            pair = await _refresh(db, body, ip)
        else:
            raise ExtensionTokenError("invalid_request", "grant_type must be authorization_code or refresh_token.")
    except ExtensionTokenError as exc:
        await record_failure(failures)
        raise _token_refusal(exc.code, exc.message) from None
    await db.commit()
    return JSONResponse(pair.as_response(), headers=_TOKEN_HEADERS)


def _server_url() -> str | None:
    try:
        return normalize_origin(get_settings().frontend_url)
    except ValueError:
        return None


@router.get("/api/extension/me")
async def extension_me(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Who the connected browser works for, and what it may offer them.

    Open to any signed-in caller (a browser with the extension switched off
    asks it to learn why), so it says no more than that caller may know: not
    the server's exact build, which only administrators see, and the site and
    model rules only to someone who may use the extension.
    """
    settings = await load_extension_settings(db)
    features = await extension_features(db, user, settings)
    try:
        build = await current_build(db, request_host=request.url.hostname, client_ip=resolve_client_ip(request))
        latest: str | None = build.version
    except ExtensionUnavailable:
        latest = None
    policy = None
    if features["chat"]:
        policy = {
            "site_access": settings.site_access,
            "allowed_sites": list(settings.allowed_sites),
            "blocked_sites": list(settings.blocked_sites),
            "page_content_models": list(settings.page_content_models),
            "agent_models": list(settings.agent_models),
            "agent_max_steps": settings.agent_max_steps,
        }
    return {
        "user": {"username": user.username, "display_name": user.display_name, "email": user.email},
        "server": {"name": PRODUCT_NAME, "url": _server_url()},
        "extension": {"latest_version": latest, "min_version": MIN_SUPPORTED_VERSION},
        "features": features,
        "policy": policy,
    }


async def _disconnect(db: AsyncSession, request: Request, user: User, session_id: str, *, where: str) -> bool:
    session = await db.get(ExtensionSession, session_id)
    if session is None or int(session.user_id) != int(user.id):
        return False
    if not await revoke_session(db, session_id, reason=REVOKED_BY_USER, user_id=int(user.id)):
        return False
    await log_security_event(
        db,
        actor=user,
        actor_ip=resolve_client_ip(request),
        action=AUDIT_DISCONNECTED,
        resource_type=AUDIT_RESOURCE,
        resource_id=session_id,
        detail={"device_name": session.device_name, "from": where},
    )
    await db.commit()
    return True


@router.post("/api/extension/revoke")
async def revoke_this_browser(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The extension disconnects itself."""
    session_id = getattr(request.state, "extension_session_id", None)
    if not session_id:
        raise _refusal(400, "invalid_request", "Only a connected browser can disconnect itself.")
    await _disconnect(db, request, user, str(session_id), where="browser")
    return {"ok": True}


@router.get("/api/extension/sessions")
async def my_extension_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The browsers this account has connected and can still use."""
    return {
        "items": [
            {
                "id": row.id,
                "device_name": row.device_name,
                "created_at": _iso(row.created_at),
                "last_used_at": _iso(row.last_used_at),
                "last_ip": row.last_ip,
            }
            for row in await list_sessions(db, user)
        ]
    }


@router.delete("/api/extension/sessions/{session_id}")
async def disconnect_extension_session(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """End one of this account's connections, from Settings."""
    if not re.fullmatch(r"[0-9a-f-]{36}", session_id) or not await _disconnect(
        db, request, user, session_id, where="settings"
    ):
        raise HTTPException(status_code=404, detail="No such connected browser.")
    return {"ok": True}
