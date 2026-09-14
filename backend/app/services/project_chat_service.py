"""Project-scoped shared chat storage: list, create, append, pin/unpin.

All operations re-use the existing ``ChatSession``/``ChatMessage`` tables
but scope by ``project_id`` instead of ``user_id``.  Authorization is
delegated to ``project_access_service`` so client-supplied project IDs
and roles are never trusted.
"""

from __future__ import annotations

import calendar
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import (
    CHANNEL_KIND_AI,
    ChatMessage,
    ChatSession,
    ai_channel_filter,
    is_member_channel,
)
from app.models.project import Project, ProjectChatPin, ProjectUserPref
from app.services.project_access_service import (
    require_capability,
    resolve_project_access,
)

_MAX_PROJECT_SESSIONS_PAGE = 100
_MAX_PROJECT_MESSAGES_PAGE = 200
_MAX_SYNC_SESSION_IDS = 200
_MAX_SYNC_SESSION_ROWS = 100


async def list_project_chat_sessions(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    limit: int = 50,
    offset: int = 0,
    q: str | None = None,
) -> tuple[list[dict[str, Any]], int] | None:
    """List chat sessions in a project. Returns None if project is hidden."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None

    limit = min(max(1, limit), _MAX_PROJECT_SESSIONS_PAGE)
    offset = max(0, offset)

    base = select(ChatSession).where(
        ChatSession.project_id == project_id,
        ChatSession.archived_at.is_(None),
        ai_channel_filter(),
    )
    count_q = (
        select(func.count())
        .select_from(ChatSession)
        .where(
            ChatSession.project_id == project_id,
            ChatSession.archived_at.is_(None),
            ai_channel_filter(),
        )
    )

    search = (q or "").strip()
    if search:
        base = base.where(ChatSession.title.ilike(f"%{search}%"))
        count_q = count_q.where(ChatSession.title.ilike(f"%{search}%"))

    total = int((await db.execute(count_q)).scalar_one() or 0)
    pinned_ids = set(await _ai_pinned_session_ids(db, project_id))
    order = [ChatSession.updated_at.desc()]
    if pinned_ids:
        order.insert(
            0,
            case((ChatSession.id.in_(list(pinned_ids)), 0), else_=1),
        )
    rows = (
        (await db.execute(base.order_by(*order).limit(limit).offset(offset)))
        .scalars()
        .all()
    )

    sessions = [_project_session_to_client(r, pinned=r.id in pinned_ids) for r in rows]
    return sessions, total


async def get_last_opened_session_id(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
) -> str | None:
    user_id = getattr(user, "id", None)
    if user_id is None:
        return None
    pref = await db.get(ProjectUserPref, (project_id, int(user_id)))
    if pref is None or not pref.last_opened_session_id:
        return None
    row = await db.get(ChatSession, pref.last_opened_session_id)
    if row is None or row.project_id != project_id or is_member_channel(row):
        return None
    return pref.last_opened_session_id


async def touch_project_visit(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Record that the user opened this project, optionally a specific chat."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None
    user_id = getattr(user, "id", None)
    if user_id is None:
        return None
    now = dt.datetime.utcnow()
    pref = await db.get(ProjectUserPref, (project_id, int(user_id)))
    if pref is None:
        pref = ProjectUserPref(
            project_id=project_id,
            user_id=int(user_id),
            last_opened_at=now,
        )
        db.add(pref)
    else:
        pref.last_opened_at = now
    if session_id:
        row = await db.get(ChatSession, session_id)
        if row is None or row.project_id != project_id or is_member_channel(row):
            raise ValueError("Chat not found in this project")
        pref.last_opened_session_id = session_id
    await db.flush()
    return {
        "lastOpenedSessionId": pref.last_opened_session_id,
        "lastOpenedAt": _dt_to_ms(pref.last_opened_at),
    }


async def sync_project_chats(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    since_ms: int | None = None,
    session_id: str | None = None,
    after_sequence: int | None = None,
) -> dict[str, Any] | None:
    """Incremental snapshot for live project chat: pins, session list, new messages."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None
    project = await db.get(Project, project_id)
    if project is None:
        return None

    pinned_ids = await _ai_pinned_session_ids(db, project_id)
    pinned_set = set(pinned_ids)

    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ChatSession)
                .where(
                    ChatSession.project_id == project_id,
                    ChatSession.archived_at.is_(None),
                    ai_channel_filter(),
                )
            )
        ).scalar_one()
        or 0
    )

    order = [ChatSession.updated_at.desc()]
    if pinned_set:
        order.insert(
            0,
            case((ChatSession.id.in_(list(pinned_set)), 0), else_=1),
        )
    id_rows = (
        (
            await db.execute(
                select(ChatSession.id)
                .where(
                    ChatSession.project_id == project_id,
                    ChatSession.archived_at.is_(None),
                    ai_channel_filter(),
                )
                .order_by(*order)
                .limit(_MAX_SYNC_SESSION_IDS)
            )
        )
        .scalars()
        .all()
    )
    session_ids = list(id_rows)

    since_dt: dt.datetime | None = None
    if since_ms is not None and since_ms > 0:
        since_dt = dt.datetime.utcfromtimestamp(since_ms / 1000.0)

    session_stmt = select(ChatSession).where(
        ChatSession.project_id == project_id,
        ChatSession.archived_at.is_(None),
        ai_channel_filter(),
    )
    if since_dt is None:
        session_rows = (
            (
                await db.execute(
                    session_stmt.order_by(*order).limit(50)
                )
            )
            .scalars()
            .all()
        )
    else:
        changed = session_stmt.where(ChatSession.updated_at >= since_dt)
        session_rows = (
            (await db.execute(changed.order_by(*order).limit(_MAX_SYNC_SESSION_ROWS)))
            .scalars()
            .all()
        )
        # Always include the open thread so deep-linked / last-opened chats stay current.
        wanted = (session_id or "").strip()
        if wanted and wanted not in {r.id for r in session_rows}:
            extra = await db.get(ChatSession, wanted)
            if (
                extra is not None
                and extra.project_id == project_id
                and not is_member_channel(extra)
            ):
                session_rows = [*session_rows, extra]

    sessions = [
        _project_session_to_client(row, pinned=row.id in pinned_set)
        for row in session_rows
    ]

    messages: list[dict[str, Any]] = []
    gone_session_id: str | None = None
    wanted = (session_id or "").strip()
    if wanted:
        row = await db.get(ChatSession, wanted)
        if row is None or row.project_id != project_id or is_member_channel(row):
            gone_session_id = wanted
        else:
            if after_sequence is not None:
                # Inclusive of after_sequence so patched-in-place assistant
                # content (same sequence, updated body) is visible to other members.
                msg_stmt = (
                    select(ChatMessage)
                    .where(
                        ChatMessage.session_id == wanted,
                        ChatMessage.sequence >= int(after_sequence),
                    )
                    .order_by(ChatMessage.sequence.asc())
                    .limit(_MAX_PROJECT_MESSAGES_PAGE)
                )
                msg_rows = (await db.execute(msg_stmt)).scalars().all()
                messages = [_project_message_to_client(m) for m in msg_rows]
            else:
                msg_stmt = (
                    select(ChatMessage)
                    .where(ChatMessage.session_id == wanted)
                    .order_by(ChatMessage.sequence.desc())
                    .limit(50)
                )
                msg_rows = list((await db.execute(msg_stmt)).scalars().all())
                msg_rows.reverse()
                messages = [_project_message_to_client(m) for m in msg_rows]

    if messages:
        from app.services.project_media_service import rewrite_personal_media_urls_in_messages

        messages = await rewrite_personal_media_urls_in_messages(
            db, project_id=project_id, messages=messages
        )

    last_opened = await get_last_opened_session_id(
        db, project_id=project_id, user=user
    )
    now = dt.datetime.utcnow()
    return {
        "serverTimeMs": _dt_to_ms(now) or 0,
        "aclVersion": int(project.acl_version or 1),
        "total": total,
        "pinnedSessionIds": pinned_ids,
        "sessionIds": session_ids,
        "sessions": sessions,
        "messages": messages,
        "messageSessionId": wanted or None,
        "completeWindow": total <= len(session_ids),
        "goneSessionId": gone_session_id,
        "lastOpenedSessionId": last_opened,
    }


async def create_project_chat_session(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    title: str = "New chat",
    model_id: str = "",
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Create a new chat thread in a project. Requires chat.write capability."""
    await require_capability(
        db, project_id=project_id, user=user, capability="chat.write"
    )
    user_id = getattr(user, "id", None)
    sid = str(session_id or "").strip() or str(uuid.uuid4())
    existing = await db.get(ChatSession, sid)
    if existing is not None:
        if existing.project_id == project_id and not is_member_channel(existing):
            pinned = (
                await db.execute(
                    select(ProjectChatPin).where(
                        ProjectChatPin.project_id == project_id,
                        ProjectChatPin.session_id == sid,
                    )
                )
            ).scalar_one_or_none()
            return _project_session_to_client(existing, pinned=pinned is not None)
        raise ValueError("Session id already in use")

    now = dt.datetime.utcnow()
    row = ChatSession(
        id=sid,
        user_id=user_id,
        project_id=project_id,
        created_by_user_id=user_id,
        channel_kind=CHANNEL_KIND_AI,
        title=title[:512] if title else "New chat",
        model_id=model_id[:512] if model_id else "",
        tools={},
        private_mode=False,  # Private mode is forbidden in projects.
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
        if raced is None or raced.project_id != project_id or is_member_channel(raced):
            raise
        return _project_session_to_client(raced, pinned=False)
    return _project_session_to_client(row, pinned=False)


async def get_project_chat_session(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    user: object,
) -> dict[str, Any] | None:
    """Get a single project chat session. Returns None if hidden."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None
    row = await db.get(ChatSession, session_id)
    if row is None or row.project_id != project_id or is_member_channel(row):
        return None
    pinned = (
        await db.execute(
            select(ProjectChatPin).where(
                ProjectChatPin.project_id == project_id,
                ProjectChatPin.session_id == session_id,
            )
        )
    ).scalar_one_or_none()
    return _project_session_to_client(row, pinned=pinned is not None)


async def list_project_chat_messages(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    user: object,
    limit: int = 100,
    before: int | None = None,
) -> tuple[list[dict[str, Any]], bool] | None:
    """List messages in a project chat session. Returns None if hidden."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None
    row = await db.get(ChatSession, session_id)
    if row is None or row.project_id != project_id or is_member_channel(row):
        return None

    limit = min(max(1, limit), _MAX_PROJECT_MESSAGES_PAGE)
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.sequence.desc())
        .limit(limit + 1)
    )
    if before is not None:
        stmt = stmt.where(ChatMessage.sequence < int(before))
    rows = (await db.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    rows = list(rows[:limit])
    rows.reverse()
    messages = [_project_message_to_client(r) for r in rows]
    from app.services.project_media_service import rewrite_personal_media_urls_in_messages

    messages = await rewrite_personal_media_urls_in_messages(
        db, project_id=project_id, messages=messages
    )
    return messages, has_more


async def append_project_chat_message(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    user: object,
    role: str,
    content: str,
    client_message_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append a single message to a project chat session.

    Requires ``chat.write`` capability.  Uses an atomic sequence
    allocation via ``_next_project_sequence`` to avoid race conditions
    between concurrent writers.
    """
    access = await require_capability(
        db, project_id=project_id, user=user, capability="chat.write"
    )
    user_id = getattr(user, "id", None)
    display_name = getattr(user, "display_name", None) or getattr(user, "username", None)

    row = await db.get(ChatSession, session_id)
    if row is None or row.project_id != project_id or is_member_channel(row):
        return None

    # Private mode is forbidden in project chats.
    if row.private_mode:
        return None

    # Idempotency: check for existing message with the same client_message_id.
    if client_message_id:
        existing = (
            await db.execute(
                select(ChatMessage).where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.client_message_id == str(client_message_id),
                )
            )
        ).scalar_one_or_none()
        if existing:
            return _project_message_to_client(existing)

    from sqlalchemy.exc import IntegrityError, OperationalError

    # Retry the sequence allocation + insert when a concurrent writer
    # allocated the same sequence (last-resort guard via the unique
    # constraint ux_chat_messages_session_sequence) or when SQLite
    # reports the database is locked.  This makes the append robust
    # under concurrent writes on both SQLite and PostgreSQL.
    last_error: Exception | None = None
    for attempt in range(12):
        try:
            # Re-fetch the session row each iteration (it may have been
            # expired/refreshed after a rollback).
            row = await db.get(ChatSession, session_id)
            if (
                row is None
                or row.project_id != project_id
                or row.private_mode
                or is_member_channel(row)
            ):
                return None

            # Re-check idempotency (a concurrent writer may have inserted
            # the same client_message_id while we were retrying).
            if client_message_id:
                existing = (
                    await db.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == session_id,
                            ChatMessage.client_message_id == str(client_message_id),
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    return _project_message_to_client(existing)

            seq = await _next_project_sequence(db, session_id)
            msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                user_id=user_id,
                author_display_name=display_name,
                role=role[:16],
                content=content,
                sequence=seq,
                client_message_id=str(client_message_id) if client_message_id else None,
                meta=meta or {},
                created_at=dt.datetime.utcnow(),
            )
            db.add(msg)
            # SQL-side increments: two concurrent appends each read the same
            # stale Python value, so ``count + 1`` in Python loses one update
            # (unique sequences, wrong message_count). Let the database add.
            row.message_count = func.coalesce(ChatSession.message_count, 0) + 1
            row.last_message_at = dt.datetime.utcnow()
            row.revision = func.coalesce(ChatSession.revision, 1) + 1
            row.updated_at = dt.datetime.utcnow()
            await db.flush()
            await db.refresh(row, attribute_names=["message_count", "revision"])
            if msg.role == "assistant":
                # Only a completed exchange is worth mining, and the check stays
                # ahead of the import so member turns pay nothing on this path.
                from app.services.project_memory_job_service import (
                    maybe_schedule_from_append,
                )

                await maybe_schedule_from_append(
                    db,
                    session=row,
                    messages=[{"role": msg.role}],
                    watermark_sequence=seq,
                )
            return _project_message_to_client(msg)
        except (IntegrityError, OperationalError) as exc:
            last_error = exc
            await db.rollback()
            continue
    return None


async def delete_project_chat_session(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    user: object,
) -> bool | None:
    """Delete a project chat session. Requires chat.write. Returns None if hidden."""
    access = await require_capability(
        db, project_id=project_id, user=user, capability="chat.write"
    )
    row = await db.get(ChatSession, session_id)
    if row is None or row.project_id != project_id or is_member_channel(row):
        return None
    await db.delete(row)
    await db.flush()
    return True


async def pin_project_chat(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    user: object,
) -> dict[str, Any] | None:
    """Pin a chat thread for all project members. Requires chat.pin capability."""
    access = await require_capability(
        db, project_id=project_id, user=user, capability="chat.pin"
    )
    user_id = getattr(user, "id", None)
    # Verify the session belongs to this project.
    row = await db.get(ChatSession, session_id)
    if row is None or row.project_id != project_id or is_member_channel(row):
        return None
    # Idempotent: if already pinned, return existing.
    existing = (
        await db.execute(
            select(ProjectChatPin).where(
                ProjectChatPin.project_id == project_id,
                ProjectChatPin.session_id == session_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"sessionId": session_id, "pinned": True, "pinnedAt": existing.pinned_at.isoformat() if existing.pinned_at else None}
    pin = ProjectChatPin(
        id=str(uuid.uuid4()),
        project_id=project_id,
        session_id=session_id,
        pinned_by_user_id=user_id,
        pinned_at=dt.datetime.utcnow(),
    )
    db.add(pin)
    await db.flush()
    return {"sessionId": session_id, "pinned": True, "pinnedAt": pin.pinned_at.isoformat()}


async def unpin_project_chat(
    db: AsyncSession,
    *,
    project_id: str,
    session_id: str,
    user: object,
) -> dict[str, Any] | None:
    """Unpin a chat thread. Requires chat.pin capability."""
    access = await require_capability(
        db, project_id=project_id, user=user, capability="chat.pin"
    )
    row = await db.get(ChatSession, session_id)
    if row is None or row.project_id != project_id or is_member_channel(row):
        return None
    existing = (
        await db.execute(
            select(ProjectChatPin).where(
                ProjectChatPin.project_id == project_id,
                ProjectChatPin.session_id == session_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()
    return {"sessionId": session_id, "pinned": False}


async def list_pinned_chats(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
) -> list[str] | None:
    """List pinned session IDs for a project. Returns None if hidden."""
    access = await resolve_project_access(db, project_id=project_id, user=user)
    if access is None:
        return None
    return await _ai_pinned_session_ids(db, project_id)


# --- helpers ---


async def _ai_pinned_session_ids(db: AsyncSession, project_id: str) -> list[str]:
    return list(
        (
            await db.execute(
                select(ProjectChatPin.session_id)
                .join(ChatSession, ChatSession.id == ProjectChatPin.session_id)
                .where(
                    ProjectChatPin.project_id == project_id,
                    ai_channel_filter(),
                )
            )
        )
        .scalars()
        .all()
    )


async def _next_project_sequence(db: AsyncSession, session_id: str) -> int:
    """Allocate the next sequence number atomically.

    Uses ``MAX(sequence) + 1`` within the current transaction; the
    unique constraint ``ux_chat_messages_session_sequence`` provides a
    last-resort guard against concurrent inserts.
    """
    current = (
        await db.execute(
            select(func.max(ChatMessage.sequence)).where(
                ChatMessage.session_id == session_id
            )
        )
    ).scalar_one()
    return int(current or 0) + 1


def _dt_to_ms(value: dt.datetime | None) -> int | None:
    if value is None:
        return None
    return int(calendar.timegm(value.timetuple()) * 1000)


def _project_session_to_client(
    row: ChatSession,
    *,
    pinned: bool = False,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title or "New chat",
        "model": row.model_id or "",
        "messageCount": row.message_count or 0,
        "revision": int(row.revision or 1),
        "pinned": pinned,
        "createdByUserId": row.created_by_user_id,
        "createdAt": _dt_to_ms(row.created_at),
        "updatedAt": _dt_to_ms(row.updated_at),
        "lastMessageAt": _dt_to_ms(row.last_message_at),
    }


def _project_message_to_client(row: ChatMessage) -> dict[str, Any]:
    """Serialize a shared project message for live sync and project APIs.

    Include streaming/receivedAt (and model labels) so other members can tell a
    finished assistant row from an in-flight placeholder. Omitting those fields
    makes the frontend treat every synced reply as still generating.
    """
    meta = row.meta if isinstance(row.meta, dict) else {}
    out: dict[str, Any] = {
        "id": row.id,
        "role": row.role,
        "content": row.content or "",
        "sequence": row.sequence,
        "authorDisplayName": row.author_display_name,
    }
    if row.client_message_id:
        out["clientMessageId"] = row.client_message_id
    if meta.get("modelId"):
        out["modelId"] = meta["modelId"]
    if meta.get("modelName"):
        out["modelName"] = meta["modelName"]
    if meta.get("sentAt") is not None:
        out["sentAt"] = meta["sentAt"]
    if meta.get("receivedAt") is not None:
        out["receivedAt"] = meta["receivedAt"]
    if meta.get("streaming") is not None:
        out["streaming"] = meta["streaming"]
    for key in (
        "agentId",
        "agentVersionId",
        "agentName",
        "agentStatus",
        "routingOutcome",
        "completionReasonCode",
        "citations",
    ):
        if meta.get(key) is not None:
            out[key] = meta[key]
    if row.agent_run_id:
        out["agentRunId"] = row.agent_run_id
    elif meta.get("agentRunId"):
        out["agentRunId"] = meta["agentRunId"]
    return out
