"""Tests for explicit user memory service."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatSession, UserMemory
from app.models.user import User
from app.services.user_chat_storage_service import save_user_prefs
from app.services.user_memory_service import (
    MAX_MEMORIES_PER_USER,
    MemoryLimitError,
    MemoryNotFoundError,
    MemoryValidationError,
    augment_messages_with_memory,
    create_memory,
    delete_all_memories,
    delete_memory,
    list_memories,
    load_injectable_memories,
    memory_content_hash,
    normalize_memory_content,
    update_memory,
)


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _add_user(db: AsyncSession, username: str = "tester") -> User:
    user = User(
        username=username,
        email=f"{username}@alpha-router.local",
        display_name=username.title(),
        hashed_password="x",
        auth_provider="local",
    )
    db.add(user)
    await db.commit()
    return (await db.execute(select(User).where(User.username == username))).scalar_one()


def test_normalize_and_hash() -> None:
    assert normalize_memory_content("  hello   world  ") == "hello world"
    assert memory_content_hash("hello world") == memory_content_hash("  hello   world\n")
    try:
        normalize_memory_content("   ")
        assert False, "expected empty rejection"
    except MemoryValidationError:
        pass
    try:
        normalize_memory_content("x" * 501)
        assert False, "expected length rejection"
    except MemoryValidationError:
        pass


async def _crud_and_inject() -> None:
    engine, factory = await _make_session()
    async with factory() as db:
        user = await _add_user(db)
        other = await _add_user(db, "other")

        created, was_new = await create_memory(db, user.id, "Prefers dark mode")
        await db.commit()
        assert was_new is True
        assert created["content"] == "Prefers dark mode"
        assert created["enabled"] is True

        dup, was_new2 = await create_memory(db, user.id, "  Prefers   dark mode ")
        await db.commit()
        assert was_new2 is False
        assert dup["id"] == created["id"]

        items = await list_memories(db, user.id)
        assert len(items) == 1

        # Ownership: other user cannot update/delete
        try:
            await update_memory(db, other.id, created["id"], content="hack")
            assert False, "expected not found"
        except MemoryNotFoundError:
            pass
        try:
            await delete_memory(db, other.id, created["id"])
            assert False, "expected not found"
        except MemoryNotFoundError:
            pass

        updated = await update_memory(db, user.id, created["id"], enabled=False)
        await db.commit()
        assert updated["enabled"] is False

        facts = await load_injectable_memories(db, user.id)
        assert facts == []

        await update_memory(db, user.id, created["id"], enabled=True)
        await save_user_prefs(db, user.id, {"memory_enabled": False})
        await db.commit()
        assert await load_injectable_memories(db, user.id) == []

        await save_user_prefs(db, user.id, {"memory_enabled": True})
        await db.commit()
        facts = await load_injectable_memories(db, user.id)
        assert facts == ["Prefers dark mode"]

        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        original = [dict(m) for m in messages]
        augmented = await augment_messages_with_memory(
            db, messages, user_id=user.id, private_mode=False
        )
        assert messages == original  # input list not mutated in-place via shared dicts for non-system
        assert augmented[0]["role"] == "system"
        assert "Prefers dark mode" in augmented[0]["content"]
        assert augmented[1:] == original

        with_system = [{"role": "system", "content": "Tools active"}, *original]
        merged = await augment_messages_with_memory(
            db, with_system, user_id=user.id, private_mode=False
        )
        assert merged[0]["role"] == "system"
        assert "Tools active" in merged[0]["content"]
        assert "Prefers dark mode" in merged[0]["content"]
        assert merged[1:] == original

        skipped = await augment_messages_with_memory(
            db, original, user_id=user.id, private_mode=True
        )
        assert skipped == original

        none_user = await augment_messages_with_memory(
            db, original, user_id=None, private_mode=False
        )
        assert none_user == original

        # Private source session rejected
        db.add(
            ChatSession(
                id="priv1",
                user_id=user.id,
                title="Private",
                model_id="m",
                private_mode=True,
            )
        )
        await db.commit()
        try:
            await create_memory(db, user.id, "Secret fact", source_session_id="priv1")
            assert False, "expected private session rejection"
        except MemoryValidationError:
            pass

        removed = await delete_all_memories(db, user.id)
        await db.commit()
        assert removed == 1
        assert await list_memories(db, user.id) == []

    await engine.dispose()


async def _cap_limit() -> None:
    engine, factory = await _make_session()
    async with factory() as db:
        user = await _add_user(db)
        for i in range(MAX_MEMORIES_PER_USER):
            await create_memory(db, user.id, f"Fact {i}")
        await db.commit()
        try:
            await create_memory(db, user.id, "One too many")
            assert False, "expected limit"
        except MemoryLimitError:
            pass
        count = len((await db.execute(select(UserMemory))).scalars().all())
        assert count == MAX_MEMORIES_PER_USER
    await engine.dispose()


def test_memory_crud_and_inject() -> None:
    asyncio.run(_crud_and_inject())


def test_memory_cap() -> None:
    asyncio.run(_cap_limit())


async def _private_mode_resolve() -> None:
    from app.services.proxy_service import _resolve_private_mode_for_memory

    engine, factory = await _make_session()
    async with factory() as db:
        user = await _add_user(db)
        db.add(
            ChatSession(
                id="pub1",
                user_id=user.id,
                title="Public",
                model_id="m",
                private_mode=False,
            )
        )
        db.add(
            ChatSession(
                id="priv2",
                user_id=user.id,
                title="Private",
                model_id="m",
                private_mode=True,
            )
        )
        await db.commit()

        assert await _resolve_private_mode_for_memory(
            db, {"private_mode": True}, user_id=user.id
        )
        assert not await _resolve_private_mode_for_memory(
            db, {"chat_session_id": "pub1"}, user_id=user.id
        )
        assert await _resolve_private_mode_for_memory(
            db, {"chat_session_id": "priv2"}, user_id=user.id
        )
        # Body flag wins even for public session id
        assert await _resolve_private_mode_for_memory(
            db, {"chat_session_id": "pub1", "private_mode": True}, user_id=user.id
        )
    await engine.dispose()


def test_resolve_private_mode_for_memory() -> None:
    asyncio.run(_private_mode_resolve())
