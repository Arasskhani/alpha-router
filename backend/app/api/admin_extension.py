"""Admin settings for the browser extension (the Chat Tools menu).

Who may use the extension and its agent is the Chat Tools ACL; this is the
rest - site access and site rules, models, the agent's limits - plus what IT
needs to force-install the extension with Group Policy.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_chat_tools, require_chat_tools_write
from app.database import get_db
from app.models.user import User
from app.services.client_ip import resolve_client_ip
from app.services.extension_distribution import ExtensionUnavailable, current_build, distribution_payload
from app.services.extension_keys import ExtensionKeyUnavailable, get_signing_key
from app.services.extension_settings import (
    MAX_MAX_STEPS,
    MAX_MODEL_REFS,
    MAX_SITE_PATTERNS,
    MIN_MAX_STEPS,
    ExtensionSettingsError,
    load_extension_settings,
    model_choices,
    save_extension_settings,
    validated_update,
)
from app.services.security_audit import log_security_event

router = APIRouter(prefix="/api/admin/extension", tags=["admin-extension"])


class ExtensionSettingsIn(BaseModel):
    site_access: Literal["per_site", "all_sites"]
    allowed_sites: list[str] = Field(default_factory=list, max_length=MAX_SITE_PATTERNS)
    blocked_sites: list[str] = Field(default_factory=list, max_length=MAX_SITE_PATTERNS)
    page_content_models: list[str] = Field(default_factory=list, max_length=MAX_MODEL_REFS)
    agent_models: list[str] = Field(default_factory=list, max_length=MAX_MODEL_REFS)
    agent_max_steps: int = Field(ge=MIN_MAX_STEPS, le=MAX_MAX_STEPS)
    agent_auto_mode: bool = False
    agent_review_model: str | None = Field(default=None, max_length=64)


async def _key_status(db: AsyncSession) -> dict:
    """The signing key on its own: a missing build or FRONTEND_URL must not hide an unreadable key."""
    try:
        key = await get_signing_key(db)
    except ExtensionKeyUnavailable as exc:
        return {"key_status": "unreadable", "key_message": str(exc)}
    if key is None:
        return {"key_status": "not_created", "key_message": None}
    return {"key_status": "ok", "key_message": None}


async def _overview(db: AsyncSession, request: Request) -> dict:
    settings = await load_extension_settings(db)
    try:
        build = await current_build(db, request_host=request.url.hostname, client_ip=resolve_client_ip(request))
        unavailable = None
    except ExtensionUnavailable as exc:
        build, unavailable = None, exc
    distribution = {**distribution_payload(build, unavailable), **await _key_status(db)}
    return {"settings": settings.to_json(), "models": await model_choices(db, settings), "distribution": distribution}


@router.get("/settings")
async def read_extension_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_chat_tools),
) -> dict:
    return await _overview(db, request)


@router.put("/settings")
async def replace_extension_settings(
    body: ExtensionSettingsIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_chat_tools_write),
) -> dict:
    current = await load_extension_settings(db)
    try:
        updated = await validated_update(db, current, **body.model_dump())
    except ExtensionSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await save_extension_settings(db, updated)
    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action="extension_settings_updated",
        resource_type="extension_settings",
        resource_id="browser_extension",
        detail={"before": current.to_json(), "after": updated.to_json()},
    )
    await db.commit()
    return await _overview(db, request)
