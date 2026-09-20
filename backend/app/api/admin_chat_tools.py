"""Grant and revoke the chat tools, one page's worth of API.

The page this serves lists every tool in
:mod:`app.services.chat_tool_registry` and nothing else, so a tool registered
today has a row here today - no endpoint, no schema and no page change. That
is the whole point of keying the policy by a registry key rather than by a
table of its own.

Changes are recorded with :func:`app.services.security_audit.log_security_event`,
which puts them in the same trail as every other administrative act and makes
them visible in Admin Logs without a new source.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_chat_tools, require_chat_tools_write
from app.database import get_db
from app.models.user import User
from app.services.chat_tool_access_service import (
    chat_tool_overview,
    get_chat_tool_access,
    set_chat_tool_access,
)
from app.services.client_ip import resolve_client_ip
from app.services.resource_access_service import AccessGrant
from app.services.security_audit import log_security_event

router = APIRouter(prefix="/api/admin/chat-tools", tags=["chat-tools"])


class AccessGrantBody(BaseModel):
    target_type: str = Field(pattern=r"^(user|group|department|role)$")
    target: int | str
    effect: str = Field(default="allow", pattern=r"^(allow|deny)$")


class ChatToolAccessBody(BaseModel):
    access_type: str = Field(pattern=r"^(public|private)$")
    grants: list[AccessGrantBody] = Field(default_factory=list)


def _audit_view(saved: dict[str, Any]) -> dict[str, Any]:
    """What goes in the trail: the decision, not the row ids behind it."""
    return {
        "access_type": saved["access_type"],
        "grants": sorted((f"{grant['target_type']}:{grant['target']}", grant["effect"]) for grant in saved["grants"]),
    }


@router.get("")
async def list_chat_tools(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_chat_tools),
) -> list[dict[str, Any]]:
    """Every registered tool with its saved policy."""
    return await chat_tool_overview(db)


@router.get("/{tool_key}/access")
async def read_chat_tool_access(
    tool_key: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_chat_tools),
) -> dict[str, Any]:
    return await get_chat_tool_access(db, tool_key)


@router.put("/{tool_key}/access")
async def replace_chat_tool_access(
    tool_key: str,
    body: ChatToolAccessBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_chat_tools_write),
) -> dict[str, Any]:
    """Replace one tool's policy, and record who changed it from what."""
    before = await get_chat_tool_access(db, tool_key)
    try:
        saved = await set_chat_tool_access(
            db,
            tool_key,
            access_type=body.access_type,
            grants=[
                AccessGrant(target_type=grant.target_type, target=grant.target, effect=grant.effect)
                for grant in body.grants
            ],
            assigned_by_user_id=actor.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await log_security_event(
        db,
        actor=actor,
        actor_ip=resolve_client_ip(request),
        action="chat_tool_access_changed",
        resource_type="chat_tool",
        resource_id=tool_key,
        detail={"before": _audit_view(before), "after": _audit_view(saved)},
    )
    await db.commit()
    return saved
