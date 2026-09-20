"""A monthly ceiling on what automatic memory may spend.

Extraction is the one thing in Alpha Router that calls a provider with nobody
waiting on the answer. It is metered and attributed to the person whose memory
it is, but deliberately reserves no budget: a background job that starts
refusing to run is worse than one that costs a little. That reasoning is
sound per user and per turn, and stops being sound across a deployment, where
a bad month is only visible once it is billed.

Both scopes count against one figure, because they are one line item.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatMessage, ChatSession, UserMemory, UserMemoryJob
from app.models.cost_accounting import UsageOperation
from app.models.system import SystemSetting
from app.models.user import User
from app.services.memory_extraction_service import (
    extraction_budget_exhausted,
    extraction_spend_this_month,
    handle_memory_extraction,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _completer(_payload: dict) -> str:
    return json.dumps({"operations": [{"op": "add", "content": "User lives in Tehran", "category": "identity"}]})


def _spend(amount: float, *, operation_type: str = "memory_extract", when: dt.datetime | None = None):
    return UsageOperation(
        id=str(uuid.uuid4()),
        operation_type=operation_type,
        source="system_memory",
        status="succeeded",
        idempotency_key=str(uuid.uuid4()),
        total_cost_usd=amount,
        started_at=when or dt.datetime.utcnow(),
    )


async def _seed(db: AsyncSession, *, cap: str) -> tuple[User, UserMemoryJob]:
    user = User(username="payer", email="pay@alpha-router.local", hashed_password="x", auth_provider="local")
    db.add(user)
    await db.flush()
    session = ChatSession(id="sess-cap", user_id=user.id, title="Chat", model_id="m", private_mode=False)
    db.add(session)
    db.add(SystemSetting(key="memory_extraction_model_id", value="1"))
    db.add(SystemSetting(key="memory_extract_monthly_budget_usd", value=cap))
    now = dt.datetime.utcnow()
    for sequence, (role, content) in enumerate([("user", "I live in Tehran."), ("assistant", "Noted.")], start=1):
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session.id,
                role=role,
                content=content,
                sequence=sequence,
                created_at=now,
            )
        )
    job = UserMemoryJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        session_id=session.id,
        status="running",
        watermark_sequence=2,
        extracted_sequence=0,
        run_after=now,
        attempt_count=1,
        max_attempts=5,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    await db.commit()
    return user, job


async def _memories(db: AsyncSession, user_id: int) -> list[str]:
    rows = (await db.execute(select(UserMemory).where(UserMemory.user_id == user_id))).scalars().all()
    return [row.content for row in rows]


async def test_no_cap_means_no_cap() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, job = await _seed(db, cap="0")
        db.add(_spend(9_999))
        await db.commit()
        exhausted, _spent, _cap = await extraction_budget_exhausted(db)
        assert exhausted is False
        await handle_memory_extraction(db, job, completer=_completer)
        await db.commit()
        assert await _memories(db, user.id) == ["User lives in Tehran"]
    await engine.dispose()


async def test_extraction_stops_once_the_month_is_spent() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, job = await _seed(db, cap="5")
        db.add(_spend(5.25))
        await db.commit()

        await handle_memory_extraction(db, job, completer=_completer)
        await db.commit()

        assert await _memories(db, user.id) == []
        # Skipped, not dropped: the window is still open for next month.
        assert job.extracted_sequence == 0
    await engine.dispose()


async def test_the_two_scopes_share_one_figure() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, job = await _seed(db, cap="5")
        db.add(_spend(3, operation_type="memory_extract"))
        db.add(_spend(3, operation_type="project_memory_extract"))
        await db.commit()

        exhausted, spent, cap = await extraction_budget_exhausted(db)
        assert exhausted is True
        assert spent == 6.0
        assert cap == 5.0

        await handle_memory_extraction(db, job, completer=_completer)
        await db.commit()
        assert await _memories(db, user.id) == []
    await engine.dispose()


async def test_last_month_does_not_count_against_this_one() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, job = await _seed(db, cap="5")
        first_of_month = dt.datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        db.add(_spend(50, when=first_of_month - dt.timedelta(days=1)))
        await db.commit()

        assert await extraction_spend_this_month(db) == 0.0
        await handle_memory_extraction(db, job, completer=_completer)
        await db.commit()
        assert await _memories(db, user.id) == ["User lives in Tehran"]
    await engine.dispose()
