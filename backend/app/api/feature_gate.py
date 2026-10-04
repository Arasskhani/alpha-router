"""Refuse the web Chat or Projects to an account Feature Access has closed them to.

The routes of a personal chat and of a project chat are partly shared: a
chat's messages are read and written under ``/api/user/chat-sessions/{id}``
whichever it is, and one completions endpoint answers both. So a gate on a
chat looks at the chat - a chat in a project needs Projects, any other chat
needs Chat - and a project chat keeps working for someone whose Chat is off.

The browser extension uses some of the same routes. It has its own access
(Chat Tools), so a request it makes is never refused here.
"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.chat import ChatSession
from app.models.feature_access import FEATURE_CHAT, FEATURE_PROJECTS
from app.models.user import User
from app.services.feature_access_service import require_feature


def _from_extension(request: Request) -> bool:
    return bool(getattr(request.state, "extension_session_id", None))


async def chat_sections(db: AsyncSession, chat_session_id: str | None, project_id: str | None = None) -> set[str]:
    """The sections a request about a chat needs: Projects for a project chat, Chat for any other.

    Both, when the request names a project and a chat that is not in one: a
    project id must not carry a personal chat past a closed Chat.
    """
    needed: set[str] = set()
    if (project_id or "").strip():
        needed.add(FEATURE_PROJECTS)
    sid = (chat_session_id or "").strip()
    if sid:
        row = (await db.execute(select(ChatSession.project_id).where(ChatSession.id == sid))).first()
        if row is not None:
            needed.add(FEATURE_PROJECTS if row[0] else FEATURE_CHAT)
    return needed or {FEATURE_CHAT}


async def require_chat_feature_for(
    db: AsyncSession,
    request: Request,
    user: User,
    *,
    chat_session_id: str | None = None,
    project_id: str | None = None,
) -> None:
    """For a handler that learns from its body which chat it is about."""
    if _from_extension(request):
        return
    for feature in sorted(await chat_sections(db, chat_session_id, project_id)):
        await require_feature(db, user, feature)


async def require_web_chat(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """A route of the personal chat list: its list, search and folders."""
    if _from_extension(request):
        return
    await require_feature(db, user, FEATURE_CHAT)


async def require_web_projects(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Every route under /api/projects."""
    if _from_extension(request):
        return
    await require_feature(db, user, FEATURE_PROJECTS)


async def require_session_section(
    session_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """A route about one chat, by the ``session_id`` in its path."""
    await require_chat_feature_for(db, request, user, chat_session_id=session_id)
