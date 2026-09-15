"""Per-message feedback and aggregate quality signals for model routing."""

from __future__ import annotations

import datetime
import json
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatMessageFeedback, ChatSession
from app.services.chat_markers import (
    IMAGE_MESSAGE_PREFIX,
    IMAGE_PENDING_MARKER,
    VIDEO_MESSAGE_PREFIX,
)

VALID_FEEDBACK_REASONS = frozenset(
    {
        "incorrect",
        "irrelevant",
        "low_detail",
        "low_quality",
        "slow",
        "other",
    }
)


def _media_payload_model(content: str, prefix: str) -> str | None:
    if not content.startswith(prefix):
        return None
    try:
        payload = json.loads(content[len(prefix) :])
    except (json.JSONDecodeError, TypeError):
        return None
    model = payload.get("model") if isinstance(payload, dict) else None
    return str(model).strip() if model else None


def _image_payload_model(content: str) -> str | None:
    return _media_payload_model(content, IMAGE_MESSAGE_PREFIX)


def feedback_target(message: ChatMessage) -> tuple[str, str | None]:
    content = str(message.content or "")
    if content.startswith(VIDEO_MESSAGE_PREFIX):
        output_kind = "video"
    elif content.startswith(IMAGE_MESSAGE_PREFIX):
        output_kind = "image"
    else:
        output_kind = "text"
    meta = message.meta if isinstance(message.meta, dict) else {}
    model_id = (
        _media_payload_model(content, VIDEO_MESSAGE_PREFIX)
        or _image_payload_model(content)
        or str(meta.get("modelId") or "").strip()
        or None
    )
    return output_kind, model_id


async def set_message_feedback(
    db: AsyncSession,
    *,
    user_id: int,
    session_id: str,
    message_id: str,
    rating: int,
    reason: str | None = None,
) -> ChatMessageFeedback | None:
    message = (
        await db.execute(
            select(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatMessage.id == message_id,
                ChatMessage.session_id == session_id,
                ChatSession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if message is None:
        raise LookupError("Assistant message not found")
    if message.role != "assistant":
        raise ValueError("Feedback is only accepted for assistant messages")
    content = str(message.content or "")
    meta = message.meta if isinstance(message.meta, dict) else {}
    if not content.strip() or content == IMAGE_PENDING_MARKER or meta.get("streaming") is True:
        raise ValueError("Feedback is only accepted for completed responses")

    existing = (
        await db.execute(
            select(ChatMessageFeedback).where(
                ChatMessageFeedback.message_id == message_id,
                ChatMessageFeedback.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if rating == 0:
        if existing is not None:
            await db.delete(existing)
            await db.flush()
        return None
    if rating not in (-1, 1):
        raise ValueError("Rating must be -1, 0, or 1")
    normalized_reason = (reason or "").strip().lower() or None
    if normalized_reason and normalized_reason not in VALID_FEEDBACK_REASONS:
        raise ValueError("Invalid feedback reason")
    if rating > 0:
        normalized_reason = None

    output_kind, model_id = feedback_target(message)
    now = datetime.datetime.utcnow()
    if existing is None:
        existing = ChatMessageFeedback(
            message_id=message.id,
            session_id=session_id,
            user_id=user_id,
            rating=rating,
            reason=normalized_reason,
            output_kind=output_kind,
            model_id=model_id,
            created_at=now,
            updated_at=now,
        )
        db.add(existing)
    else:
        existing.rating = rating
        existing.reason = normalized_reason
        existing.output_kind = output_kind
        existing.model_id = model_id
        existing.updated_at = now
    await db.flush()
    return existing


async def feedback_quality_signals(
    db: AsyncSession,
    *,
    model_ids: list[str],
    output_kind: str,
) -> dict[str, dict[str, float | int]]:
    if not model_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ChatMessageFeedback.model_id,
                func.count(ChatMessageFeedback.id),
                func.sum(case((ChatMessageFeedback.rating > 0, 1), else_=0)),
            )
            .where(
                ChatMessageFeedback.output_kind == output_kind,
                ChatMessageFeedback.model_id.in_(model_ids),
            )
            .group_by(ChatMessageFeedback.model_id)
        )
    ).all()
    signals: dict[str, dict[str, float | int]] = {}
    prior_mean = 0.75
    prior_weight = 10.0
    for model_id, total, positive in rows:
        count = int(total or 0)
        likes = int(positive or 0)
        bayesian = (likes + prior_mean * prior_weight) / (count + prior_weight)
        signals[str(model_id)] = {
            "count": count,
            "likes": likes,
            "score": bayesian,
        }
    return signals


def feedback_payload(row: ChatMessageFeedback | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "rating": int(row.rating),
        "reason": row.reason,
        "output_kind": row.output_kind,
        "model_id": row.model_id,
    }
