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


async def _stored_chat_project(db: AsyncSession, chat_session_id: str | None) -> tuple[bool, str | None]:
    """Whether the chat is stored, and the project it is in (None for a personal chat)."""
    sid = (chat_session_id or "").strip()
    if not sid:
        return False, None
    row = (await db.execute(select(ChatSession.project_id).where(ChatSession.id == sid))).first()
    if row is None:
        return False, None
    return True, (str(row[0]) if row[0] else None)


async def _may_write_in_project(db: AsyncSession, user: User, project_id: str) -> bool:
    from app.services.project_access_service import resolve_project_access

    access = await resolve_project_access(db, project_id=project_id, user=user)
    return access is not None and access.can("chat.write")


async def chat_sections(
    db: AsyncSession,
    user: User,
    chat_session_id: str | None,
    project_id: str | None = None,
    *,
    unsaved_is_project: bool = True,
) -> set[str]:
    """The sections a request about a chat needs: Projects for a project chat, Chat for any other.

    A stored chat decides by where it is: in a project it needs Projects (and
    a project id beside it changes nothing); a personal one needs Chat, and
    Projects too when the request also names a project.

    A chat not stored yet counts as the project's only when the person may
    write chats in that project, and - for a turn (``unsaved_is_project``
    false unless the turn is saved) - only when the turn is saved there. A
    project id alone must not carry a personal turn past a closed Chat: an
    unsaved turn with a project id is a personal turn to the chat pipeline.
    """
    pid = (project_id or "").strip()
    stored, in_project = await _stored_chat_project(db, chat_session_id)
    if stored:
        if in_project:
            return {FEATURE_PROJECTS}
        return {FEATURE_CHAT, FEATURE_PROJECTS} if pid else {FEATURE_CHAT}
    if pid:
        if unsaved_is_project and await _may_write_in_project(db, user, pid):
            return {FEATURE_PROJECTS}
        return {FEATURE_CHAT, FEATURE_PROJECTS}
    return {FEATURE_CHAT}


async def require_chat_feature_for(
    db: AsyncSession,
    request: Request,
    user: User,
    *,
    chat_session_id: str | None = None,
    project_id: str | None = None,
    unsaved_is_project: bool = True,
) -> None:
    """For a handler that learns from its body which chat it is about."""
    if _from_extension(request):
        return
    needed = await chat_sections(db, user, chat_session_id, project_id, unsaved_is_project=unsaved_is_project)
    for feature in sorted(needed):
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
    """A route about one chat, by the ``session_id`` in its path.

    A chat that is not stored is left to the route, which answers 404: the web
    app asks that way whether a new chat - a project one too - is on the
    server yet, and a 403 there would stop it from creating it.
    """
    if _from_extension(request):
        return
    await require_stored_chat_section(db, user, session_id)


async def require_stored_chat_section(db: AsyncSession, user: User, chat_session_id: str | None) -> None:
    """The section of a stored chat, when there is one: for a route that reaches a chat through
    something else (an agent run, a handoff). A chat not stored, or none, is left to the route."""
    stored, in_project = await _stored_chat_project(db, chat_session_id)
    if stored:
        await require_feature(db, user, FEATURE_PROJECTS if in_project else FEATURE_CHAT)
