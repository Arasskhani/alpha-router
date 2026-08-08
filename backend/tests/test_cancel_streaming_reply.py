"""Tests for server-side streaming cancellation."""

import asyncio
import datetime as dt
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatMessage
from app.models.user import User
from app.services.chat_completion_persistence import ChatCompletionPersister
from app.services.user_chat_storage_service import (
    _STALE_IMAGE_PENDING_SEC,
    IMAGE_PENDING_MARKER,
    append_session_messages,
    cancel_streaming_reply,
    create_chat_session,
    list_session_messages,
)


class _SessionCtx:
    def __init__(self, factory):
        self._factory = factory

    async def __aenter__(self):
        self._session = self._factory()
        return await self._session.__aenter__()

    async def __aexit__(self, *args):
        return await self._session.__aexit__(*args)


async def _run_cancel_roundtrip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session_ctx = _SessionCtx(session_factory)
        with patch(
            "app.services.chat_completion_persistence.AsyncSessionLocal",
            return_value=session_ctx,
        ):
            session.add(
                User(
                    username="tester",
                    email="tester@alpha-router.local",
                    display_name="Tester",
                    hashed_password="x",
                    auth_provider="local",
                )
            )
            await session.commit()
            user = (await session.execute(select(User))).scalar_one()

            await create_chat_session(
                session,
                user.id,
                {"id": "s1", "title": "Hello", "model": "gpt-4"},
            )
            await session.commit()

            persister = ChatCompletionPersister(
                session,
                user_id=user.id,
                session_id="s1",
                model_id="model::1",
                model_name="GPT",
                user_message={
                    "role": "user",
                    "content": "Hi",
                    "clientMessageId": "u1",
                },
                assistant_client_message_id="a1",
            )
            await persister.prepare()
            await persister.on_content("Partial")
            await session.commit()

            cancelled = await cancel_streaming_reply(session, user.id, "s1")
            assert cancelled is not None
            await session.commit()

            msgs, _ = await list_session_messages(session, user.id, "s1")
            assert msgs[-1]["content"] == "Partial"
            assert msgs[-1].get("receivedAt") is not None
            assert msgs[-1].get("streaming") is False

            assert await persister.is_cancel_requested()
            await persister.finalize(success=True)
            await session.commit()

            row = (
                await session.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == "s1")
                    .order_by(ChatMessage.sequence.desc())
                )
            ).scalars().first()
            assert row is not None
            assert not (row.meta or {}).get("cancelRequested")
    await engine.dispose()


async def _run_cancel_image_pending() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester2",
                email="tester2@alpha-router.local",
                display_name="Tester",
                hashed_password="x",
                auth_provider="local",
            )
        )
        await session.commit()
        user = (await session.execute(select(User))).scalar_one()

        await create_chat_session(
            session,
            user.id,
            {"id": "img1", "title": "Image", "model": "gpt-4"},
        )
        await append_session_messages(
            session,
            user.id,
            "img1",
            [
                {"role": "user", "content": "Draw a cat", "clientMessageId": "u1"},
                {
                    "role": "assistant",
                    "content": IMAGE_PENDING_MARKER,
                    "clientMessageId": "a1",
                    "streaming": True,
                },
            ],
        )
        await session.commit()

        cancelled = await cancel_streaming_reply(session, user.id, "img1")
        assert cancelled is not None
        await session.commit()

        msgs, _ = await list_session_messages(session, user.id, "img1")
        assert msgs[-1]["content"] == "Image generation stopped."
        assert msgs[-1].get("receivedAt") is not None
    await engine.dispose()


async def _run_stale_pending_reconcile() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester3",
                email="tester3@alpha-router.local",
                display_name="Tester",
                hashed_password="x",
                auth_provider="local",
            )
        )
        await session.commit()
        user = (await session.execute(select(User))).scalar_one()

        await create_chat_session(
            session,
            user.id,
            {"id": "img2", "title": "Image", "model": "gpt-4"},
        )
        await append_session_messages(
            session,
            user.id,
            "img2",
            [
                {"role": "user", "content": "Draw a dog", "clientMessageId": "u1"},
                {
                    "role": "assistant",
                    "content": IMAGE_PENDING_MARKER,
                    "clientMessageId": "a1",
                    "streaming": True,
                },
            ],
        )
        await session.commit()

        # A live (slow) generation must NOT be finalized by a read.
        msgs, _ = await list_session_messages(session, user.id, "img2")
        assert msgs[-1]["content"] == IMAGE_PENDING_MARKER

        # Age the pending row past the stale threshold: reads now reconcile it.
        row = (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == "img2")
                .order_by(ChatMessage.sequence.desc())
            )
        ).scalars().first()
        assert row is not None
        row.created_at = dt.datetime.utcnow() - dt.timedelta(
            seconds=_STALE_IMAGE_PENDING_SEC + 5
        )
        await session.commit()

        msgs, _ = await list_session_messages(session, user.id, "img2")
        assert msgs[-1]["content"] == "Image generation stopped."
        assert msgs[-1].get("receivedAt") is not None
    await engine.dispose()


async def _run_cancel_orphan_pending_with_received_at() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester4",
                email="tester4@alpha-router.local",
                display_name="Tester",
                hashed_password="x",
                auth_provider="local",
            )
        )
        await session.commit()
        user = (await session.execute(select(User))).scalar_one()

        await create_chat_session(
            session,
            user.id,
            {"id": "img3", "title": "Image", "model": "gpt-4"},
        )
        await append_session_messages(
            session,
            user.id,
            "img3",
            [
                {"role": "user", "content": "Draw a bird", "clientMessageId": "u1"},
                {
                    "role": "assistant",
                    "content": IMAGE_PENDING_MARKER,
                    "clientMessageId": "a1",
                    "receivedAt": 1_700_000_000_000,
                    "streaming": False,
                },
            ],
        )
        await session.commit()

        cancelled = await cancel_streaming_reply(session, user.id, "img3")
        assert cancelled is not None
        await session.commit()

        msgs, _ = await list_session_messages(session, user.id, "img3")
        assert msgs[-1]["content"] == "Image generation stopped."
        assert msgs[-1].get("receivedAt") is not None
    await engine.dispose()


def test_cancel_streaming_reply_roundtrip() -> None:
    asyncio.run(_run_cancel_roundtrip())


def test_cancel_image_pending_finalizes() -> None:
    asyncio.run(_run_cancel_image_pending())


def test_stale_image_pending_reconciled_only_after_threshold() -> None:
    asyncio.run(_run_stale_pending_reconcile())


async def _run_reconcile_orphan_pending_with_received_at() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester5",
                email="tester5@alpha-router.local",
                display_name="Tester",
                hashed_password="x",
                auth_provider="local",
            )
        )
        await session.commit()
        user = (await session.execute(select(User))).scalar_one()

        await create_chat_session(
            session,
            user.id,
            {"id": "img4", "title": "Image", "model": "gpt-4"},
        )
        await append_session_messages(
            session,
            user.id,
            "img4",
            [
                {"role": "user", "content": "Draw a fish", "clientMessageId": "u1"},
                {
                    "role": "assistant",
                    "content": IMAGE_PENDING_MARKER,
                    "clientMessageId": "a1",
                    "receivedAt": 1_700_000_000_000,
                    "streaming": False,
                },
            ],
        )
        await session.commit()

        msgs, _ = await list_session_messages(session, user.id, "img4")
        assert msgs[-1]["content"] == "Image generation stopped."
    await engine.dispose()


def test_cancel_orphan_image_pending_with_received_at() -> None:
    asyncio.run(_run_cancel_orphan_pending_with_received_at())


def test_reconcile_orphan_image_pending_with_received_at() -> None:
    asyncio.run(_run_reconcile_orphan_pending_with_received_at())
