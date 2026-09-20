"""Whose chat is it, when the turn arrives on a personal API key?

Browser chat and the OpenAI-compatible gateway share preflight_stream_chat, so
they shared the memory injection too: paste a personal key into an editor, a
cron script or a service the team calls, and the owner's durable personal
facts — health and financial ones included, when the admin allows those
categories — went into that app's prompt. Private Mode does not help; a
gateway request carries no session and no flag, so it resolves to non-private
every time.

Nothing is learned on that path either way, because gateway turns are never
persisted as a chat session and so never schedule extraction. Reading without
writing is exactly the asymmetry worth an explicit switch.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.user import User
from app.services.user_chat_storage_service import save_user_prefs
from app.services.user_memory_service import augment_messages_with_memory, create_memory


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user_with_a_memory(db: AsyncSession) -> User:
    user = User(
        username="keyholder",
        email="key@alpha-router.local",
        hashed_password="x",
        auth_provider="local",
    )
    db.add(user)
    await db.flush()
    await create_memory(db, user.id, "User takes lisinopril daily", category="health", origin="auto")
    await db.commit()
    return user


def _injected(messages: list[dict]) -> bool:
    return any("## User memory" in str(message.get("content") or "") for message in messages)


async def test_browser_chat_still_gets_the_memories() -> None:
    factory, engine = await _factory()
    async with factory() as db:
        user = await _user_with_a_memory(db)
        out = await augment_messages_with_memory(
            db,
            [{"role": "user", "content": "what should I avoid?"}],
            user_id=user.id,
        )
        assert _injected(out)
    await engine.dispose()


async def test_an_api_key_turn_gets_nothing_by_default() -> None:
    factory, engine = await _factory()
    async with factory() as db:
        user = await _user_with_a_memory(db)
        out = await augment_messages_with_memory(
            db,
            [{"role": "user", "content": "what should I avoid?"}],
            user_id=user.id,
            via_api_key=True,
        )
        assert not _injected(out)
        assert out == [{"role": "user", "content": "what should I avoid?"}]
    await engine.dispose()


async def test_an_api_key_turn_gets_them_once_the_user_opts_in() -> None:
    factory, engine = await _factory()
    async with factory() as db:
        user = await _user_with_a_memory(db)
        await save_user_prefs(db, user.id, {"memory_outside_chat": True})
        await db.commit()
        out = await augment_messages_with_memory(
            db,
            [{"role": "user", "content": "what should I avoid?"}],
            user_id=user.id,
            via_api_key=True,
        )
        assert _injected(out)
    await engine.dispose()


async def test_opting_in_does_not_override_the_master_switch() -> None:
    factory, engine = await _factory()
    async with factory() as db:
        user = await _user_with_a_memory(db)
        await save_user_prefs(db, user.id, {"memory_outside_chat": True, "memory_enabled": False})
        await db.commit()
        for via_api_key in (False, True):
            out = await augment_messages_with_memory(
                db,
                [{"role": "user", "content": "what should I avoid?"}],
                user_id=user.id,
                via_api_key=via_api_key,
            )
            assert not _injected(out)
    await engine.dispose()


async def test_private_mode_still_wins_over_the_opt_in() -> None:
    factory, engine = await _factory()
    async with factory() as db:
        user = await _user_with_a_memory(db)
        await save_user_prefs(db, user.id, {"memory_outside_chat": True})
        await db.commit()
        out = await augment_messages_with_memory(
            db,
            [{"role": "user", "content": "what should I avoid?"}],
            user_id=user.id,
            private_mode=True,
            via_api_key=True,
        )
        assert not _injected(out)
    await engine.dispose()
