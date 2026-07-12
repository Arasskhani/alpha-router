"""User chat history API — normalized PostgreSQL tables."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_active_user
from app.config import get_settings
from app.database import get_db, get_read_db
from app.models.user import User
from app.services.rate_limit import check_rate_limit
from app.services.user_chat_storage_service import (
    RevisionConflictError,
    append_session_messages,
    create_chat_folder,
    create_chat_session,
    delete_chat_folder,
    delete_chat_session,
    list_chat_folders,
    list_chat_sessions,
    list_session_messages,
    load_user_prefs,
    replace_session_messages,
    save_user_prefs,
    search_chat_messages,
    get_chat_session,
    cancel_streaming_reply,
    update_chat_folder,
    update_chat_session,
    update_last_session_message,
)

router = APIRouter(prefix="/api/user/chats", tags=["user-chats"])


class UserPrefsPatchIn(BaseModel):
    default_model: str | None = None
    theme: Literal["light", "dark"] | None = None


class ChatSessionCreateIn(BaseModel):
    id: str | None = None
    title: str = "New chat"
    folderId: str | None = None
    model: str = ""
    tools: dict[str, Any] = Field(default_factory=dict)
    titleLocked: bool = False
    titleGenerated: bool = False
    toolsTouched: bool = False
    privateMode: bool = False
    createdAt: int | None = None
    updatedAt: int | None = None


class ChatSessionPatchIn(BaseModel):
    title: str | None = None
    folderId: str | None = None
    model: str | None = None
    tools: dict[str, Any] | None = None
    titleLocked: bool | None = None
    titleGenerated: bool | None = None
    toolsTouched: bool | None = None
    privateMode: bool | None = None
    updatedAt: int | None = None
    expectedRevision: int | None = None


class ChatFolderCreateIn(BaseModel):
    id: str | None = None
    name: str
    color: str | None = None
    createdAt: int | None = None
    updatedAt: int | None = None


class ChatFolderPatchIn(BaseModel):
    name: str | None = None
    color: str | None = None
    sort_order: int | None = None


class ChatMessageIn(BaseModel):
    id: str | None = None
    role: Literal["user", "assistant"]
    content: str = ""
    modelId: str | None = None
    modelName: str | None = None
    sentAt: int | None = None
    receivedAt: int | None = None
    clientMessageId: str | None = None


class ChatMessagesPostIn(BaseModel):
    messages: list[ChatMessageIn] = Field(default_factory=list)
    expectedRevision: int | None = None


class ChatMessagesPutIn(BaseModel):
    messages: list[ChatMessageIn] = Field(default_factory=list)
    expectedRevision: int | None = None


class LastMessagePatchIn(BaseModel):
    content: str = ""
    modelId: str | None = None
    modelName: str | None = None
    receivedAt: int | None = None
    expectedRevision: int | None = None


def _revision_conflict(exc: RevisionConflictError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": "Session revision conflict", "revision": exc.current_revision},
    )


@router.get("")
async def list_user_chats(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, description="Search session titles (min 2 chars)"),
    since: int | None = Query(None, description="Return sessions updated after this Unix ms timestamp"),
    min_activity_ms: int | None = Query(
        None, description="Sessions with last activity at or after this Unix ms timestamp",
    ),
    max_activity_ms: int | None = Query(
        None, description="Sessions with last activity before this Unix ms timestamp",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db),
):
    settings = get_settings()
    if q and q.strip():
        await check_rate_limit(f"chat-search:{user.id}", limit=settings.chat_search_rate_limit_per_min)
    elif since is not None:
        await check_rate_limit(
            f"chat-list-since:{user.id}",
            limit=settings.chat_list_since_rate_limit_per_min,
        )
    else:
        await check_rate_limit(f"chat-list:{user.id}", limit=settings.chat_list_rate_limit_per_min)

    sessions, total, older_total = await list_chat_sessions(
        db,
        user.id,
        limit=limit,
        offset=offset,
        q=q,
        since_ms=since,
        min_activity_ms=min_activity_ms,
        max_activity_ms=max_activity_ms,
    )
    folders = await list_chat_folders(db, user.id)
    prefs = await load_user_prefs(db, user.id)
    out: dict[str, object] = {
        "sessions": sessions,
        "folders": folders,
        "prefs": prefs,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
    if older_total is not None:
        out["older_total"] = older_total
    return out


@router.get("/search-messages")
async def search_user_chat_messages(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db),
):
    await check_rate_limit(
        f"chat-msg-search:{user.id}",
        limit=get_settings().chat_message_search_rate_limit_per_min,
    )
    return {"results": await search_chat_messages(db, user.id, q=q, limit=limit)}


@router.get("/folders")
async def get_chat_folders(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_read_db)):
    return {"folders": await list_chat_folders(db, user.id)}


@router.post("/folders")
async def post_chat_folder(
    body: ChatFolderCreateIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await create_chat_folder(db, user.id, body.model_dump())
    await db.commit()
    return folder


@router.patch("/folders/{folder_id}")
async def patch_chat_folder(
    folder_id: str,
    body: ChatFolderPatchIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    folder = await update_chat_folder(db, user.id, folder_id, updates)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    await db.commit()
    return folder


@router.delete("/folders/{folder_id}")
async def remove_chat_folder(
    folder_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_chat_folder(db, user.id, folder_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Folder not found")
    await db.commit()
    return {"ok": True}


@router.post("/sessions")
async def post_chat_session(
    body: ChatSessionCreateIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await create_chat_session(db, user.id, body.model_dump())
        await db.commit()
        return session
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.patch("/sessions/{session_id}")
async def patch_chat_session(
    session_id: str,
    body: ChatSessionPatchIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    payload = body.model_dump(exclude_unset=True)
    expected = payload.pop("expectedRevision", None)
    try:
        session = await update_chat_session(
            db,
            user.id,
            session_id,
            payload,
            expected_revision=expected,
        )
    except RevisionConflictError as exc:
        await db.rollback()
        raise _revision_conflict(exc) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()
    return session


@router.delete("/sessions/{session_id}")
async def remove_chat_session(
    session_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_chat_session(db, user.id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()
    return {"ok": True}


messages_router = APIRouter(prefix="/api/user/chat-sessions", tags=["user-chats"])


@messages_router.get("/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    before: int | None = Query(None, description="Return messages with sequence less than this value"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    messages, has_more = await list_session_messages(
        db, user.id, session_id, limit=limit, before=before
    )
    await db.commit()
    session = await get_chat_session(db, user.id, session_id)
    if not messages and before is None:
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
    revision = int(session["revision"]) if session else None
    return {"messages": messages, "has_more": has_more, "revision": revision}


@messages_router.post("/{session_id}/messages")
async def post_session_messages(
    session_id: str,
    body: ChatMessagesPostIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        messages = await append_session_messages(
            db,
            user.id,
            session_id,
            [m.model_dump() for m in body.messages],
            expected_revision=body.expectedRevision,
        )
    except RevisionConflictError as exc:
        await db.rollback()
        raise _revision_conflict(exc) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session = await get_chat_session(db, user.id, session_id)
    await db.commit()
    return {"messages": messages, "session": session}


@messages_router.put("/{session_id}/messages")
async def put_session_messages(
    session_id: str,
    body: ChatMessagesPutIn,
    response: Response,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin/repair only — clients should use POST append for normal sync."""
    response.headers["Deprecation"] = "true"
    response.headers["X-Alpha Router-Router-Replace-Messages"] = "admin-repair-only"
    try:
        messages = await replace_session_messages(
            db,
            user.id,
            session_id,
            [m.model_dump() for m in body.messages],
            expected_revision=body.expectedRevision,
        )
    except RevisionConflictError as exc:
        await db.rollback()
        raise _revision_conflict(exc) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()
    return {"messages": messages}


@messages_router.patch("/{session_id}/messages/last")
async def patch_last_session_message(
    session_id: str,
    body: LastMessagePatchIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    meta: dict[str, Any] = {}
    if body.modelId:
        meta["modelId"] = body.modelId
    if body.modelName:
        meta["modelName"] = body.modelName
    if body.receivedAt is not None:
        meta["receivedAt"] = body.receivedAt
    try:
        session = await update_last_session_message(
            db,
            user.id,
            session_id,
            body.content,
            meta=meta or None,
            expected_revision=body.expectedRevision,
        )
    except RevisionConflictError as exc:
        await db.rollback()
        raise _revision_conflict(exc) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()
    return session


@messages_router.post("/{session_id}/cancel-stream")
async def cancel_session_stream(
    session_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Signal an in-flight server-owned completion to stop (works after page refresh)."""
    session = await cancel_streaming_reply(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or nothing to cancel")
    await db.commit()
    return session


@router.get("/prefs")
async def get_user_prefs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_read_db)):
    return await load_user_prefs(db, user.id)


@router.patch("/prefs")
async def patch_user_prefs(
    body: UserPrefsPatchIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return await load_user_prefs(db, user.id)
    try:
        result = await save_user_prefs(db, user.id, updates)
        await db.commit()
        return result
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=413, detail=str(exc)) from exc
