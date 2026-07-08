"""Tests for server-owned chat completion persistence."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.services.chat_completion_persistence import ChatCompletionPersister
from app.services.user_chat_storage_service import create_chat_session, list_session_messages


async def _run_persist_roundtrip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester",
                email="tester@nitro.local",
                display_name="Tester",
                hashed_password="x",
                role="user",
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


def test_chat_completion_persister_roundtrip() -> None:
    asyncio.run(_run_persist_roundtrip())


async def _run_persist_creates_missing_session() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester2",
                email="tester2@nitro.local",
                display_name="Tester2",
                hashed_password="x",
                role="user",
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


def test_chat_completion_persister_creates_missing_session() -> None:
    asyncio.run(_run_persist_creates_missing_session())


async def _run_persist_sets_fallback_title() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester3",
                email="tester3@nitro.local",
                display_name="Tester3",
                hashed_password="x",
                role="user",
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


def test_chat_completion_persister_sets_fallback_title() -> None:
    asyncio.run(_run_persist_sets_fallback_title())
