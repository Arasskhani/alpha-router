"""Per-message feedback ownership, idempotency, and Bayesian aggregation."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatMessage
from app.models.user import User
from app.services.chat_feedback_service import (
    feedback_quality_signals,
    set_message_feedback,
)
from app.services.user_chat_storage_service import (
    append_session_messages,
    create_chat_session,
    list_session_messages,
)


async def _run_feedback_roundtrip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        user = User(
            username="feedback-user",
            email="feedback@alpha-router.local",
            display_name="Feedback",
            hashed_password="x",
            auth_provider="local",
        )
        db.add(user)
        await db.flush()
        await create_chat_session(db, user.id, {"id": "feedback-session", "model": "model-a"})
        await append_session_messages(
            db,
            user.id,
            "feedback-session",
            [
                {
                    "role": "assistant",
                    "content": "A completed answer",
                    "modelId": "model-a",
                    "receivedAt": 1,
                    "clientMessageId": "assistant-1",
                }
            ],
        )
        message = (await db.execute(select(ChatMessage))).scalar_one()

        row = await set_message_feedback(
            db,
            user_id=user.id,
            session_id="feedback-session",
            message_id=message.id,
            rating=1,
        )
        assert row is not None
        assert row.model_id == "model-a"

        # Repeating or changing a vote updates one row instead of double-counting.
        row = await set_message_feedback(
            db,
            user_id=user.id,
            session_id="feedback-session",
            message_id=message.id,
            rating=-1,
            reason="incorrect",
        )
        assert row is not None
        assert row.rating == -1
        signals = await feedback_quality_signals(
            db,
            model_ids=["model-a"],
            output_kind="text",
        )
        assert signals["model-a"]["count"] == 1
        assert signals["model-a"]["likes"] == 0

        messages, _ = await list_session_messages(db, user.id, "feedback-session")
        assert messages[0]["feedback"] == {"rating": -1, "reason": "incorrect"}

        removed = await set_message_feedback(
            db,
            user_id=user.id,
            session_id="feedback-session",
            message_id=message.id,
            rating=0,
        )
        assert removed is None
        signals = await feedback_quality_signals(
            db,
            model_ids=["model-a"],
            output_kind="text",
        )
        assert signals == {}
    await engine.dispose()


def test_chat_feedback_roundtrip() -> None:
    asyncio.run(_run_feedback_roundtrip())
