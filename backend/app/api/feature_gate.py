"""Refuse the web Chat or Projects to an account Feature Access has closed them to.

The routes of a personal chat and of a project chat are partly shared: a
chat's messages are read and written under ``/api/user/chat-sessions/{id}``
whichever it is, and one completions endpoint answers both. So a gate on a
chat looks at the chat - a chat in a project needs Projects, any other chat
needs Chat - and a project chat keeps working for someone whose Chat is off.

Except in a project of their own that nobody else is in: there the chat is
a personal chat by another name, so while their Chat is closed it is closed
too (:func:`project_chat_closed`). Its files, rooms and members still work,
and the chat opens again once a second member joins.

The browser extension uses some of the same routes. It has its own access
(the Browser extension section, and Chat Tools; see
``app.services.extension_access``), so a request it makes is never refused here.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.chat import ChatSession
from app.models.feature_access import FEATURE_CHAT, FEATURE_PROJECTS
from app.models.project import PROJECT_ROLE_PRIMARY_OWNER, ProjectMember
from app.models.user import User
from app.services.feature_access_service import FEATURE_FORBIDDEN_CODE, decide_all, feature_forbidden

#: Why a project's chat is refused when Chat is: the project has no member but its owner.
SOLO_PROJECT_REASON = "solo_project"


def _from_extension(request: Request) -> bool:
    return bool(getattr(request.state, "extension_session_id", None))


async def _allowed(request: Request | None, db: AsyncSession, user: User, feature: str) -> bool:
    """One section's decision, read once per request.

    The gates of one request ask about Chat and Projects more than once (the
    Projects router, then the chat in a project), so both are decided together
    on the first question and kept on the request.
    """
    cache: dict[str, bool] | None = getattr(request.state, "feature_allowed", None) if request is not None else None
    if cache is None:
        cache = {}
        if request is not None:
            request.state.feature_allowed = cache
    if feature not in cache:
        wanted = list(dict.fromkeys([feature, FEATURE_CHAT, FEATURE_PROJECTS]))
        for key, decision in (await decide_all(db, user, wanted)).items():
            cache[key] = decision.allowed
    return cache[feature]


async def _require(request: Request | None, db: AsyncSession, user: User, feature: str) -> None:
    if not await _allowed(request, db, user, feature):
        raise feature_forbidden(feature)


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


async def project_chat_closed(
    db: AsyncSession, user: User, project_id: str | None, request: Request | None = None
) -> bool:
    """Whether this person's Chat is closed and the project is theirs alone.

    Theirs alone: they are its Primary Owner and no one else is a member
    (pending invitations do not count). Their Chat is read first, so an open
    Chat - nearly everyone - costs no look at the members.
    """
    pid = (project_id or "").strip()
    if not pid or await _allowed(request, db, user, FEATURE_CHAT):
        return False
    members = (
        await db.execute(
            select(ProjectMember.user_id, ProjectMember.role).where(ProjectMember.project_id == pid).limit(2)
        )
    ).all()
    return len(members) == 1 and int(members[0][0]) == int(user.id) and members[0][1] == PROJECT_ROLE_PRIMARY_OWNER


def solo_project_chat_forbidden() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": FEATURE_FORBIDDEN_CODE,
            "feature": FEATURE_CHAT,
            "reason": SOLO_PROJECT_REASON,
            "message": "Chat is not enabled for your account, so chat is closed in projects that only you are in. "
            "Files, rooms and members still work. Ask your administrator if you need it.",
        },
    )


async def require_project_chat(
    db: AsyncSession, user: User, project_id: str | None, request: Request | None = None
) -> None:
    """Refuse the chat of a project that is this person's alone while their Chat is closed."""
    if await project_chat_closed(db, user, project_id, request):
        raise solo_project_chat_forbidden()


async def _chat_sections_and_project(
    db: AsyncSession,
    user: User,
    chat_session_id: str | None,
    project_id: str | None,
    unsaved_is_project: bool,
) -> tuple[set[str], str | None]:
    """The sections a request about a chat needs: Projects for a project chat, Chat for any other.

    A stored chat decides by where it is: in a project it needs Projects (and
    a project id beside it changes nothing); a personal one needs Chat, and
    Projects too when the request also names a project.

    A chat not stored yet counts as the project's only when the person may
    write chats in that project, and - for a turn (``unsaved_is_project``
    false unless the turn is saved) - only when the turn is saved there. A
    project id alone must not carry a personal turn past a closed Chat: an
    unsaved turn with a project id is a personal turn to the chat pipeline.

    The project is the one whose chat this is, when it is a project chat.
    """
    pid = (project_id or "").strip()
    stored, in_project = await _stored_chat_project(db, chat_session_id)
    if stored:
        if in_project:
            return {FEATURE_PROJECTS}, in_project
        return ({FEATURE_CHAT, FEATURE_PROJECTS} if pid else {FEATURE_CHAT}), None
    if pid:
        if unsaved_is_project and await _may_write_in_project(db, user, pid):
            return {FEATURE_PROJECTS}, pid
        return {FEATURE_CHAT, FEATURE_PROJECTS}, None
    return {FEATURE_CHAT}, None


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
    needed, in_project = await _chat_sections_and_project(db, user, chat_session_id, project_id, unsaved_is_project)
    for feature in sorted(needed):
        await _require(request, db, user, feature)
    await require_project_chat(db, user, in_project, request)


async def require_web_chat(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """A route of the personal chat list: its list, search and folders."""
    if _from_extension(request):
        return
    await _require(request, db, user, FEATURE_CHAT)


async def require_web_projects(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Every route under /api/projects."""
    if _from_extension(request):
        return
    await _require(request, db, user, FEATURE_PROJECTS)


async def require_open_project_chat(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """A route under /api/projects/{project_id}/chats, or one that starts a chat there."""
    if _from_extension(request):
        return
    await require_project_chat(db, user, project_id, request)


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
    await require_stored_chat_section(db, user, session_id, request)


async def require_stored_chat_section(
    db: AsyncSession, user: User, chat_session_id: str | None, request: Request | None = None
) -> None:
    """The section of a stored chat, when there is one: for a route that reaches a chat through
    something else (an agent run, a handoff). A chat not stored, or none, is left to the route."""
    stored, in_project = await _stored_chat_project(db, chat_session_id)
    if stored:
        await _require(request, db, user, FEATURE_PROJECTS if in_project else FEATURE_CHAT)
        await require_project_chat(db, user, in_project, request)
