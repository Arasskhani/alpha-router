"""OpenAI-compatible gateway for Open WebUI and Alpharouter API keys."""

import secrets
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.branding import INTERNAL_DOMAIN
from app.config import get_settings
from app.core.security import hash_password
from app.database import get_db
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.alpha_router_api_key_service import ensure_key_usable
from app.services.api_key_connection_policy import (
    allowed_connection_ids_for_key,
    filter_models_for_connections,
)
from app.services.api_key_model_policy import (
    allowed_model_ids_for_key,
    filter_models_for_allowlist,
)
from app.services.model_access_service import (
    filter_models_for_subject,
    resolve_access_subject,
)
from app.services.proxy_service import (
    STREAM_SSE_HEADERS,
    configure_litellm_cache,
    create_embedding,
    preflight_stream_chat,
    stream_chat,
)
from app.services.user_service import get_user_by_api_key
from app.utils.app_attribution import detect_client_app


def _is_master_key(candidate: str) -> bool:
    """Constant-time comparison: ``==`` on secrets leaks length/prefix timing."""
    expected = str(settings.gateway_master_key or "")
    if not expected:
        return False
    return secrets.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


router = APIRouter(tags=["gateway"])
settings = get_settings()
configure_litellm_cache()

GATEWAY_SERVICE_USERNAME = "gateway-service"


async def _get_or_create_gateway_service_user(db: AsyncSession) -> User:
    """Fixed service identity for master-key usage.

    Replaces the previous body.user impersonation: the master key now maps to a
    single dedicated service account instead of any caller-supplied identity.
    The account carries an unknown random password so it cannot log in via the UI.
    """
    user = (await db.execute(select(User).where(User.username == GATEWAY_SERVICE_USERNAME))).scalars().first()
    if user:
        return user
    user = User(
        username=GATEWAY_SERVICE_USERNAME,
        email=f"gateway-service@{INTERNAL_DOMAIN}",
        display_name="Gateway Service",
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        auth_provider="system",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@dataclass
class GatewayAuth:
    user_id: int | None
    username: str
    source: str
    skip_budget: bool
    alpha_router_api_key_id: int | None
    user_api_key_id: int | None
    client_app: str | None


async def _resolve_gateway_auth(
    request: Request,
    db: AsyncSession,
) -> GatewayAuth:
    auth = request.headers.get("Authorization", "")
    raw_key = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""

    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    skip_budget = False
    source = "openwebui"
    user_id = None
    alpha_router_api_key_id = None
    user_api_key_id = None
    username = "gateway"
    client_app = detect_client_app(request)

    if _is_master_key(raw_key):
        # Master key → fixed service identity. body.user is intentionally ignored
        # to prevent impersonation. Usage debits the service account's budget, so
        # the key is denied (402) until an admin assigns a budget plan to it.
        user = await _get_or_create_gateway_service_user(db)
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Gateway service account disabled")
        user_id = user.id
        username = user.username
        source = "master"
    else:
        user, source, router_key, user_api_key = await get_user_by_api_key(db, raw_key)
        if source == "alpha_router_key" and router_key:
            await ensure_key_usable(db, router_key)
            skip_budget = True
            alpha_router_api_key_id = router_key.id
            user_id = None
            username = router_key.name
        elif user:
            if not user.is_active:
                raise HTTPException(status_code=403, detail="Account disabled")
            user_id = user.id
            username = user.username
            if user_api_key is not None:
                user_api_key_id = user_api_key.id
        else:
            raise HTTPException(status_code=401, detail="Invalid API key")

    return GatewayAuth(
        user_id=user_id,
        username=username,
        source=source,
        skip_budget=skip_budget,
        alpha_router_api_key_id=alpha_router_api_key_id,
        user_api_key_id=user_api_key_id,
        client_app=client_app,
    )


async def _require_valid_gateway_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Auth gate for read-only gateway routes (e.g. /v1/models).

    Accepts the master key or any valid user/Alpharouter API key; rejects missing or
    unknown keys with 401. Does not consume budget.
    """
    auth = request.headers.get("Authorization", "")
    raw_key = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""
    if not raw_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    if _is_master_key(raw_key):
        return
    user, source, router_key, user_api_key = await get_user_by_api_key(db, raw_key)
    if source == "alpha_router_key" and router_key:
        await ensure_key_usable(db, router_key)
        return
    if user:
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account disabled")
        return
    raise HTTPException(status_code=401, detail="Invalid API key")


@router.get("/v1/models")
async def list_models(request: Request, db: AsyncSession = Depends(get_db)):
    auth_ctx = await _resolve_gateway_auth(request, db)
    rows = (
        (
            await db.execute(
                select(AIModel)
                .join(Connection, Connection.id == AIModel.connection_id)
                .where(AIModel.is_enabled == True, Connection.is_active == True)  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
    subject = await resolve_access_subject(
        db,
        user_id=auth_ctx.user_id,
        alpha_router_api_key_id=auth_ctx.alpha_router_api_key_id,
        source=auth_ctx.source,
    )
    rows = await filter_models_for_subject(db, list(rows), subject)
    allowed_connection_ids = await allowed_connection_ids_for_key(db, auth_ctx.alpha_router_api_key_id)
    rows = filter_models_for_connections(rows, allowed_connection_ids)
    allowed_model_ids = await allowed_model_ids_for_key(db, auth_ctx.alpha_router_api_key_id)
    rows = filter_models_for_allowlist(rows, allowed_model_ids)
    return {
        "object": "list",
        "data": [
            {
                "id": m.external_id,
                "object": "model",
                "owned_by": m.provider_type,
            }
            for m in rows
        ],
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, db: AsyncSession = Depends(get_db)):
    auth_ctx = await _resolve_gateway_auth(request, db)
    body = await request.json()
    if request.headers.get("Idempotency-Key"):
        body["_idempotency_key"] = request.headers["Idempotency-Key"]

    if body.get("stream", True):
        resolved = await preflight_stream_chat(
            db,
            body,
            user_id=auth_ctx.user_id,
            skip_budget=auth_ctx.skip_budget,
            alpha_router_api_key_id=auth_ctx.alpha_router_api_key_id,
            source=auth_ctx.source,
            client_app=auth_ctx.client_app,
        )
        try:
            await db.commit()
        except BaseException:
            permit = getattr(resolved, "code_interpreter_capacity_permit", None)
            if permit is not None:
                from app.services.code_interpreter_capacity_service import (
                    release_code_interpreter_turn,
                )

                await release_code_interpreter_turn(permit)
            raise
        gen = stream_chat(
            request,
            body,
            user_id=auth_ctx.user_id,
            username=auth_ctx.username,
            source=auth_ctx.source,
            client_app=auth_ctx.client_app,
            skip_budget=auth_ctx.skip_budget,
            alpha_router_api_key_id=auth_ctx.alpha_router_api_key_id,
            user_api_key_id=auth_ctx.user_api_key_id,
            resolved=resolved,
        )
        permit = getattr(resolved, "code_interpreter_capacity_permit", None)

        async def release_capacity_fallback() -> None:
            if permit is not None:
                from app.services.code_interpreter_capacity_service import (
                    release_code_interpreter_turn,
                )

                await release_code_interpreter_turn(permit)

        return StreamingResponse(
            gen,
            media_type="text/event-stream",
            headers=STREAM_SSE_HEADERS,
            background=(BackgroundTask(release_capacity_fallback) if permit is not None else None),
        )
    raise HTTPException(status_code=400, detail="Non-streaming mode: use stream=true")


@router.post("/v1/embeddings")
async def embeddings(request: Request, db: AsyncSession = Depends(get_db)):
    auth_ctx = await _resolve_gateway_auth(request, db)
    body = await request.json()
    if request.headers.get("Idempotency-Key"):
        body["_idempotency_key"] = request.headers["Idempotency-Key"]
    payload = await create_embedding(
        db,
        body,
        user_id=auth_ctx.user_id,
        username=auth_ctx.username,
        source=auth_ctx.source,
        skip_budget=auth_ctx.skip_budget,
        alpha_router_api_key_id=auth_ctx.alpha_router_api_key_id,
        user_api_key_id=auth_ctx.user_api_key_id,
        client_app=auth_ctx.client_app,
        source_ip=request.client.host if request.client else None,
    )
    return JSONResponse(content=payload)
