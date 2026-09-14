"""Per-user composer prefs for a project chat (tools, model, Agent).

Shared ``ChatSession`` rows keep messages, title, and pin state. Tool toggles,
the selected model, and Agent binding are stored per ``(project, session, user)``
so one member's composer never drives another member's turn.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession, is_member_channel
from app.models.project import ProjectChatComposerPref
from app.services.project_access_service import (
    require_capability,
    resolve_project_access,
)

_MAX_TOOLS_BYTES = 16 * 1024
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _empty_pref_payload() -> dict[str, Any]:
    return {
        "tools": {},
        "toolsTouched": False,
        "model": None,
        "selectedAgentSlug": None,
    }


def _pref_to_client(row: ProjectChatComposerPref | None) -> dict[str, Any]:
    if row is None:
        return _empty_pref_payload()
    tools = row.tools if isinstance(row.tools, dict) else {}
    return {
        "tools": tools,
        "toolsTouched": bool(row.tools_touched),
        "model": (row.model_id or None),
        "selectedAgentSlug": row.selected_agent_slug,
    }


def _check_tools_size(value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_TOOLS_BYTES:
        raise ValueError("Composer tools exceed storage limit")


def _normalize_agent_slug(raw: Any) -> str | None:
    slug = str(raw or "").strip().lower()
    if not slug or slug == "none":
        return None
    if slug == "auto":
        return "auto"
    if len(slug) > 128 or not _SLUG_RE.fullmatch(slug):
        raise ValueError("selectedAgentSlug is invalid")
    return slug


async def _load_project_session(db: AsyncSession, *, project_id: str, session_id: str) -> ChatSession | None:
    row = await db.get(ChatSession, session_id)
    if row is None or row.project_id != project_id or is_member_channel(row):
        return None
    return row


async def get_project_chat_composer_prefs(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    user: object,
) -> dict[str, Any] | None:
    """Return this user's composer prefs. Missing row → empty defaults."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None
    session = await _load_project_session(db, project_id=project_id, session_id=session_id)
    if session is None:
        return None
    user_id = getattr(user, "id", None)
    if user_id is None:
        return _empty_pref_payload()
    pref = await db.get(ProjectChatComposerPref, (project_id, session_id, int(user_id)))
    return _pref_to_client(pref)


async def upsert_project_chat_composer_prefs(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    user: object,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Create or replace this user's composer prefs for a project chat."""
    await require_capability(db, project_id=project_id, user=user, capability="chat.write")
    session = await _load_project_session(db, project_id=project_id, session_id=session_id)
    if session is None:
        return None
    user_id = getattr(user, "id", None)
    if user_id is None:
        raise ValueError("User is required")

    tools = payload.get("tools") if isinstance(payload.get("tools"), dict) else {}
    _check_tools_size(tools)
    tools_touched = bool(payload.get("toolsTouched") or payload.get("tools_touched"))
    model_raw = payload.get("model")
    if model_raw is None:
        model_raw = payload.get("model_id")
    model_id = str(model_raw or "").strip()[:512] or None
    agent_slug = _normalize_agent_slug(payload.get("selectedAgentSlug", payload.get("selected_agent_slug")))

    now = dt.datetime.utcnow()
    key = (project_id, session_id, int(user_id))
    row = await db.get(ProjectChatComposerPref, key)
    if row is None:
        row = ProjectChatComposerPref(
            project_id=project_id,
            session_id=session_id,
            user_id=int(user_id),
            tools=tools,
            tools_touched=tools_touched,
            model_id=model_id,
            selected_agent_slug=agent_slug,
            updated_at=now,
        )
        db.add(row)
    else:
        row.tools = tools
        row.tools_touched = tools_touched
        row.model_id = model_id
        row.selected_agent_slug = agent_slug
        row.updated_at = now
    await db.flush()
    return _pref_to_client(row)
