"""A chat's messages as the model reads them, and a turn's history made whole.

The web app builds each turn's history from the messages it has loaded. A
chat opened from the list holds only its latest page, so a client that has
not read the older pages (an old tab, a failed read, a flow that slices the
loaded messages) sends the model a chat that starts in the middle. The client
says where its history starts (``history_from_sequence``: the sequence of its
first message), and the server puts the chat's older messages in front.

The same reading of a stored message - attachments, voice notes, generated
media - is what the chat's summary and its recall index are built from.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage
from app.services.chat_markers import (
    ATTACHMENT_MESSAGE_PREFIX,
    AUDIO_MESSAGE_PREFIX,
    IMAGE_MESSAGE_PREFIX,
    IMAGE_PENDING_MARKER,
    SPEECH_MESSAGE_PREFIX,
    SPEECH_PENDING_MARKER,
    VIDEO_MESSAGE_PREFIX,
    VIDEO_PENDING_MARKER,
)

logger = logging.getLogger(__name__)

#: The most older messages put in front of one turn.
MAX_COMPLETED_MESSAGES = 5000
#: And the most characters: a turn is fitted into the model's window afterwards, and more than this never fits
#: one (about a million tokens); nor is it read into a worker's memory for one request.
MAX_COMPLETED_CHARS = 4_000_000
#: Rows read at a time, newest first, until either limit is reached.
READ_BATCH = 100

_PENDING = frozenset({IMAGE_PENDING_MARKER, VIDEO_PENDING_MARKER, SPEECH_PENDING_MARKER})
_MEDIA = (
    (IMAGE_MESSAGE_PREFIX, "Generated image"),
    (VIDEO_MESSAGE_PREFIX, "Generated video"),
    (SPEECH_MESSAGE_PREFIX, "Generated speech"),
)


def _json_after(content: str, prefix: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content[len(prefix) :])
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _attachment_text(payload: dict[str, Any]) -> str:
    chunks = [str(payload.get("userText") or "").strip()]
    images: list[str] = []
    for attachment in payload.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name") or "attachment")
        text = str(attachment.get("text") or "").strip()
        if text:
            chunks.append(f"--- {name} ---\n{text}")
        elif str(attachment.get("kind") or "") == "image":
            images.append(name)
        else:
            chunks.append(f"[Attached file: {name}]")
    if images:
        chunks.append(f"[Attached image(s): {', '.join(images)}]")
    return "\n\n".join(chunk for chunk in chunks if chunk)


def message_text_for_model(content: Any) -> str:
    """A stored message's words, as the model is to read them; "" for one it would not see.

    Attachments give the words typed with them and each file's text; a voice
    note its transcript; a generated image, video or speech a line naming it
    with its prompt. A reply still being made (a pending marker) says nothing.
    """
    if isinstance(content, list):
        parts = [
            str(item.get("text") or "") for item in content if isinstance(item, dict) and item.get("type") == "text"
        ]
        return " ".join(part for part in parts if part).strip()
    text = str(content or "").strip()
    if not text or text in _PENDING:
        return ""
    if text.startswith(ATTACHMENT_MESSAGE_PREFIX):
        payload = _json_after(text, ATTACHMENT_MESSAGE_PREFIX)
        return _attachment_text(payload) if payload is not None else text
    if text.startswith(AUDIO_MESSAGE_PREFIX):
        payload = _json_after(text, AUDIO_MESSAGE_PREFIX)
        return str((payload or {}).get("transcript") or "").strip()
    for prefix, label in _MEDIA:
        if text.startswith(prefix):
            payload = _json_after(text, prefix) or {}
            prompt = str(payload.get("prompt") or payload.get("text") or "").strip()
            return f"[{label}: {prompt}]" if prompt else f"[{label}]"
    return text


async def _read_older(
    db: AsyncSession,
    session_id: str,
    *,
    before_sequence: int,
    limit: int = MAX_COMPLETED_MESSAGES,
    max_chars: int | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """The chat's user and assistant messages older than ``before_sequence``, oldest first, as the model reads them;
    and whether the character budget cut them short.

    Read newest first, a batch at a time, up to ``limit`` messages and
    ``max_chars`` characters (``MAX_COMPLETED_CHARS``): the ones nearest the
    turn are the ones kept.
    """
    budget = int(max_chars or MAX_COMPLETED_CHARS)
    newest_first: list[dict[str, str]] = []
    total = 0
    read = 0
    upper = int(before_sequence)
    while read < int(limit):
        rows = (
            await db.execute(
                select(ChatMessage.sequence, ChatMessage.role, ChatMessage.content)
                .where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.sequence < upper,
                    ChatMessage.role.in_(("user", "assistant")),
                )
                .order_by(ChatMessage.sequence.desc())
                .limit(min(READ_BATCH, int(limit) - read))
            )
        ).all()
        for _sequence, role, content in rows:
            text = message_text_for_model(content)
            if not text:
                continue
            if total + len(text) > budget:
                return list(reversed(newest_first)), True
            newest_first.append({"role": str(role), "content": text})
            total += len(text)
        read += len(rows)
        if len(rows) < READ_BATCH:
            break
        upper = int(rows[-1][0])
    return list(reversed(newest_first)), False


async def complete_chat_history(
    db: AsyncSession,
    *,
    user: object,
    chat_session_id: str | None,
    messages: list[dict],
    history_from_sequence: int | None,
) -> tuple[list[dict], int]:
    """``messages`` with the chat's messages older than the client's first put in front; and how many were.

    Only in a chat the person may write in, never a private one, and only
    while the administrator leaves it on. Leading system messages stay first.
    A failure to read leaves the turn as it came (in a savepoint, so it
    does not take the turn's transaction with it).
    """
    from app.services.observability import observe_chat_history_completion

    if not history_from_sequence or int(history_from_sequence) <= 1 or not chat_session_id:
        return messages, 0
    try:
        async with db.begin_nested():
            completed, added, outcome = await _complete(
                db,
                user=user,
                chat_session_id=chat_session_id,
                messages=messages,
                history_from_sequence=int(history_from_sequence),
            )
    except Exception:
        logger.exception("completing a turn's history failed session_id=%s; sent as it came", chat_session_id)
        observe_chat_history_completion("failed")
        return messages, 0
    observe_chat_history_completion(outcome, added=added)
    return completed, added


async def _complete(
    db: AsyncSession,
    *,
    user: object,
    chat_session_id: str,
    messages: list[dict],
    history_from_sequence: int,
) -> tuple[list[dict], int, str]:
    """The completed messages, how many were put in front, and the outcome for the metric."""
    from app.services.chat_session_access import resolve_owned_chat_session
    from app.services.memory_settings_service import get_memory_settings

    settings = await get_memory_settings(db)
    if not settings.get("history_completion_enabled", True):
        return messages, 0, "off"
    try:
        session = await resolve_owned_chat_session(db, user=user, chat_session_id=chat_session_id)
    except HTTPException:
        # Not this person's chat: the turn's own checks answer for that, as before.
        return messages, 0, "refused"
    if session is None or bool(session.private_mode):
        return messages, 0, "refused"
    older, capped = await _read_older(db, str(session.id), before_sequence=int(history_from_sequence))
    if not older:
        return messages, 0, "nothing_older"
    lead = 0
    while lead < len(messages) and str((messages[lead] or {}).get("role") or "") == "system":
        lead += 1
    logger.info(
        "chat history completed on the server session_id=%s added=%s from_sequence=%s",
        session.id,
        len(older),
        history_from_sequence,
    )
    return [*messages[:lead], *older, *messages[lead:]], len(older), "capped" if capped else "completed"
