"""Tests for server-owned chat completion persistence."""

import asyncio
import time
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatSession
from app.models.user import User
from app.services.chat_completion_persistence import ChatCompletionPersister
from app.services.user_chat_storage_service import create_chat_session, list_session_messages


class _SessionCtx:
    def __init__(self, factory):
        self._factory = factory

    async def __aenter__(self):
        self._session = self._factory()
        return await self._session.__aenter__()

    async def __aexit__(self, *args):
        return await self._session.__aexit__(*args)


async def _run_persist_roundtrip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
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
                "content": "Hi there",
                "clientMessageId": "u1",
            },
            assistant_client_message_id="a1",
        )
        await persister.prepare()
        await persister.on_content("Hello")
        await persister.finalize(success=True)

        msgs, _ = await list_session_messages(session, user.id, "s1")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hi there"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "Hello"
        assert msgs[1].get("clientMessageId") == "a1"


async def test_chat_completion_persister_roundtrip() -> None:
    await _run_persist_roundtrip()


async def _run_persist_creates_missing_session() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester2",
                email="tester2@alpha-router.local",
                display_name="Tester2",
                hashed_password="x",
                auth_provider="local",
            )
        )
        await session.commit()
        user = (await session.execute(select(User))).scalar_one()

        persister = ChatCompletionPersister(
            session,
            user_id=user.id,
            session_id="new-session-id",
            model_id="model::1",
            model_name="GPT",
            user_message={
                "role": "user",
                "content": "Hello",
                "clientMessageId": "u-new",
            },
            assistant_client_message_id="a-new",
        )
        await persister.prepare()
        await persister.on_content("World")
        await persister.finalize(success=True)

        msgs, _ = await list_session_messages(session, user.id, "new-session-id")
        assert len(msgs) == 2
        assert msgs[1]["content"] == "World"


async def test_chat_completion_persister_creates_missing_session() -> None:
    await _run_persist_creates_missing_session()


async def _run_persist_sets_fallback_title() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester3",
                email="tester3@alpha-router.local",
                display_name="Tester3",
                hashed_password="x",
                auth_provider="local",
            )
        )
        await session.commit()
        user = (await session.execute(select(User))).scalar_one()

        persister = ChatCompletionPersister(
            session,
            user_id=user.id,
            session_id="titled-session",
            model_id="model::1",
            user_message={
                "role": "user",
                "content": "Explain quantum computing in simple terms",
                "clientMessageId": "u-title",
            },
            assistant_client_message_id="a-title",
        )
        await persister.prepare()
        await persister.on_content("Quantum computing uses qubits.")
        await persister.finalize(success=True)

        row = await session.get(ChatSession, "titled-session")
        assert row is not None
        assert row.title != "New chat"
        assert "quantum" in row.title.lower()


async def test_chat_completion_persister_sets_fallback_title() -> None:
    await _run_persist_sets_fallback_title()


async def _run_schedule_content_does_not_block() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    original_flush = ChatCompletionPersister._flush_on

    async def slow_flush(self, db, content, *, partial):
        await asyncio.sleep(0.25)
        await original_flush(self, db, content, partial=partial)

    async with session_factory() as session:
        session_ctx = _SessionCtx(session_factory)
        with (
            patch(
                "app.services.chat_completion_persistence.AsyncSessionLocal",
                return_value=session_ctx,
            ),
            patch.object(ChatCompletionPersister, "_flush_on", slow_flush),
        ):
            session.add(
                User(
                    username="tester-stream",
                    email="tester-stream@alpha-router.local",
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
                {"id": "s-stream", "title": "Hello", "model": "gpt-4"},
            )
            await session.commit()
            persister = ChatCompletionPersister(
                session,
                user_id=user.id,
                session_id="s-stream",
                model_id="model::1",
                model_name="GPT",
                assistant_client_message_id="a-stream",
            )
            await persister.prepare()
            started = time.monotonic()
            persister.schedule_content("x" * 80)
            elapsed = time.monotonic() - started
            assert elapsed < 0.05
            await persister.drain_background()
            await persister.finalize(success=True)

        msgs, _ = await list_session_messages(session, user.id, "s-stream")
        assert msgs[-1]["content"] == "x" * 80
    await engine.dispose()


async def test_schedule_content_does_not_block_on_flush() -> None:
    await _run_schedule_content_does_not_block()


async def _run_schedule_content_persists_partial() -> None:
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
                    username="tester-bg",
                    email="tester-bg@alpha-router.local",
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
                {"id": "s-bg", "title": "Hello", "model": "gpt-4"},
            )
            await session.commit()
            persister = ChatCompletionPersister(
                session,
                user_id=user.id,
                session_id="s-bg",
                model_id="model::1",
                model_name="GPT",
                assistant_client_message_id="a-bg",
            )
            await persister.prepare()
            persister.schedule_content("partial reply stored off the SSE path " + ("." * 40))
            await persister.drain_background()

        async with session_factory() as reader:
            msgs, _ = await list_session_messages(reader, user.id, "s-bg")
            asst = msgs[-1]
            assert "partial reply stored off the SSE path" in asst["content"]
            assert asst.get("streaming") is True
    await engine.dispose()


async def test_schedule_content_persists_partial_without_finalize() -> None:
    await _run_schedule_content_persists_partial()
