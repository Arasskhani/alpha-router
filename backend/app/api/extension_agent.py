"""What a connected browser's agent reports, and the reviewer it asks in Auto mode.

Both are for the extension's own token and for users the administrator lets
use the agent. ``events`` records steps and runs for Admin Logs; ``review-action``
answers ``allow`` or ``ask`` for one proposed action, and ``ask`` whenever it
cannot answer.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.client_ip import resolve_client_ip
from app.services.extension_access import AGENT_TOOL, permitted_extension_tools
from app.services.extension_agent import (
    MAX_EVENTS_PER_CALL,
    AgentEventError,
    ReviewVerdict,
    agent_event,
    agent_event_rows,
    review_action,
)
from app.services.extension_settings import load_extension_settings
from app.services.rate_limit import check_rate_limit

router = APIRouter(tags=["extension"])

#: Calls to ``events`` a minute from one connected browser: batches, so far fewer are needed.
EVENTS_CALLS_PER_MINUTE = 120
#: Reviews a minute from one connected browser: one per action at most, and steps are slower than that.
REVIEWS_PER_MINUTE = 60


def _refusal(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def _agent_session(request: Request, db: AsyncSession, user: User) -> str:
    """This connected browser's session, once it is sure its user may use the agent."""
    session_id = getattr(request.state, "extension_session_id", None)
    if not session_id:
        raise _refusal(400, "extension_only", "Only the browser extension can do this.")
    if AGENT_TOOL not in await permitted_extension_tools(db, user):
        raise _refusal(403, "agent_not_permitted", "The browser agent is not enabled for your account.")
    return str(session_id)


class AgentEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["agent_step", "agent_task"]
    #: The host the step acted on (or the run started on); never a full URL.
    site: str | None = Field(None, max_length=253)
    #: The tool, for a step.
    action: str | None = Field(None, max_length=64)
    outcome: str | None = Field(None, max_length=16)
    detail: dict[str, Any] = Field(default_factory=dict)


class AgentEventsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[AgentEventIn] = Field(..., min_length=1, max_length=MAX_EVENTS_PER_CALL)


@router.post("/api/extension/events")
async def record_agent_events(
    body: AgentEventsIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The agent's steps and runs, for Admin Logs: only the fields it keeps, never typed text."""
    session_id = await _agent_session(request, db, user)
    await check_rate_limit(f"extension:events:{session_id}", limit=EVENTS_CALLS_PER_MINUTE)
    try:
        events = [agent_event(e.kind, e.site, e.action, e.outcome, e.detail) for e in body.events]
    except AgentEventError as exc:
        raise _refusal(400, "invalid_request", str(exc)) from None
    db.add_all(agent_event_rows(events, user=user, ip=resolve_client_ip(request), session_id=session_id))
    await db.commit()
    return {"recorded": len(events)}


#: The size of a proposed action's arguments as JSON.
MAX_ARGUMENTS_BYTES = 4096


class ReviewActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The user's request, in their words.
    task: str = Field(..., min_length=1, max_length=4000)
    tool: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,63}$")
    site: str = Field(..., min_length=1, max_length=253)
    #: The element: its role and accessible name.
    target: str | None = Field(None, max_length=300)
    arguments: dict[str, Any] = Field(default_factory=dict)
    #: The steps so far, one short line each.
    history: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("arguments")
    @classmethod
    def _small_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":"), default=str).encode()) > MAX_ARGUMENTS_BYTES:
            raise ValueError(f"The arguments are at most {MAX_ARGUMENTS_BYTES} bytes.")
        return value


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


@router.post("/api/extension/review-action")
async def review_agent_action(
    body: ReviewActionIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Whether Auto mode may take this action without asking: ``allow``, or ``ask`` the user."""
    session_id = await _agent_session(request, db, user)
    settings = await load_extension_settings(db)
    if not (settings.agent_auto_mode and settings.agent_review_model):
        raise _refusal(403, "auto_mode_off", "Auto mode is off: ask the user.")
    try:
        await check_rate_limit(f"extension:review:{session_id}", limit=REVIEWS_PER_MINUTE)
    except HTTPException:
        return ReviewVerdict("ask", "Too many reviews in a minute.").to_json()
    verdict = await review_action(
        db,
        user=user,
        settings=settings,
        task=body.task,
        tool=body.tool,
        site=body.site,
        target=body.target,
        arguments=body.arguments,
        history=[_clip(line, 300) for line in body.history],
    )
    return verdict.to_json()
