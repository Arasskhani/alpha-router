"""Phase 4: streaming message persistence must survive DB rollbacks.

When ``on_content`` raises mid-stream and the caller rolls the session back,
the previously-flushed assistant content is reverted in the DB. The persister
must reset its incremental counters so the next flush re-writes the full
accumulated content; otherwise the stored message gets stuck at the
pre-rollback (shorter) content. ``finalize`` must also guarantee the final
content is written even after a rollback.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.chat_completion_persistence import ChatCompletionPersister
from app.services.user_chat_storage_service import (
    create_chat_session,
    list_session_messages,
)


def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _bootstrap_user_and_session(factory):
    async with factory() as db:
        db.add(
            User(
                username="corrupt",
                email="corrupt@test",
                hashed_password="x",
                auth_provider="local",
            )
        )
        await db.commit()
        user = (await db.execute(select(User))).scalar_one()
        await create_chat_session(db, user.id, {"id": "s1", "title": "T", "model": "m"})
        await db.commit()
    return user.id


async def _read_last_assistant(factory, user_id, session_id):
    async with factory() as db:
        msgs, _ = await list_session_messages(db, user_id, session_id)
        asst = [m for m in msgs if m["role"] == "assistant"]
        return asst[-1]["content"] if asst else None


async def _test_reset_persist_state_resets_counters() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    uid = await _bootstrap_user_and_session(factory)
    async with factory() as db:
        p = ChatCompletionPersister(db, user_id=uid, session_id="s1", model_id="m", model_name="M")
        await p.prepare()
        await p.on_content("Hello world this is long enough to flush")
        assert p._last_persist_len > 0
        p.reset_persist_state()
        assert p._last_persist_len == 0
        assert p._last_persist_at == 0.0
    await engine.dispose()


async def _test_finalize_writes_full_content_after_rollback() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    uid = await _bootstrap_user_and_session(factory)
    async with factory() as db:
        p = ChatCompletionPersister(
            db,
            user_id=uid,
            session_id="s1",
            model_id="m",
            model_name="M",
            user_message={"role": "user", "content": "Hi", "clientMessageId": "u1"},
            assistant_client_message_id="a1",
        )
        await p.prepare()
        # Simulate a successful partial flush, then a rollback (as happens when
        # on_content raises in stream_chat). The rollback reverts the stored
        # content to the empty placeholder.
        await p.on_content("Partial content that is long enough to flush once")
        await db.rollback()
        p.reset_persist_state()

        # Continue streaming more content.
        await p.on_content("Partial content that is long enough to flush once plus more text")
        await p.finalize(success=True)

    final = await _read_last_assistant(factory, uid, "s1")
    assert final is not None
    assert "plus more text" in final
    assert final.startswith("Partial content")
    await engine.dispose()


async def _test_on_content_does_not_skip_after_reset() -> None:
    """After reset_persist_state, a short delta must still flush (counters are 0)."""
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    uid = await _bootstrap_user_and_session(factory)
    async with factory() as db:
        p = ChatCompletionPersister(
            db, user_id=uid, session_id="s1", model_id="m", model_name="M",
            assistant_client_message_id="a2",
        )
        await p.prepare()
        # Long content to trigger a flush, then rollback + reset.
        long = "x" * 200
        await p.on_content(long)
        await db.rollback()
        p.reset_persist_state()
        # A short additional delta — without reset this would be skipped because
        # delta_chars < MIN and interval not elapsed. With reset, _last_persist_len
        # is 0 so delta_chars is large and it flushes.
        await p.on_content(long + "Y")
        await p.finalize(success=True)
    final = await _read_last_assistant(factory, uid, "s1")
    assert final is not None
    assert final.endswith("Y")
    await engine.dispose()


async def _test_finalize_on_failure_writes_error_message() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    uid = await _bootstrap_user_and_session(factory)
    async with factory() as db:
        p = ChatCompletionPersister(
            db, user_id=uid, session_id="s1", model_id="m", model_name="M",
            assistant_client_message_id="a3",
        )
        await p.prepare()
        await p.on_content("Some partial reply that is long enough to flush")
        await db.rollback()
        p.reset_persist_state()
        await p.finalize(success=False, error_message="upstream timeout")
    final = await _read_last_assistant(factory, uid, "s1")
    assert final is not None
    assert "Error: upstream timeout" in final
    await engine.dispose()


def test_reset_persist_state_resets_counters():
    asyncio.run(_test_reset_persist_state_resets_counters())


def test_finalize_writes_full_content_after_rollback():
    asyncio.run(_test_finalize_writes_full_content_after_rollback())


def test_on_content_does_not_skip_after_reset():
    asyncio.run(_test_on_content_does_not_skip_after_reset())


def test_finalize_on_failure_writes_error_message():
    asyncio.run(_test_finalize_on_failure_writes_error_message())
