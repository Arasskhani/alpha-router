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

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import (
    ChatMessage,
    ChatSession,
    UserMemory,
    UserMemoryJob,
    UserMemorySuppression,
)
from app.models.system import SystemSetting
from app.models.user import User
from app.services.memory_extraction_service import (
    MemoryOperation,
    apply_memory_operations,
    handle_memory_extraction,
)
from app.services.user_chat_storage_service import save_user_prefs
from app.services.user_memory_service import create_memory, delete_all_memories, delete_memory


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


@pytest.fixture
async def seeded(db_session: AsyncSession) -> tuple[User, ChatSession, UserMemoryJob]:
    """A user mid-conversation with one extraction job claimed and running."""

    user = User(
        username="gatekeeper",
        email="gate@alpha-router.local",
        hashed_password="x",
        auth_provider="local",
    )
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(
        id="sess-gate",
        user_id=user.id,
        title="Chat",
        model_id="m",
        private_mode=False,
    )
    db_session.add(session)
    db_session.add(SystemSetting(key="memory_extraction_model_id", value="1"))
    await db_session.flush()
    now = dt.datetime.utcnow()
    for sequence, (role, content) in enumerate([("user", "I live in Tehran."), ("assistant", "Noted.")], start=1):
        db_session.add(
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
    db_session.add(job)
    await db_session.commit()
    return user, session, job


async def _alive(db: AsyncSession, user_id: int) -> list[str]:
    rows = (await db.execute(select(UserMemory).where(UserMemory.user_id == user_id))).scalars().all()
    return [row.content for row in rows]


async def test_queued_job_still_extracts_while_auto_capture_is_on(db_session, seeded) -> None:
    user, _session, job = seeded
    await handle_memory_extraction(db_session, job, completer=_completer)
    await db_session.commit()
    assert await _alive(db_session, user.id) == ["User lives in Tehran"]
    assert job.extracted_sequence == 2


async def test_job_queued_before_opting_out_writes_nothing(db_session, seeded) -> None:
    """The switch moved after the job was enqueued; the job must respect it."""
    user, _session, job = seeded
    await save_user_prefs(db_session, user.id, {"memory_auto_capture": False})
    await db_session.commit()

    await handle_memory_extraction(db_session, job, completer=_completer)
    await db_session.commit()

    assert await _alive(db_session, user.id) == []
    # The window is claimed rather than left open: turning the switch back on
    # must not retroactively mine the turns spoken while it was off.
    assert job.extracted_sequence == 2


async def test_turning_the_switch_back_on_does_not_mine_the_opted_out_window(db_session, seeded) -> None:
    user, _session, job = seeded
    await save_user_prefs(db_session, user.id, {"memory_auto_capture": False})
    await db_session.commit()
    await handle_memory_extraction(db_session, job, completer=_completer)
    await db_session.commit()

    await save_user_prefs(db_session, user.id, {"memory_auto_capture": True})
    job.status = "running"
    job.updated_at = dt.datetime.utcnow()
    await db_session.commit()

    # Same watermark, nothing new said: min_new keeps it inert.
    await handle_memory_extraction(db_session, job, completer=_completer)
    await db_session.commit()
    assert await _alive(db_session, user.id) == []


async def test_delete_all_during_a_claimed_job_wins(db_session, session_factory, seeded) -> None:
    """The person emptied the list while this job was already extracting."""
    user, _session, job = seeded

    async def _slow_completer(payload: dict) -> str:
        # Stand in for the model call: another connection runs delete-all and
        # commits while this job holds its window.
        async with session_factory() as other:
            await delete_all_memories(other, user.id)
            await other.commit()
        return await _completer(payload)

    await handle_memory_extraction(db_session, job, completer=_slow_completer)
    await db_session.commit()

    assert await _alive(db_session, user.id) == []


async def test_delete_all_keeps_earlier_one_by_one_suppressions(db_session, seeded) -> None:
    """Emptying the list must not revoke every "never learn this again"."""
    user, _session, _job = seeded
    payload, created = await create_memory(db_session, user.id, "User lives in Tehran", origin="auto")
    assert created
    await delete_memory(db_session, user.id, payload["id"])
    await db_session.commit()

    await delete_all_memories(db_session, user.id)
    await db_session.commit()

    suppressions = (
        (await db_session.execute(select(UserMemorySuppression).where(UserMemorySuppression.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(suppressions) == 1

    # And the block still bites: the same fact does not come back.
    result = await apply_memory_operations(
        db_session,
        user_id=user.id,
        session_id=None,
        operations=[
            MemoryOperation(
                op="add",
                content="User lives in Tehran",
                category="identity",
                confidence=0.9,
                salience=0.8,
            )
        ],
    )
    await db_session.commit()
    assert result.added == 0
    assert result.skipped == 1
    assert await _alive(db_session, user.id) == []
