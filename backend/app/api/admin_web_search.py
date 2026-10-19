"""Admin: the chat's Web Search - its fallback switch, and trying a search connection before relying on it.

The search connections themselves are made under Connections (kind
``web_search``); this router holds what is not a connection: whether
DuckDuckGo is asked after them, which services a search asks now, and a
Test that runs one real search with a draft or a saved connection.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_connections, require_connections_write
from app.database import get_db
from app.models.connection import Connection
from app.models.user import User
from app.services.client_ip import resolve_client_ip
from app.services.connection_kinds import (
    CONNECTION_KIND_WEB_SEARCH,
    NO_KEY_PROVIDERS,
    WEB_SEARCH_PROVIDERS,
    search_config,
)
from app.services.rate_limit import check_rate_limit
from app.services.security_audit import log_security_event
from app.services.web_search_providers import SearchTarget, WebSearchError, run_search
from app.services.web_search_service import (
    WebSearchSettings,
    connection_target,
    load_web_search_settings,
    save_web_search_settings,
    search_plan,
)

router = APIRouter(prefix="/api/admin/web-search", tags=["admin"])

#: What the Test searches for when the administrator names nothing.
DEFAULT_TEST_QUERY = "Alpharouter open source AI platform"
#: Tests one administrator may run a minute: each is a real, possibly billed, search.
TESTS_PER_MINUTE = 20


async def _overview(db: AsyncSession) -> dict[str, Any]:
    settings = await load_web_search_settings(db)
    plan = await search_plan(db)
    return {
        "settings": settings.to_json(),
        # The services a search asks now, in order: what the chat's Web Search will do.
        "plan": [
            {"label": step.label, "provider": step.target.provider, "connection_id": step.connection_id}
            for step in plan
        ],
        "available": bool(plan),
    }


@router.get("")
async def get_web_search(db: AsyncSession = Depends(get_db), _: User = Depends(require_connections)):
    return await _overview(db)


class WebSearchSettingsIn(BaseModel):
    duckduckgo_fallback: bool


@router.put("")
async def put_web_search(
    body: WebSearchSettingsIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_connections_write),
):
    before = await load_web_search_settings(db)
    after = WebSearchSettings(duckduckgo_fallback=body.duckduckgo_fallback)
    await save_web_search_settings(db, after)
    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action="web_search_settings_updated",
        resource_type="web_search_settings",
        resource_id="web_search",
        detail={"before": before.to_json(), "after": after.to_json()},
    )
    await db.commit()
    return await _overview(db)


class WebSearchTestIn(BaseModel):
    #: A saved connection to try; its stored key is used unless ``api_key`` is given.
    connection_id: int | None = Field(None, ge=1)
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    config: dict[str, Any] | None = None
    query: str | None = Field(None, max_length=200)


async def _test_target(db: AsyncSession, body: WebSearchTestIn) -> SearchTarget:
    from app.api.admin import _validated_connection_base_url

    stored: SearchTarget | None = None
    if body.connection_id is not None:
        conn = await db.get(Connection, body.connection_id)
        if conn is None or conn.kind != CONNECTION_KIND_WEB_SEARCH:
            raise HTTPException(404, detail="No such web search connection.")
        stored = connection_target(conn)
    provider = (body.provider_type or (stored.provider if stored else "")).strip().lower()
    if provider not in WEB_SEARCH_PROVIDERS:
        raise HTTPException(400, detail=f"A web search connection is one of: {', '.join(WEB_SEARCH_PROVIDERS)}.")
    base_url = await _validated_connection_base_url(body.base_url) if body.base_url is not None else None
    if base_url is None and stored is not None and stored.provider == provider:
        base_url = stored.base_url
    key = (body.api_key or "").strip()
    if not key and stored is not None and stored.provider == provider:
        key = stored.api_key
    if provider not in NO_KEY_PROVIDERS and not key:
        raise HTTPException(400, detail="This search service needs its API key.")
    raw_config = body.config if body.config is not None else (stored.config if stored else None)
    try:
        config = search_config(provider, raw_config)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from None
    return SearchTarget(provider=provider, api_key=key, base_url=base_url, config=config)


@router.post("/test")
async def test_web_search(
    body: WebSearchTestIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_connections_write),
):
    """One real search with a draft or saved connection: what came back, how long it took, or why it failed."""
    await check_rate_limit(f"admin_web_search_test:{admin.id}", limit=TESTS_PER_MINUTE, window_seconds=60)
    target = await _test_target(db, body)
    query = (body.query or "").strip() or DEFAULT_TEST_QUERY
    started = time.monotonic()
    try:
        results = await run_search(target, query, 5)
    except WebSearchError as exc:
        return {
            "ok": False,
            "error": {"code": exc.code, "message": exc.message},
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "results": [{"title": row.title, "url": row.url} for row in results],
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }
