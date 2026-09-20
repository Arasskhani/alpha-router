"""The gates handle_memory_extraction applies before it writes anything.

schedule_extraction already refuses to enqueue a job when the person has
automatic learning switched off. That check alone is not enough: a job waits
out a debounce of up to ``extract_max_wait_seconds`` and can be retried after
that, so the switch can move while the job is already in the queue. These
tests pin the behaviour at the point where memories are actually written.
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
from app.models.system import SystemSetting
from app.models.user import User
from app.services.memory_extraction_service import handle_memory_extraction
from app.services.user_chat_storage_service import save_user_prefs
from app.services.user_memory_service import delete_all_memories


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _completer(_payload: dict) -> str:
    return json.dumps(
        {
            "operations": [
                {
                    "op": "add",
                    "content": "User lives in Tehran",
                    "category": "identity",
                    "confidence": 0.9,
                    "salience": 0.8,
                }
            ]
        }
    )


async def _seed(db: AsyncSession) -> tuple[User, ChatSession, UserMemoryJob]:
    user = User(
        username="gatekeeper",
        email="gate@alpha-router.local",
        hashed_password="x",
        auth_provider="local",
    )
    db.add(user)
    await db.flush()
    session = ChatSession(
        id="sess-gate",
        user_id=user.id,
        title="Chat",
        model_id="m",
        private_mode=False,
    )
    db.add(session)
    db.add(SystemSetting(key="memory_extraction_model_id", value="1"))
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
    return user, session, job


async def _alive(db: AsyncSession, user_id: int) -> list[str]:
    rows = (await db.execute(select(UserMemory).where(UserMemory.user_id == user_id))).scalars().all()
    return [row.content for row in rows]


async def test_queued_job_still_extracts_while_auto_capture_is_on() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, _session, job = await _seed(db)
        await handle_memory_extraction(db, job, completer=_completer)
        await db.commit()
        assert await _alive(db, user.id) == ["User lives in Tehran"]
        assert job.extracted_sequence == 2
    await engine.dispose()


async def test_job_queued_before_opting_out_writes_nothing() -> None:
    """The switch moved after the job was enqueued; the job must respect it."""
    factory, engine = await _session_factory()
    async with factory() as db:
        user, _session, job = await _seed(db)
        await save_user_prefs(db, user.id, {"memory_auto_capture": False})
        await db.commit()

        await handle_memory_extraction(db, job, completer=_completer)
        await db.commit()

        assert await _alive(db, user.id) == []
        # The window is claimed rather than left open: turning the switch back
        # on must not retroactively mine the turns spoken while it was off.
        assert job.extracted_sequence == 2
    await engine.dispose()


async def test_turning_the_switch_back_on_does_not_mine_the_opted_out_window() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, session, job = await _seed(db)
        await save_user_prefs(db, user.id, {"memory_auto_capture": False})
        await db.commit()
        await handle_memory_extraction(db, job, completer=_completer)
        await db.commit()

        await save_user_prefs(db, user.id, {"memory_auto_capture": True})
        job.status = "running"
        job.updated_at = dt.datetime.utcnow()
        await db.commit()

        # Same watermark, nothing new said: min_new keeps it inert.
        await handle_memory_extraction(db, job, completer=_completer)
        await db.commit()
        assert await _alive(db, user.id) == []
        assert session.id == "sess-gate"
    await engine.dispose()


async def test_delete_all_during_a_claimed_job_wins() -> None:
    """The person emptied the list while this job was already extracting."""
    factory, engine = await _session_factory()
    async with factory() as db:
        user, _session, job = await _seed(db)

        async def _slow_completer(payload: dict) -> str:
            # Stand in for the model call: a second connection runs delete-all
            # and commits while this job holds its window.
            async with factory() as other:
                await delete_all_memories(other, user.id)
                await other.commit()
            return await _completer(payload)

        await handle_memory_extraction(db, job, completer=_slow_completer)
        await db.commit()

        assert await _alive(db, user.id) == []
    await engine.dispose()
