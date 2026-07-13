"""Persist chat messages during /api/chat/completions streaming (server-owned)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.chat import ChatMessage, ChatSession
from app.services.user_chat_storage_service import (
    append_session_messages,
    create_chat_session,
    get_chat_session,
    update_chat_session,
    update_last_session_message,
)

_STREAM_PERSIST_INTERVAL_SEC = 0.45
_STREAM_PERSIST_MIN_CHARS = 64
_CANCEL_POLL_INTERVAL_SEC = 0.25


async def _maybe_set_fallback_session_title(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    user_message: dict[str, Any] | None,
) -> None:
    """Set a sidebar title from the first user turn when still the default."""
    from app.services.chat_title_service import _fallback_title, _sanitize_title

    row = await db.get(ChatSession, session_id)
    if row is None or row.user_id != user_id:
        return
    if row.title_locked or row.title_generated:
        return
    current = (row.title or "").strip().lower()
    if current and current != "new chat":
        return
    messages: list[dict[str, Any]] = []
    if user_message and user_message.get("content") is not None:
        messages.append(dict(user_message))
    title = _sanitize_title(_fallback_title(messages))
    if title == "New chat":
        return
    await update_chat_session(
        db,
        user_id,
        session_id,
        {"title": title, "titleGenerated": False},
    )


async def _read_cancel_flag(db: AsyncSession, session_id: str) -> bool:
    last = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is None or last.role != "assistant":
        return False
    meta = last.meta if isinstance(last.meta, dict) else {}
    if meta.get("receivedAt") is not None:
        return True
    return bool(meta.get("cancelRequested"))


class ChatCompletionPersister:
    """Append user + assistant placeholder, then PATCH assistant content while streaming."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        session_id: str,
        model_id: str | None = None,
        model_name: str | None = None,
        user_message: dict[str, Any] | None = None,
        assistant_client_message_id: str | None = None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.session_id = session_id
        self.model_id = model_id
        self.model_name = model_name
        self.user_message = user_message
        self.assistant_client_message_id = assistant_client_message_id or str(uuid.uuid4())
        self._content = ""
        self._last_persist_len = 0
        self._last_persist_at = 0.0
        self._last_cancel_poll_at = 0.0
        self._cancel_requested = False
        self._prepared = False

    def reset_persist_state(self) -> None:
        """Reset incremental-flush tracking after the DB session is rolled back.

        When ``on_content`` raises and the caller rolls the session back, the
        last successfully-committed flush is undone too — the row may revert to
        a shorter content (or the empty placeholder). Without resetting these
        counters, the next flush would see a small ``delta_chars`` and skip,
        leaving the assistant message stuck at the pre-rollback content. Forcing
        a full re-write on the next flush keeps the stored message consistent
        with the in-memory ``collected_content``.
        """
        self._last_persist_len = 0
        self._last_persist_at = 0.0

    async def _ensure_chat_session(self) -> None:
        existing = await get_chat_session(self.db, self.user_id, self.session_id)
        if existing is not None:
            return
        await create_chat_session(
            self.db,
            self.user_id,
            {
                "id": self.session_id,
                "title": "New chat",
                "model": self.model_id or "",
            },
        )
        await self.db.flush()

    async def prepare(self) -> None:
        if self._prepared or not self.session_id:
            return
        await self._ensure_chat_session()
        to_append: list[dict[str, Any]] = []
        if self.user_message and self.user_message.get("content") is not None:
            um = dict(self.user_message)
            um.setdefault("role", "user")
            um.setdefault("clientMessageId", um.get("clientMessageId") or str(uuid.uuid4()))
            to_append.append(um)

        assistant: dict[str, Any] = {
            "role": "assistant",
            "content": "",
            "clientMessageId": self.assistant_client_message_id,
            "streaming": True,
        }
        if self.model_id:
            assistant["modelId"] = self.model_id
        if self.model_name:
            assistant["modelName"] = self.model_name
        to_append.append(assistant)

        await append_session_messages(self.db, self.user_id, self.session_id, to_append)
        await self.db.commit()
        self._prepared = True

    async def on_content(self, content: str) -> None:
        if not self._prepared:
            return
        self._content = content
        now = time.monotonic()
        delta_chars = len(content) - self._last_persist_len
        if delta_chars < _STREAM_PERSIST_MIN_CHARS and now - self._last_persist_at < _STREAM_PERSIST_INTERVAL_SEC:
            return
        await self._flush(content, partial=True)

    async def is_cancel_requested(self, *, force: bool = False) -> bool:
        if not self.session_id:
            return False
        if self._cancel_requested:
            return True
        now = time.monotonic()
        if not force and now - self._last_cancel_poll_at < _CANCEL_POLL_INTERVAL_SEC:
            return False
        self._last_cancel_poll_at = now
        try:
            async with AsyncSessionLocal() as db:
                self._cancel_requested = await _read_cancel_flag(db, self.session_id)
        except Exception:
            self._cancel_requested = False
        return self._cancel_requested

    async def finalize(self, *, success: bool, error_message: str | None = None) -> None:
        if not self._prepared:
            return
        cancelled = await self.is_cancel_requested(force=True)
        if cancelled:
            success = True
            error_message = None
        content = self._content
        if not success and error_message and error_message != "client_disconnected":
            if content.strip():
                content = f"{content}\n\nError: {error_message}"
            else:
                content = f"Error: {error_message}"
        elif not content.strip() and not success:
            content = "No response from model."
        # If a prior on_content flush was rolled back, the stored message may be
        # stale; force a full re-write of the final content regardless of the
        # incremental counters.
        self.reset_persist_state()
        try:
            await self._flush(content, partial=False)
            if success:
                await _maybe_set_fallback_session_title(
                    self.db,
                    self.user_id,
                    self.session_id,
                    self.user_message,
                )
                await self.db.commit()
        except Exception:
            # Last-resort: roll back and retry the final write once on a clean
            # transaction so the assistant message is not left streaming=True.
            try:
                await self.db.rollback()
            except Exception:
                pass
            try:
                await self._flush(content, partial=False)
                await self.db.commit()
            except Exception:
                await self.db.rollback()

    async def _flush(self, content: str, *, partial: bool) -> None:
        meta: dict[str, Any] = {"streaming": partial}
        if self.model_id:
            meta["modelId"] = self.model_id
        if self.model_name:
            meta["modelName"] = self.model_name
        if not partial:
            meta["streaming"] = False
            meta["receivedAt"] = int(time.time() * 1000)
            meta["cancelRequested"] = False
        await update_last_session_message(
            self.db,
            self.user_id,
            self.session_id,
            content,
            meta=meta or None,
        )
        await self.db.commit()
        self._last_persist_len = len(content)
        self._last_persist_at = time.monotonic()


def persister_from_body(
    db: AsyncSession,
    *,
    user_id: int,
    body: dict,
    model_id: str | None,
    model_name: str | None = None,
) -> ChatCompletionPersister | None:
    if not body.get("persist_chat"):
        return None
    session_id = body.get("chat_session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    user_message = body.get("user_message")
    if user_message is not None and not isinstance(user_message, dict):
        user_message = None
    assistant_id = body.get("assistant_client_message_id")
    if assistant_id is not None:
        assistant_id = str(assistant_id)
    return ChatCompletionPersister(
        db,
        user_id=user_id,
        session_id=session_id.strip(),
        model_id=model_id,
        model_name=model_name,
        user_message=user_message,
        assistant_client_message_id=assistant_id,
    )
