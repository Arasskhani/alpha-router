"""Debounced memory extraction jobs, retry, lease recovery, watermarks."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatMessage, ChatSession, UserMemoryJob
from app.models.knowledge import OutboxEvent
from app.models.system import SystemSetting
from app.models.user import User
from app.services.memory_job_service import (
    claim_job,
    complete_job,
    fail_job,
    recover_stale_jobs,
    reset_watermarks_for_user,
    schedule_extraction,
)
from app.services.user_memory_service import create_memory, delete_all_memories


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _seed_user_session(db: AsyncSession) -> tuple[User, ChatSession]:
    user = User(
        username="jobber",
        email="jobber@alpha-router.local",
        hashed_password="x",
        auth_provider="local",
    )
    db.add(user)
    await db.flush()
    session = ChatSession(
        id="sess-job",
        user_id=user.id,
        title="Work",
        model_id="m",
        private_mode=False,
    )
    db.add(session)
    db.add(SystemSetting(key="memory_extraction_model_id", value="1"))
    db.add(SystemSetting(key="memory_extract_debounce_seconds", value="30"))
    await db.commit()
    return user, session


async def _coalesce_retry_recover() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, session = await _seed_user_session(db)
        first = await schedule_extraction(
            db, user_id=user.id, session_id=session.id, watermark_sequence=2
        )
        assert first is not None
        first_id = first.id
        first_run = first.run_after
        second = await schedule_extraction(
            db, user_id=user.id, session_id=session.id, watermark_sequence=5
        )
        await db.commit()
        assert second is not None
        assert second.id == first_id
        assert second.watermark_sequence == 5
        assert second.run_after >= first_run
        open_jobs = (
            await db.execute(
                select(UserMemoryJob).where(
                    UserMemoryJob.user_id == user.id,
                    UserMemoryJob.status.in_(("pending", "retry")),
                )
            )
        ).scalars().all()
        assert len(open_jobs) == 1
        events = (await db.execute(select(OutboxEvent))).scalars().all()
        assert any(event.event_type == "memory.job.ready" for event in events)

        job = await db.get(UserMemoryJob, first_id)
        job.run_after = dt.datetime.utcnow() - dt.timedelta(seconds=1)
        await db.flush()
        claimed = await claim_job(db, job_id=first_id, worker_id="w1")
        assert claimed is not None
        assert claimed.status == "running"
        assert claimed.attempt_count == 1

        dup = await claim_job(db, job_id=first_id, worker_id="w2")
        assert dup is None

        result = await fail_job(
            db, claimed, worker_id="w1", error="boom", retryable=True
        )
        await db.commit()
        assert result.status == "retry"
        assert result.next_attempt_at is not None

        retry_row = await db.get(UserMemoryJob, first_id)
        retry_row.run_after = dt.datetime.utcnow() - dt.timedelta(seconds=1)
        retry_row.max_attempts = 2
        await db.flush()
        claimed2 = await claim_job(db, job_id=first_id, worker_id="w1")
        assert claimed2 is not None
        dead = await fail_job(
            db, claimed2, worker_id="w1", error="still boom", retryable=True
        )
        await db.commit()
        assert dead.status == "dead"

        stale = UserMemoryJob(
            id=str(uuid.uuid4()),
            user_id=user.id,
            session_id=session.id,
            status="running",
            watermark_sequence=8,
            extracted_sequence=5,
            run_after=dt.datetime.utcnow(),
            attempt_count=1,
            max_attempts=5,
            lease_expires_at=dt.datetime.utcnow() - dt.timedelta(seconds=5),
            worker_id="crashed",
            created_at=dt.datetime.utcnow(),
            updated_at=dt.datetime.utcnow(),
        )
        db.add(stale)
        await db.commit()
        recovered = await recover_stale_jobs(db)
        await db.commit()
        assert recovered == 1
        refreshed = await db.get(UserMemoryJob, stale.id)
        assert refreshed.status == "retry"
        assert refreshed.worker_id is None

        private = ChatSession(
            id="sess-priv",
            user_id=user.id,
            title="Secret",
            model_id="m",
            private_mode=True,
        )
        db.add(private)
        await db.commit()
        skipped = await schedule_extraction(
            db, user_id=user.id, session_id=private.id, watermark_sequence=2
        )
        assert skipped is None
    await engine.dispose()


async def _watermark_reset() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, session = await _seed_user_session(db)
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=user.id,
                role="user",
                content="hello",
                sequence=1,
            )
        )
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=user.id,
                role="assistant",
                content="hi",
                sequence=2,
            )
        )
        job = await schedule_extraction(
            db, user_id=user.id, session_id=session.id, watermark_sequence=2
        )
        await create_memory(db, user.id, "Something durable")
        await db.commit()
        assert job is not None
        assert job.extracted_sequence == 0
        await delete_all_memories(db, user.id)
        await db.commit()
        refreshed = await db.get(UserMemoryJob, job.id)
        assert refreshed.extracted_sequence >= 2
        assert refreshed.status == "succeeded"
    await engine.dispose()


async def _complete_job_happy_path() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user, session = await _seed_user_session(db)
        job = await schedule_extraction(
            db, user_id=user.id, session_id=session.id, watermark_sequence=4
        )
        job.run_after = dt.datetime.utcnow() - dt.timedelta(seconds=1)
        await db.flush()
        claimed = await claim_job(db, job_id=job.id, worker_id="w1")
        assert claimed is not None
        ok = await complete_job(
            db, claimed, worker_id="w1", extracted_sequence=4
        )
        await db.commit()
        assert ok is True
        done = await db.get(UserMemoryJob, job.id)
        assert done.status == "succeeded"
        assert done.extracted_sequence == 4
    await engine.dispose()


async def _race_keeps_caller_transaction_usable() -> None:
    """A lost race on the open-job unique index must not poison the caller's tx."""
    factory, engine = await _session_factory()
    async with factory() as db:
        user, session = await _seed_user_session(db)
        winner = await schedule_extraction(
            db, user_id=user.id, session_id=session.id, watermark_sequence=2
        )
        await db.commit()
        assert winner is not None

        # Simulate the race window: insert directly, skipping the coalesce lookup.
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session.id,
                user_id=user.id,
                role="user",
                content="still chatting",
                sequence=3,
            )
        )
        raced = UserMemoryJob(
            id=str(uuid.uuid4()),
            user_id=user.id,
            session_id=session.id,
            status="pending",
            watermark_sequence=3,
            extracted_sequence=0,
            run_after=dt.datetime.utcnow(),
            attempt_count=0,
            max_attempts=5,
            created_at=dt.datetime.utcnow(),
            updated_at=dt.datetime.utcnow(),
        )
        try:
            async with db.begin_nested():
                db.add(raced)
                await db.flush()
            raise AssertionError("expected the partial unique index to reject the row")
        except IntegrityError:
            pass

        # The savepoint rollback leaves the outer transaction writable.
        again = await schedule_extraction(
            db, user_id=user.id, session_id=session.id, watermark_sequence=3
        )
        await db.commit()
        assert again is not None
        assert again.id == winner.id
        assert again.watermark_sequence == 3
        persisted = (
            await db.execute(
                select(ChatMessage).where(ChatMessage.session_id == session.id)
            )
        ).scalars().all()
        assert [row.sequence for row in persisted] == [3]
    await engine.dispose()


def test_memory_job_coalesce_retry_and_lease_recovery() -> None:
    asyncio.run(_coalesce_retry_recover())


def test_open_job_race_does_not_poison_caller_transaction() -> None:
    asyncio.run(_race_keeps_caller_transaction_usable())


def test_delete_all_resets_watermarks() -> None:
    asyncio.run(_watermark_reset())


def test_memory_job_complete() -> None:
    asyncio.run(_complete_job_happy_path())
