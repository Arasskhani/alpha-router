"""Member-only human rooms: list, create, messages, sync, and brief handoff.

Rooms reuse ``ChatSession`` / ``ChatMessage`` with ``channel_kind=member``.
They never appear on project ``/chats`` routes and must not call models.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import (
    CHANNEL_KIND_MEMBER,
    ChatMessage,
    ChatSession,
    is_member_channel,
)
from app.models.project import Project, ProjectRoomHandoff
from app.services.project_access_service import resolve_project_access
from app.services.project_chat_service import (
    _dt_to_ms,
    _next_project_sequence,
    _project_message_to_client,
    create_project_chat_session,
)


def _room_message_to_client(row: ChatMessage, user: object | None = None) -> dict[str, Any]:
    out = _project_message_to_client(row)
    if row.user_id is not None:
        out["userId"] = row.user_id
    viewer_id = getattr(user, "id", None) if user is not None else None
    out["mine"] = viewer_id is not None and row.user_id == viewer_id
    meta = row.meta if isinstance(row.meta, dict) else {}
    if meta.get("replyToMessageId"):
        out["replyToMessageId"] = meta["replyToMessageId"]
    if meta.get("replyToAuthor"):
        out["replyToAuthor"] = meta["replyToAuthor"]
    if meta.get("replyToContent"):
        out["replyToContent"] = meta["replyToContent"]
    if meta.get("edited"):
        out["edited"] = True
    return out


_MAX_ROOM_SESSIONS_PAGE = 100
_MAX_ROOM_MESSAGES_PAGE = 200
_MAX_SYNC_SESSION_IDS = 200
_MAX_SYNC_SESSION_ROWS = 100
_MAX_HANDOFF_BRIEF = 8000


async def require_room_access(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    write: bool = False,
):
    """Members only. Public viewers are hidden (404). Write needs chat.write."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None or not access.is_member:
        return None
    if write and not access.can("chat.write"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission for this action",
        )
    return access


async def list_project_rooms(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
) -> tuple[list[dict[str, Any]], int] | None:
    if await require_room_access(db, project_id=project_id, user=user) is None:
        return None

    limit = min(max(1, limit), _MAX_ROOM_SESSIONS_PAGE)
    offset = max(0, offset)
    base = select(ChatSession).where(
        ChatSession.project_id == project_id,
        ChatSession.archived_at.is_(None),
        ChatSession.channel_kind == CHANNEL_KIND_MEMBER,
    )
    count_q = (
        select(func.count())
        .select_from(ChatSession)
        .where(
            ChatSession.project_id == project_id,
            ChatSession.archived_at.is_(None),
            ChatSession.channel_kind == CHANNEL_KIND_MEMBER,
        )
    )
    search = (q or "").strip()
    if search:
        base = base.where(ChatSession.title.ilike(f"%{search}%"))
        count_q = count_q.where(ChatSession.title.ilike(f"%{search}%"))

    total = int((await db.execute(count_q)).scalar_one() or 0)
    rows = (await db.execute(base.order_by(ChatSession.updated_at.desc()).limit(limit).offset(offset))).scalars().all()
    return [_room_session_to_client(row) for row in rows], total


async def sync_project_rooms(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    since_ms: int | None = None,
    session_id: str | None = None,
    after_sequence: int | None = None,
) -> dict[str, Any] | None:
    if await require_room_access(db, project_id=project_id, user=user) is None:
        return None
    project = await db.get(Project, project_id)
    if project is None:
        return None

    room_filter = (
        ChatSession.project_id == project_id,
        ChatSession.archived_at.is_(None),
        ChatSession.channel_kind == CHANNEL_KIND_MEMBER,
    )
    total = int((await db.execute(select(func.count()).select_from(ChatSession).where(*room_filter))).scalar_one() or 0)
    order = [ChatSession.updated_at.desc()]
    session_ids = list(
        (await db.execute(select(ChatSession.id).where(*room_filter).order_by(*order).limit(_MAX_SYNC_SESSION_IDS)))
        .scalars()
        .all()
    )

    since_dt: dt.datetime | None = None
    if since_ms is not None and since_ms > 0:
        since_dt = dt.datetime.utcfromtimestamp(since_ms / 1000.0)

    session_stmt = select(ChatSession).where(*room_filter)
    if since_dt is None:
        session_rows = list((await db.execute(session_stmt.order_by(*order).limit(50))).scalars().all())
    else:
        changed = session_stmt.where(ChatSession.updated_at >= since_dt)
        session_rows = list((await db.execute(changed.order_by(*order).limit(_MAX_SYNC_SESSION_ROWS))).scalars().all())
        wanted = (session_id or "").strip()
        if wanted and wanted not in {row.id for row in session_rows}:
            extra = await db.get(ChatSession, wanted)
            if _is_project_room(extra, project_id):
                session_rows = [*session_rows, extra]

    messages: list[dict[str, Any]] = []
    gone_session_id: str | None = None
    wanted = (session_id or "").strip()
    if wanted:
        row = await db.get(ChatSession, wanted)
        if not _is_project_room(row, project_id):
            gone_session_id = wanted
        elif after_sequence is not None:
            msg_stmt = (
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == wanted,
                    ChatMessage.sequence >= int(after_sequence),
                )
                .order_by(ChatMessage.sequence.asc())
                .limit(_MAX_ROOM_MESSAGES_PAGE)
            )
            messages = [_room_message_to_client(m, user) for m in (await db.execute(msg_stmt)).scalars().all()]
        else:
            msg_stmt = (
                select(ChatMessage)
                .where(ChatMessage.session_id == wanted)
                .order_by(ChatMessage.sequence.desc())
                .limit(50)
            )
            msg_rows = list((await db.execute(msg_stmt)).scalars().all())
            msg_rows.reverse()
            messages = [_room_message_to_client(m, user) for m in msg_rows]

    now = dt.datetime.utcnow()
    return {
        "serverTimeMs": _dt_to_ms(now) or 0,
        "aclVersion": int(project.acl_version or 1),
        "total": total,
        "sessionIds": session_ids,
        "sessions": [_room_session_to_client(row) for row in session_rows],
        "messages": messages,
        "messageSessionId": wanted or None,
        "completeWindow": total <= len(session_ids),
        "goneSessionId": gone_session_id,
    }


async def create_project_room(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    title: str = "New room",
    session_id: str | None = None,
) -> dict[str, Any] | None:
    if await require_room_access(db, project_id=project_id, user=user, write=True) is None:
        return None
    user_id = getattr(user, "id", None)
    sid = str(session_id or "").strip() or str(uuid.uuid4())
    existing = await db.get(ChatSession, sid)
    if existing is not None:
        if _is_project_room(existing, project_id):
            return _room_session_to_client(existing)
        raise ValueError("Session id already in use")

    now = dt.datetime.utcnow()
    row = ChatSession(
        id=sid,
        user_id=user_id,
        project_id=project_id,
        created_by_user_id=user_id,
        channel_kind=CHANNEL_KIND_MEMBER,
        title=(title or "New room")[:512],
        model_id="",
        tools={},
        private_mode=False,
        message_count=0,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raced = await db.get(ChatSession, sid)
        if not _is_project_room(raced, project_id):
            raise
        return _room_session_to_client(raced)
    return _room_session_to_client(row)


async def get_project_room(
    db: AsyncSession,
    *,
    project_id: str,
    room_id: str,
    user: object,
) -> dict[str, Any] | None:
    if await require_room_access(db, project_id=project_id, user=user) is None:
        return None
    row = await db.get(ChatSession, room_id)
    if not _is_project_room(row, project_id):
        return None
    return _room_session_to_client(row)


async def list_project_room_messages(
    db: AsyncSession,
    *,
    project_id: str,
    room_id: str,
    user: object,
    limit: int = 100,
    before: int | None = None,
) -> tuple[list[dict[str, Any]], bool] | None:
    if await require_room_access(db, project_id=project_id, user=user) is None:
        return None
    row = await db.get(ChatSession, room_id)
    if not _is_project_room(row, project_id):
        return None

    limit = min(max(1, limit), _MAX_ROOM_MESSAGES_PAGE)
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == room_id)
        .order_by(ChatMessage.sequence.desc())
        .limit(limit + 1)
    )
    if before is not None:
        stmt = stmt.where(ChatMessage.sequence < int(before))
    rows = (await db.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = list(rows[:limit])
    rows.reverse()
    return [_room_message_to_client(r, user) for r in rows], has_more


async def append_project_room_message(
    db: AsyncSession,
    *,
    project_id: str,
    room_id: str,
    user: object,
    content: str,
    client_message_id: str | None = None,
    reply_to_message_id: str | None = None,
) -> dict[str, Any] | None:
    if await require_room_access(db, project_id=project_id, user=user, write=True) is None:
        return None
    user_id = getattr(user, "id", None)
    display_name = getattr(user, "display_name", None) or getattr(user, "username", None)

    row = await db.get(ChatSession, room_id)
    if not _is_project_room(row, project_id):
        return None

    meta = await _reply_meta(db, room_id=room_id, reply_to_message_id=reply_to_message_id)

    if client_message_id:
        existing = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id == room_id,
                    ChatMessage.client_message_id == str(client_message_id),
                )
            )
        ).scalar_one_or_none()
        if existing:
            return _room_message_to_client(existing, user)

    last_error: Exception | None = None
    for _attempt in range(12):
        try:
            row = await db.get(ChatSession, room_id)
            if not _is_project_room(row, project_id):
                return None
            if client_message_id:
                existing = (
                    await db.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == room_id,
                            ChatMessage.client_message_id == str(client_message_id),
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    return _room_message_to_client(existing, user)

            seq = await _next_project_sequence(db, room_id)
            msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=room_id,
                user_id=user_id,
                author_display_name=display_name,
                role="user",
                content=content,
                sequence=seq,
                client_message_id=str(client_message_id) if client_message_id else None,
                meta=meta,
                created_at=dt.datetime.utcnow(),
            )
            db.add(msg)
            row.message_count = int(row.message_count or 0) + 1
            row.last_message_at = dt.datetime.utcnow()
            row.revision = int(row.revision or 1) + 1
            row.updated_at = dt.datetime.utcnow()
            await db.flush()
            return _room_message_to_client(msg, user)
        except (IntegrityError, OperationalError) as exc:
            last_error = exc
            await db.rollback()
            continue
    if last_error is not None:
        raise last_error
    return None


async def update_project_room_message(
    db: AsyncSession,
    *,
    project_id: str,
    room_id: str,
    message_id: str,
    user: object,
    content: str,
) -> dict[str, Any] | None:
    if await require_room_access(db, project_id=project_id, user=user, write=True) is None:
        return None
    room = await db.get(ChatSession, room_id)
    if not _is_project_room(room, project_id):
        return None
    msg = await db.get(ChatMessage, message_id)
    if msg is None or msg.session_id != room_id:
        return None
    if msg.user_id != getattr(user, "id", None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only edit your own messages",
        )
    text = (content or "").strip()
    if not text:
        raise ValueError("Message is required")
    msg.content = text
    meta = dict(msg.meta) if isinstance(msg.meta, dict) else {}
    meta["edited"] = True
    msg.meta = meta
    room.revision = int(room.revision or 1) + 1
    room.updated_at = dt.datetime.utcnow()
    await db.flush()
    return _room_message_to_client(msg, user)


async def delete_project_room_message(
    db: AsyncSession,
    *,
    project_id: str,
    room_id: str,
    message_id: str,
    user: object,
) -> bool | None:
    if await require_room_access(db, project_id=project_id, user=user, write=True) is None:
        return None
    room = await db.get(ChatSession, room_id)
    if not _is_project_room(room, project_id):
        return None
    msg = await db.get(ChatMessage, message_id)
    if msg is None or msg.session_id != room_id:
        return None
    if msg.user_id != getattr(user, "id", None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own messages",
        )
    await db.delete(msg)
    room.message_count = max(0, int(room.message_count or 0) - 1)
    room.revision = int(room.revision or 1) + 1
    room.updated_at = dt.datetime.utcnow()
    await db.flush()
    return True


async def delete_project_room(
    db: AsyncSession,
    *,
    project_id: str,
    room_id: str,
    user: object,
) -> bool | None:
    if await require_room_access(db, project_id=project_id, user=user, write=True) is None:
        return None
    row = await db.get(ChatSession, room_id)
    if not _is_project_room(row, project_id):
        return None
    await db.delete(row)
    await db.flush()
    return True


async def create_room_handoff(
    db: AsyncSession,
    *,
    project_id: str,
    room_id: str,
    user: object,
    brief: str,
    title: str | None = None,
) -> dict[str, Any] | None:
    if await require_room_access(db, project_id=project_id, user=user, write=True) is None:
        return None
    source = await db.get(ChatSession, room_id)
    if not _is_project_room(source, project_id):
        return None

    text = (brief or "").strip()
    if not text:
        raise ValueError("Brief is required")
    if len(text) > _MAX_HANDOFF_BRIEF:
        raise ValueError(f"Brief must be at most {_MAX_HANDOFF_BRIEF} characters")

    chat_title = (title or "").strip() or (source.title or "New chat")
    session = await create_project_chat_session(
        db,
        project_id=project_id,
        user=user,
        title=chat_title,
    )
    if session is None:
        return None
    target_id = str(session["id"])
    handoff = ProjectRoomHandoff(
        id=str(uuid.uuid4()),
        source_session_id=room_id,
        target_session_id=target_id,
        brief=text,
        created_by_user_id=getattr(user, "id", None),
        created_at=dt.datetime.utcnow(),
    )
    db.add(handoff)
    await db.flush()
    return {
        "targetSessionId": target_id,
        "brief": text,
        "sourceRoomId": room_id,
    }


async def _reply_meta(
    db: AsyncSession,
    *,
    room_id: str,
    reply_to_message_id: str | None,
) -> dict[str, Any]:
    parent_id = (reply_to_message_id or "").strip()
    if not parent_id:
        return {}
    parent = await db.get(ChatMessage, parent_id)
    if parent is None or parent.session_id != room_id:
        return {}
    snippet = (parent.content or "").strip()
    if len(snippet) > 240:
        snippet = snippet[:239] + "…"
    return {
        "replyToMessageId": parent.id,
        "replyToAuthor": parent.author_display_name,
        "replyToContent": snippet,
    }


def _is_project_room(row: ChatSession | None, project_id: str) -> bool:
    return row is not None and row.project_id == project_id and is_member_channel(row)


def _room_session_to_client(row: ChatSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title or "New room",
        "messageCount": row.message_count or 0,
        "revision": int(row.revision or 1),
        "channelKind": CHANNEL_KIND_MEMBER,
        "createdByUserId": row.created_by_user_id,
        "createdAt": _dt_to_ms(row.created_at),
        "updatedAt": _dt_to_ms(row.updated_at),
        "lastMessageAt": _dt_to_ms(row.last_message_at),
    }
