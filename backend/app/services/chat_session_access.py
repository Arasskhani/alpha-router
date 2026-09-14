"""Who may act on a chat session named by the client.

``chat_session_id`` arrives in several multipart forms (attachments, voice
notes, attach-from-media) and used to be looked up as-is: the caller could
name any session, have uploads scoped to that session's project and leave
voice notes and media rows pointing at a conversation that is not theirs.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession


async def resolve_owned_chat_session(
    db: AsyncSession,
    *,
    user: object,
    chat_session_id: str | None,
) -> ChatSession | None:
    """Return the session when ``user`` may write into it; None when no id given.

    Allowed: the session's own user, or a member of the session's project who
    holds ``chat.write`` there (shared project conversations). Anything else
    is a 404 so the existence of other people's sessions is not confirmed.
    """
    sid = (chat_session_id or "").strip()
    if not sid:
        return None
    user_id = getattr(user, "id", None)
    session = await db.get(ChatSession, sid)
    if session is None or user_id is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if int(session.user_id) == int(user_id):
        return session
    if session.project_id:
        from app.services.project_access_service import resolve_project_access

        access = await resolve_project_access(db, project_id=session.project_id, user=user)
        if access is not None and access.can("chat.write"):
            return session
    raise HTTPException(status_code=404, detail="Chat session not found")
