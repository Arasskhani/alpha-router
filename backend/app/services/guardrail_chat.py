"""A chat turn the administrator's Guardrails refused, as the chat keeps and shows it.

The server writes the refused turn itself, so what is stored never depends on
the client: the person's message with every found value replaced by its hint
(``603…453``), marked as held back - it is never sent to a model again, so the
chat goes on - and in place of an answer the rule's message, marked as a
refusal so the chat shows it as the organisation's, not as a model's error.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage
from app.services.chat_markers import GUARDRAIL_BLOCKED_META_KEY, GUARDRAIL_HELD_BACK_META_KEY
from app.services.guardrail_policy import redact_for_storage

logger = logging.getLogger(__name__)


def _user_content(body: dict[str, Any]) -> str | None:
    """The person's message as the client keeps it (``user_message``), else the last one sent, when it is text."""
    message = body.get("user_message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return str(message["content"])
    for item in reversed(list(body.get("messages") or [])):
        if isinstance(item, dict) and item.get("role") == "user":
            return item["content"] if isinstance(item.get("content"), str) else None
    return None


def refused_user_content(body: dict[str, Any], values: list[str], secrets: set[str]) -> str | None:
    """The person's message with the found values hidden: what the chat keeps and shows of it."""
    content = _user_content(body)
    return redact_for_storage(content, values, secret_values=secrets) if content is not None else None


async def keep_refused_turn(
    db: AsyncSession,
    *,
    user_id: int,
    body: dict[str, Any],
    message: str,
    user_content: str | None,
    held_back: bool,
    model_id: str | None = None,
    model_name: str | None = None,
) -> bool:
    """Write the refused turn to the person's chat when the turn is one the server keeps; whether it was written.

    ``held_back``: the person's own message was what a rule refused - it is kept
    with its values hidden and never sent again. Otherwise (what the platform
    added was refused) it is kept as it was.
    """
    from app.services.chat_completion_persistence import PrivateModePersistenceError, persister_from_body

    try:
        persister = persister_from_body(db, user_id=user_id, body=body, model_id=model_id, model_name=model_name)
    except PrivateModePersistenceError:
        return False
    if persister is None:
        return False
    if persister.user_message is not None and user_content is not None:
        persister.user_message = {**persister.user_message, "content": user_content}
    persister.set_message_metadata({GUARDRAIL_BLOCKED_META_KEY: {"message": message}})
    try:
        await persister.prepare()
        marks: dict[str, dict[str, Any]] = {
            # No answer is coming: the placeholder is done, and says when.
            persister.assistant_client_message_id: {"streaming": False, "receivedAt": _now_ms()},
        }
        if held_back and persister.user_message is not None:
            marks[str(persister.user_message.get("clientMessageId") or "")] = {GUARDRAIL_HELD_BACK_META_KEY: True}
        rows = (
            (
                await db.execute(
                    select(ChatMessage).where(
                        ChatMessage.session_id == persister.session_id,
                        ChatMessage.user_id == user_id,
                        ChatMessage.client_message_id.in_(list(marks)),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            current: dict[str, Any] = row.meta if isinstance(row.meta, dict) else {}
            cast(Any, row).meta = {**current, **marks[str(row.client_message_id)]}
        await db.commit()
    except Exception:  # noqa: BLE001 -- the refusal stands; the client then keeps the turn as it can
        logger.exception("Could not keep a refused turn session_id=%s", persister.session_id)
        await db.rollback()
        return False
    return True


def _now_ms() -> int:
    return int(dt.datetime.now(dt.UTC).timestamp() * 1000)
