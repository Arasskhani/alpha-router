"""OpenAI-compatible gateway for Open WebUI and NITRO API keys."""

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.model_catalog import AIModel
from app.services.proxy_service import (
    STREAM_SSE_HEADERS,
    configure_litellm_cache,
    create_embedding,
    preflight_stream_chat,
    stream_chat,
)
from app.services.nitro_api_key_service import ensure_key_usable
from app.services.user_service import get_or_create_user_from_request, get_user_by_api_key
from app.utils.app_attribution import detect_client_app

router = APIRouter(tags=["gateway"])
settings = get_settings()
configure_litellm_cache()


@dataclass
class GatewayAuth:
    user_id: int | None
    username: str
    source: str
    skip_budget: bool
    nitro_api_key_id: int | None
    client_app: str | None


async def _resolve_gateway_auth(
    request: Request,
    db: AsyncSession,
    body: dict,
) -> GatewayAuth:
    auth = request.headers.get("Authorization", "")
    raw_key = auth.replace("Bearer ", "").strip() if auth.startswith("Bearer ") else ""

    skip_budget = False
    source = "openwebui"
    user_id = None
    nitro_api_key_id = None
    username = body.get("user", "anonymous@local")
    client_app = detect_client_app(request)

    if raw_key and raw_key != settings.gateway_master_key:
        user, source, nitro_key = await get_user_by_api_key(db, raw_key)
        if source == "nitro_key" and nitro_key:
            await ensure_key_usable(db, nitro_key)
            skip_budget = True
            nitro_api_key_id = nitro_key.id
            user_id = None
            username = nitro_key.name
        elif user:
            if not user.is_active:
                raise HTTPException(status_code=403, detail="Account disabled")
            user_id = user.id
            username = user.username
        else:
            raise HTTPException(status_code=401, detail="Invalid API key")
    else:
        user = await get_or_create_user_from_request(db, username)
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account disabled")
        user_id = user.id
        username = user.username

    return GatewayAuth(
        user_id=user_id,
        username=username,
        source=source,
        skip_budget=skip_budget,
        nitro_api_key_id=nitro_api_key_id,
        client_app=client_app,
    )


@router.get("/v1/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AIModel).where(AIModel.is_enabled == True))).scalars().all()  # noqa: E712
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
    body = await request.json()
    auth_ctx = await _resolve_gateway_auth(request, db, body)

    if body.get("stream", True):
        resolved = await preflight_stream_chat(
            db,
            body,
            user_id=auth_ctx.user_id,
            skip_budget=auth_ctx.skip_budget,
            nitro_api_key_id=auth_ctx.nitro_api_key_id,
        )
        gen = stream_chat(
            request,
            body,
            user_id=auth_ctx.user_id,
            username=auth_ctx.username,
            source=auth_ctx.source,
            client_app=auth_ctx.client_app,
            skip_budget=auth_ctx.skip_budget,
            nitro_api_key_id=auth_ctx.nitro_api_key_id,
            resolved=resolved,
        )
        return StreamingResponse(
            gen,
            media_type="text/event-stream",
            headers=STREAM_SSE_HEADERS,
        )
    raise HTTPException(status_code=400, detail="Non-streaming mode: use stream=true")


@router.post("/v1/embeddings")
async def embeddings(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    auth_ctx = await _resolve_gateway_auth(request, db, body)
    payload = await create_embedding(
        db,
        body,
        user_id=auth_ctx.user_id,
        username=auth_ctx.username,
        source=auth_ctx.source,
        skip_budget=auth_ctx.skip_budget,
        nitro_api_key_id=auth_ctx.nitro_api_key_id,
        client_app=auth_ctx.client_app,
        source_ip=request.client.host if request.client else None,
    )
    return JSONResponse(content=payload)
