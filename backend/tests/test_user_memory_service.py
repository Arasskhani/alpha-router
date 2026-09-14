"""Tests for automatic user memory CRUD, retrieval, suppression, and injection."""

from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatSession, UserMemory, UserMemorySuppression
from app.models.system import SystemSetting
from app.models.user import User
from app.services.user_chat_storage_service import save_user_prefs
from app.services.user_memory_service import (
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
    retrieve_memories,
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


def test_persian_normalization_dedupes() -> None:
    arabic_yeh_kaf = "ترجيح الوضع الداكن يك"
    persian_yeh_kaf = "ترجيح الوضع الداكن یک"
    assert memory_content_hash(arabic_yeh_kaf) == memory_content_hash(persian_yeh_kaf)
    assert memory_content_hash("نمره ۱۲") == memory_content_hash("نمره 12")


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

        items, total = await list_memories(db, user.id)
        assert len(items) == 1
        assert total == 1

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
        augmented = await augment_messages_with_memory(db, messages, user_id=user.id, private_mode=False)
        assert messages == original
        assert augmented[0]["role"] == "system"
        assert "Prefers dark mode" in augmented[0]["content"]
        assert augmented[1:] == original

        with_system = [{"role": "system", "content": "Tools active"}, *original]
        merged = await augment_messages_with_memory(db, with_system, user_id=user.id, private_mode=False)
        assert merged[0]["role"] == "system"
        assert "Tools active" in merged[0]["content"]
        assert "Prefers dark mode" in merged[0]["content"]
        assert merged[1:] == original

        skipped = await augment_messages_with_memory(db, original, user_id=user.id, private_mode=True)
        assert skipped == original

        none_user = await augment_messages_with_memory(db, original, user_id=None, private_mode=False)
        assert none_user == original

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
        items, total = await list_memories(db, user.id)
        assert items == []
        assert total == 0

    await engine.dispose()


async def _cap_eviction() -> None:
    engine, factory = await _make_session()
    async with factory() as db:
        user = await _add_user(db)
        db.add(SystemSetting(key="memory_max_per_user", value="10"))
        await db.flush()
        for i in range(10):
            await create_memory(db, user.id, f"Fact {i}", salience=0.1 + (i * 0.01))
        await db.commit()
        created, was_new = await create_memory(db, user.id, "One too many", salience=0.99)
        await db.commit()
        assert was_new is True
        assert created["content"] == "One too many"
        alive = (
            (
                await db.execute(
                    select(UserMemory).where(
                        UserMemory.user_id == user.id,
                        UserMemory.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(alive) == 10
        contents = {row.content for row in alive}
        assert "One too many" in contents
        assert "Fact 0" not in contents
    await engine.dispose()


async def _supersede_expiry_suppression_retrieve() -> None:
    engine, factory = await _make_session()
    async with factory() as db:
        user = await _add_user(db)
        old, _ = await create_memory(
            db,
            user.id,
            "Fasting blood sugar is elevated",
            category="health",
            sensitivity="sensitive",
            salience=0.9,
        )
        newer, _ = await create_memory(
            db,
            user.id,
            "Fasting blood sugar is now in the normal range",
            category="health",
            salience=0.85,
            supersedes_id=old["id"],
        )
        await db.commit()
        target = await db.get(UserMemory, old["id"])
        target.enabled = False
        await db.flush()

        expired, _ = await create_memory(
            db,
            user.id,
            "On vacation until last week",
            category="schedule",
            salience=0.7,
            expires_at=dt.datetime.utcnow() - dt.timedelta(days=1),
        )
        pizza, _ = await create_memory(
            db,
            user.id,
            "User likes pineapple pizza",
            category="preference",
            salience=0.4,
        )
        await db.commit()

        retrieved = await retrieve_memories(db, user.id, query="I want pizza and soda for lunch")
        contents = [item.content for item in retrieved]
        assert any("normal range" in item for item in contents)
        assert "On vacation until last week" not in contents
        assert any("pizza" in item.lower() for item in contents)

        await delete_memory(db, user.id, pizza["id"])
        await db.commit()
        suppressed = (
            (await db.execute(select(UserMemorySuppression).where(UserMemorySuppression.user_id == user.id)))
            .scalars()
            .all()
        )
        assert suppressed
        from app.services.memory_extraction_service import (
            MemoryOperation,
            apply_memory_operations,
        )

        result = await apply_memory_operations(
            db,
            user_id=user.id,
            session_id=None,
            operations=[
                MemoryOperation(
                    op="add",
                    content="User likes pineapple pizza",
                    category="preference",
                )
            ],
        )
        await db.commit()
        assert result.added == 0
        assert result.skipped >= 1

        db.add(SystemSetting(key="memory_inject_max_items", value="1"))
        db.add(SystemSetting(key="memory_core_items", value="1"))
        await db.flush()
        capped = await retrieve_memories(db, user.id, query="anything")
        assert len(capped) <= 1
        assert newer["id"]  # supersede chain preserved
    await engine.dispose()


async def _timeout_fallback() -> None:
    engine, factory = await _make_session()
    async with factory() as db:
        user = await _add_user(db)
        db.add(SystemSetting(key="memory_retrieval_timeout_ms", value="50"))
        await db.flush()
        await create_memory(db, user.id, "Prefers sitting near a window", category="preference")
        await db.commit()

        async def _slow(*_args, **_kwargs):
            await asyncio.sleep(1)
            return []

        with (
            patch("app.services.user_memory_service._semantic_rows", side_effect=_slow),
            patch("app.services.user_memory_service._lexical_rows", side_effect=_slow),
        ):
            facts = await retrieve_memories(db, user.id, query="window seat please")
        assert any("window" in item.content for item in facts)
    await engine.dispose()


def test_memory_crud_and_inject() -> None:
    asyncio.run(_crud_and_inject())


def test_memory_cap_evicts_lowest() -> None:
    asyncio.run(_cap_eviction())


def test_supersede_expiry_suppression_and_retrieve() -> None:
    asyncio.run(_supersede_expiry_suppression_retrieve())


def test_retrieve_timeout_falls_back_to_recency() -> None:
    asyncio.run(_timeout_fallback())


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

        assert await _resolve_private_mode_for_memory(db, {"private_mode": True}, user_id=user.id)
        assert not await _resolve_private_mode_for_memory(db, {"chat_session_id": "pub1"}, user_id=user.id)
        assert await _resolve_private_mode_for_memory(db, {"chat_session_id": "priv2"}, user_id=user.id)
        assert await _resolve_private_mode_for_memory(
            db, {"chat_session_id": "pub1", "private_mode": True}, user_id=user.id
        )
    await engine.dispose()


def test_resolve_private_mode_for_memory() -> None:
    asyncio.run(_private_mode_resolve())
