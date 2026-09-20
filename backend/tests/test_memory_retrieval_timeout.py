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

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.user_memory_service as memory_service
from app.models.chat import UserMemory
from app.models.user import User
from app.services.user_memory_service import create_memory, retrieve_memories


@pytest.fixture
async def remembered(db_session: AsyncSession) -> User:
    user = User(username="slow", email="slow@alpha-router.local", hashed_password="x", auth_provider="local")
    db_session.add(user)
    await db_session.flush()
    await create_memory(db_session, user.id, "User prefers pizza for lunch", category="preference")
    await create_memory(db_session, user.id, "User drives a diesel van", category="other")
    await db_session.commit()
    return user


async def test_a_hanging_vector_store_costs_the_semantic_leg_and_nothing_else(
    db_session, remembered, monkeypatch
) -> None:
    async def _hangs(*_args, **_kwargs):
        await asyncio.sleep(30)
        return []

    monkeypatch.setattr(memory_service, "_semantic_rows", _hangs)

    got = await retrieve_memories(db_session, remembered.id, query="what pizza should I order")

    # The lexical hit survives: it was fetched before the clock started.
    assert any("pizza" in item.content.lower() for item in got)

    # And the caller's session is still usable, which is the whole point.
    rows = (await db_session.execute(select(UserMemory).where(UserMemory.user_id == remembered.id))).scalars().all()
    assert len(rows) == 2


async def test_the_settings_are_read_once_per_lookup(db_session, remembered, monkeypatch) -> None:
    """The second read used to happen inside the cancellable region."""
    import app.services.memory_settings_service as settings_service

    calls = 0
    real = settings_service._load_raw

    async def counted(session):
        nonlocal calls
        calls += 1
        return await real(session)

    monkeypatch.setattr(settings_service, "_load_raw", counted)
    await retrieve_memories(db_session, remembered.id, query="pizza")
    assert calls == 1
