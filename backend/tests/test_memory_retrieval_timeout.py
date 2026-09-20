"""What the retrieval timeout is allowed to cancel.

``retrieval_timeout_ms`` exists for the embedding provider and the vector
store — the two things in a memory lookup that can hang. It used to wrap the
lexical query as well, which is an indexed read of the user's own rows on the
caller's session. Cancelling that mid-statement leaves the session in a failed
transaction, and the session does not belong to memory: budget settlement and
chat persistence run on it after this. So a slow vector store did not degrade
the memory block, it broke the whole turn.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
import app.services.user_memory_service as memory_service
from app.database import Base
from app.models.chat import UserMemory
from app.models.user import User
from app.services.user_memory_service import create_memory, retrieve_memories


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _seed(db: AsyncSession) -> User:
    user = User(username="slow", email="slow@alpha-router.local", hashed_password="x", auth_provider="local")
    db.add(user)
    await db.flush()
    await create_memory(db, user.id, "User prefers pizza for lunch", category="preference")
    await create_memory(db, user.id, "User drives a diesel van", category="other")
    await db.commit()
    return user


async def test_a_hanging_vector_store_costs_the_semantic_leg_and_nothing_else(monkeypatch) -> None:
    factory, engine = await _factory()
    async with factory() as db:
        user = await _seed(db)

        async def _hangs(*_args, **_kwargs):
            await asyncio.sleep(30)
            return []

        monkeypatch.setattr(memory_service, "_semantic_rows", _hangs)

        got = await retrieve_memories(db, user.id, query="what pizza should I order")

        # The lexical hit survives: it was fetched before the clock started.
        assert any("pizza" in item.content.lower() for item in got)

        # And the caller's session is still usable, which is the whole point.
        rows = (await db.execute(select(UserMemory).where(UserMemory.user_id == user.id))).scalars().all()
        assert len(rows) == 2
    await engine.dispose()


async def test_the_settings_are_read_once_per_lookup(monkeypatch) -> None:
    """The second read used to happen inside the cancellable region."""
    factory, engine = await _factory()
    async with factory() as db:
        user = await _seed(db)

        import app.services.memory_settings_service as settings_service

        calls = 0
        real = settings_service._load_raw

        async def counted(session):
            nonlocal calls
            calls += 1
            return await real(session)

        monkeypatch.setattr(settings_service, "_load_raw", counted)
        await retrieve_memories(db, user.id, query="pizza")
        assert calls == 1
    await engine.dispose()
