"""Tests for retention policy settings."""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.services.retention_policy_service import (
    get_chat_retention_settings,
    purge_expired_chat_messages,
    set_chat_retention_settings,
)


async def _run_settings_roundtrip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        defaults = await get_chat_retention_settings(session)
        assert defaults["retention_enabled"] is False
        assert defaults["retention_days"] >= 1
        assert defaults["clear_schedule_enabled"] is False
        assert defaults["cleanup_active"] is False
        assert isinstance(defaults["schedule_timezone"], str)
        assert defaults["schedule_timezone"]

        updated = await set_chat_retention_settings(
            session,
            retention_enabled=True,
            retention_days=90,
            clear_schedule_enabled=True,
            clear_schedule_hour=5,
            clear_schedule_minute=30,
        )
        assert updated["retention_enabled"] is True
        assert updated["retention_days"] == 90
        assert updated["clear_schedule_enabled"] is True
        assert updated["cleanup_active"] is True
        reloaded = await get_chat_retention_settings(session)
        assert reloaded == updated
    await engine.dispose()


async def _run_purge_roundtrip() -> None:
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
                role="user",
                auth_provider="local",
            )
        )
        await session.flush()
        user_id = (
            await session.execute(select(User.id).where(User.username == "tester"))
        ).scalar_one()
        session.add(
            ChatSession(
                id="sess-1",
                user_id=user_id,
                title="Old",
                model_id="m1",
                tools={},
            )
        )
        old_time = dt.datetime.utcnow() - dt.timedelta(days=400)
        session.add(
            ChatMessage(
                id="msg-old",
                session_id="sess-1",
                user_id=user_id,
                role="user",
                content="old",
                sequence=1,
                meta={},
                created_at=old_time,
            )
        )
        session.add(
            ChatMessage(
                id="msg-new",
                session_id="sess-1",
                user_id=user_id,
                role="assistant",
                content="new",
                sequence=2,
                meta={},
                created_at=dt.datetime.utcnow(),
            )
        )
        await session.commit()

        await set_chat_retention_settings(session, retention_enabled=True, retention_days=180)
        result = await purge_expired_chat_messages(session)
        assert result["removed_messages"] == 1
        await session.commit()

        remaining = (await session.execute(select(ChatMessage.content))).scalars().all()
        assert remaining == ["new"]
    await engine.dispose()


async def _run_purge_removes_empty_sessions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="purge_user",
                email="purge@alpha-router.local",
                display_name="Purge",
                hashed_password="x",
                role="user",
                auth_provider="local",
            )
        )
        await session.flush()
        user_id = (
            await session.execute(select(User.id).where(User.username == "purge_user"))
        ).scalar_one()

        session.add(
            ChatSession(
                id="sess-empty-after-purge",
                user_id=user_id,
                title="Should be removed",
                model_id="m1",
                tools={},
            )
        )
        session.add(
            ChatSession(
                id="sess-still-has-msgs",
                user_id=user_id,
                title="Should stay",
                model_id="m1",
                tools={},
            )
        )
        session.add(
            ChatSession(
                id="sess-fresh-empty",
                user_id=user_id,
                title="Fresh empty chat",
                model_id="m1",
                tools={},
            )
        )
        old_time = dt.datetime.utcnow() - dt.timedelta(days=400)
        session.add(
            ChatMessage(
                id="msg-only-old",
                session_id="sess-empty-after-purge",
                user_id=user_id,
                role="user",
                content="old only",
                sequence=1,
                meta={},
                created_at=old_time,
            )
        )
        session.add(
            ChatMessage(
                id="msg-old-partial",
                session_id="sess-still-has-msgs",
                user_id=user_id,
                role="user",
                content="old",
                sequence=1,
                meta={},
                created_at=old_time,
            )
        )
        session.add(
            ChatMessage(
                id="msg-new-partial",
                session_id="sess-still-has-msgs",
                user_id=user_id,
                role="assistant",
                content="new",
                sequence=2,
                meta={},
                created_at=dt.datetime.utcnow(),
            )
        )
        await session.commit()

        await set_chat_retention_settings(session, retention_enabled=True, retention_days=180)
        result = await purge_expired_chat_messages(session)
        await session.commit()

        assert result["removed_messages"] == 2
        assert result["removed_empty_sessions"] == 1

        session_ids = set((await session.execute(select(ChatSession.id))).scalars().all())
        assert "sess-empty-after-purge" not in session_ids
        assert "sess-still-has-msgs" in session_ids
        assert "sess-fresh-empty" in session_ids
    await engine.dispose()


def test_chat_retention_settings_roundtrip():
    import asyncio

    asyncio.run(_run_settings_roundtrip())


def test_chat_retention_purge():
    import asyncio

    asyncio.run(_run_purge_roundtrip())


def test_chat_retention_purge_removes_empty_sessions():
    import asyncio

    asyncio.run(_run_purge_removes_empty_sessions())
