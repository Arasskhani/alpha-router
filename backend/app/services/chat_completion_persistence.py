"""Persist chat messages during /api/chat/completions streaming (server-owned)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.agent_runtime import AgentRun
from app.models.chat import ChatMessage, ChatSession
from app.services.private_mode_service import (
    PrivateModePersistenceError,
    effective_private_mode,
)
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

logger = logging.getLogger(__name__)


async def _maybe_set_fallback_session_title(
    db: AsyncSession,
    user_id: int,
    session_id: str,
    user_message: dict[str, Any] | None,
) -> None:
    """Set a sidebar title from the first user turn when still the default."""
    from app.services.chat_title_service import _fallback_title, _sanitize_title

    row = await db.get(ChatSession, session_id)
    if row is None:
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


#: Meta the persister itself keeps current; server-owned metadata never overrides it.
_PERSISTER_META_KEYS = frozenset({"streaming", "receivedAt", "cancelRequested", "modelId", "modelName"})


def _merge_server_metadata(into: dict[str, Any], metadata: dict[str, Any] | None) -> None:
    if not isinstance(metadata, dict):
        return
    for key, value in metadata.items():
        clean_key = str(key).strip()
        if clean_key and clean_key not in _PERSISTER_META_KEYS:
            into[clean_key] = value


class ChatCompletionPersister:
    """Persist a placeholder and update assistant content during streaming."""

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
        agent_run_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.session_id = session_id
        self.model_id = model_id
        self.model_name = model_name
        self.user_message = user_message
        self.assistant_client_message_id = assistant_client_message_id or str(uuid.uuid4())
        self.agent_run_id = agent_run_id
        self.project_id = (project_id or "").strip() or None
        self._completion_metadata: dict[str, Any] = {}
        self._message_metadata: dict[str, Any] = {}
        self._content = ""
        self._last_persist_len = 0
        self._last_persist_at = 0.0
        self._last_cancel_poll_at = 0.0
        self._cancel_requested = False
        self._prepared = False
        self._bg_flush_task: asyncio.Task[None] | None = None
        self._bg_cancel_task: asyncio.Task[None] | None = None

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

    def set_completion_metadata(self, metadata: dict[str, Any] | None) -> None:
        """Attach server-owned Agent metadata only to the completed message."""

        _merge_server_metadata(self._completion_metadata, metadata)

    def set_message_metadata(self, metadata: dict[str, Any] | None) -> None:
        """Server-owned facts about the answer, on its message from the placeholder on.

        Unlike completion metadata, these are true of the answer before a
        single token arrives, so they are stamped when the placeholder is
        written: a job that reads the chat mid-stream sees them too.
        """
        _merge_server_metadata(self._message_metadata, metadata)

    async def _ensure_chat_session(self) -> None:
        existing = await get_chat_session(self.db, self.user_id, self.session_id)
        if existing is not None:
            return
        payload: dict[str, Any] = {
            "id": self.session_id,
            "title": "New chat",
            "model": self.model_id or "",
        }
        if self.project_id:
            payload["project_id"] = self.project_id
        await create_chat_session(
            self.db,
            self.user_id,
            payload,
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

        appended = await append_session_messages(
            self.db,
            self.user_id,
            self.session_id,
            to_append,
        )
        if self._message_metadata and appended is not None:
            placeholder = (
                await self.db.execute(
                    select(ChatMessage).where(
                        ChatMessage.session_id == self.session_id,
                        ChatMessage.user_id == self.user_id,
                        ChatMessage.client_message_id == self.assistant_client_message_id,
                    )
                )
            ).scalar_one_or_none()
            if placeholder is not None:
                current: dict[str, Any] = placeholder.meta if isinstance(placeholder.meta, dict) else {}
                cast(Any, placeholder).meta = {**current, **self._message_metadata}
        if self.agent_run_id and appended is not None:
            run = await self.db.get(AgentRun, self.agent_run_id)
            if run is None or run.user_id != self.user_id:
                raise ValueError("Agent run is unavailable for chat persistence")
            client_ids = {
                str(message.get("clientMessageId") or "") for message in to_append if message.get("clientMessageId")
            }
            rows = (
                (
                    await self.db.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == self.session_id,
                            ChatMessage.user_id == self.user_id,
                            ChatMessage.client_message_id.in_(client_ids),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                row.agent_run_id = self.agent_run_id
        await self.db.commit()
        self._prepared = True

    def _should_partial_flush(self) -> bool:
        if not self._prepared:
            return False
        delta_chars = len(self._content) - self._last_persist_len
        if delta_chars <= 0:
            return False
        now = time.monotonic()
        return not (
            delta_chars < _STREAM_PERSIST_MIN_CHARS and now - self._last_persist_at < _STREAM_PERSIST_INTERVAL_SEC
        )

    def schedule_content(self, content: str) -> None:
        """Store the latest assistant text and flush later, off the SSE path.

        Callers must not await this. A background task writes to a dedicated
        DB session so token yield is not blocked on commit latency.
        """
        if not self._prepared:
            return
        self._content = content
        if self._bg_flush_task is not None and not self._bg_flush_task.done():
            return
        if not self._should_partial_flush():
            return
        try:
            self._bg_flush_task = asyncio.get_running_loop().create_task(self._background_partial_flush())
        except RuntimeError:
            return

    async def _background_partial_flush(self) -> None:
        while self._should_partial_flush():
            content = self._content
            try:
                async with AsyncSessionLocal() as db:
                    await self._flush_on(db, content, partial=True)
            except Exception:
                logger.exception("Background stream persist failed session=%s", self.session_id)
                self.reset_persist_state()
                return
            if content == self._content:
                return

    async def drain_background(self) -> None:
        """Wait for in-flight persist/cancel tasks before a request-session write."""
        tasks = [task for task in (self._bg_flush_task, self._bg_cancel_task) if task is not None and not task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._bg_flush_task = None
        self._bg_cancel_task = None

    async def on_content(self, content: str) -> None:
        if not self._prepared:
            return
        self._content = content
        if not self._should_partial_flush():
            return
        await self._flush(content, partial=True)

    def peek_cancel_requested(self) -> bool:
        return self._cancel_requested

    def schedule_cancel_poll(self) -> None:
        """Kick a non-blocking cancel-flag read; the next token checks the result."""
        if not self.session_id or self._cancel_requested:
            return
        now = time.monotonic()
        if now - self._last_cancel_poll_at < _CANCEL_POLL_INTERVAL_SEC:
            return
        if self._bg_cancel_task is not None and not self._bg_cancel_task.done():
            return
        self._last_cancel_poll_at = now
        try:
            self._bg_cancel_task = asyncio.get_running_loop().create_task(self._background_cancel_poll())
        except RuntimeError:
            return

    async def _background_cancel_poll(self) -> None:
        try:
            async with AsyncSessionLocal() as db:
                self._cancel_requested = await _read_cancel_flag(db, self.session_id)
        except Exception:  # noqa: BLE001 -- falls back to a safe default value
            self._cancel_requested = False

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
        except Exception:  # noqa: BLE001 -- falls back to a safe default value
            self._cancel_requested = False
        return self._cancel_requested

    async def finalize(self, *, success: bool, error_message: str | None = None) -> None:
        await self.drain_background()
        if not self._prepared:
            return
        cancelled = await self.is_cancel_requested(force=True)
        if cancelled:
            success = True
            error_message = None
        content = self._content
        if not success and error_message and error_message != "client_disconnected":
            content = f"{content}\n\nError: {error_message}" if content.strip() else f"Error: {error_message}"
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
        except Exception:  # noqa: BLE001 -- session is rolled back and the caller continues without the write
            # Last-resort: roll back and retry the final write once on a clean
            # transaction so the assistant message is not left streaming=True.
            with contextlib.suppress(Exception):
                await self.db.rollback()
            try:
                await self._flush(content, partial=False)
                await self.db.commit()
            except Exception:  # noqa: BLE001 -- session is rolled back and the caller continues without the write
                await self.db.rollback()

    async def _flush(self, content: str, *, partial: bool) -> None:
        await self._flush_on(self.db, content, partial=partial)

    async def _flush_on(self, db: AsyncSession, content: str, *, partial: bool) -> None:
        meta: dict[str, Any] = dict(self._message_metadata)
        if not partial:
            meta.update(self._completion_metadata)
        meta["streaming"] = partial
        if self.model_id:
            meta["modelId"] = self.model_id
        if self.model_name:
            meta["modelName"] = self.model_name
        if not partial:
            meta["streaming"] = False
            meta["receivedAt"] = int(time.time() * 1000)
            meta["cancelRequested"] = False
        await update_last_session_message(
            db,
            self.user_id,
            self.session_id,
            content,
            meta=meta or None,
        )
        await db.commit()
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
    if effective_private_mode(body):
        raise PrivateModePersistenceError("Private Mode conversations cannot be persisted on the server")
    session_id = body.get("chat_session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    user_message = body.get("user_message")
    if user_message is not None and not isinstance(user_message, dict):
        user_message = None
    assistant_id = body.get("assistant_client_message_id")
    if assistant_id is not None:
        assistant_id = str(assistant_id)
    project_id = body.get("project_id") or body.get("projectId")
    project_id = None if not isinstance(project_id, str) or not project_id.strip() else project_id.strip()
    return ChatCompletionPersister(
        db,
        user_id=user_id,
        session_id=session_id.strip(),
        model_id=model_id,
        model_name=model_name,
        user_message=user_message,
        assistant_client_message_id=assistant_id,
        agent_run_id=(str(body.get("_agent_run_id")) if body.get("_agent_run_id") else None),
        project_id=project_id,
    )
