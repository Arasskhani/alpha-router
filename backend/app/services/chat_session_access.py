"""Who may act on a chat session named by the client.

``chat_session_id`` arrives in several multipart forms (attachments, voice
notes, attach-from-media) and used to be looked up as-is: the caller could
name any *existing* session, have uploads scoped to that session's project
and leave voice notes and media rows pointing at a conversation that is not
theirs.

Two kinds of id must keep working and are deliberately not refused:

* ids the server has never seen. The frontend creates sessions client-side
  and syncs them later (fire-and-forget), and Private Mode sessions are never
  synced at all. There is nothing to leak from an unknown id; it is stored
  opaquely exactly as before.
* the caller's own personal sessions, and project sessions they can write in.

A project session is always answered by the project's access, whoever
started it: a member who started a chat and was then removed from the
project must not go on reading it - nor, through a turn in it, the project's
other chats (recall), its older messages (history completion) or its summary.

Any other session that exists is refused (404, so the existence of other
people's sessions is not confirmed).
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
    """Return the session when it exists and ``user`` may write into it.

    ``None`` when no id was given *or* the id is unknown to the server (see
    module docstring). Raises 404 for an existing session the caller may not
    use.
    """
    sid = (chat_session_id or "").strip()
    if not sid:
        return None
    user_id = getattr(user, "id", None)
    session = await db.get(ChatSession, sid)
    if session is None:
        return None
    if user_id is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    if session.project_id:
        from app.services.project_access_service import resolve_project_access

        access = await resolve_project_access(db, project_id=session.project_id, user=user)
        if access is not None and access.can("chat.write"):
            return session
    elif int(session.user_id) == int(user_id):
        return session
    raise HTTPException(status_code=404, detail="Chat session not found")
