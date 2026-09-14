"""Project memory job scheduling: coalescing, eligibility, and personal isolation."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatMessage, ChatSession, UserMemoryJob
from app.models.knowledge import OutboxEvent
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    Project,
    ProjectMember,
    ProjectMemory,
    ProjectMemoryJob,
)
from app.models.system import SystemSetting
from app.models.user import User
from app.services.memory_job_service import (
    schedule_extraction as schedule_user_extraction,
)
from app.services.project_memory_job_service import (
    claim_job,
    complete_job,
    recover_stale_jobs,
    schedule_extraction,
)
from app.services.project_memory_service import (
    create_auto_project_memory,
    create_project_memory,
    delete_all_auto_project_memories,
)

PROJ_ID = "proj-mem-jobs"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db: AsyncSession, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@alpha-router.local",
        hashed_password="x",
        auth_provider="local",
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_project(db: AsyncSession) -> tuple[User, User, ChatSession]:
    owner = await _user(db, "proj_owner")
    member = await _user(db, "proj_member")
    db.add(
        Project(
            id=PROJ_ID,
            name="Billing revamp",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ_ID, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=PROJ_ID, user_id=member.id, role=PROJECT_ROLE_CONTRIBUTOR))
    session = ChatSession(
        id="sess-proj-ai",
        user_id=owner.id,
        title="Kickoff",
        model_id="m",
        private_mode=False,
        project_id=PROJ_ID,
        channel_kind="ai",
    )
    db.add(session)
    db.add(SystemSetting(key="memory_extraction_model_id", value="1"))
    db.add(SystemSetting(key="project_memory_extract_debounce_seconds", value="45"))
    await db.flush()
    return owner, member, session


async def _two_members_coalesce_into_one_job() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, member, session = await _seed_project(db)
        first = await schedule_extraction(db, project_id=PROJ_ID, session_id=session.id, watermark_sequence=2)
        assert first is not None
        # The second member posts into the same thread moments later.
        second = await schedule_extraction(db, project_id=PROJ_ID, session_id=session.id, watermark_sequence=6)
        await db.commit()
        assert second is not None
        assert second.id == first.id
        assert second.watermark_sequence == 6

        open_jobs = (
            (
                await db.execute(
                    select(ProjectMemoryJob).where(
                        ProjectMemoryJob.project_id == PROJ_ID,
                        ProjectMemoryJob.status.in_(("pending", "retry")),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(open_jobs) == 1
        events = (await db.execute(select(OutboxEvent))).scalars().all()
        ready = [e for e in events if e.event_type == "project_memory.job.ready"]
        assert len(ready) == 1

        # No personal job was created for either member.
        user_jobs = (await db.execute(select(UserMemoryJob))).scalars().all()
        assert user_jobs == []
        del owner, member
    await engine.dispose()


async def _project_chat_never_schedules_personal_job() -> None:
    """Regression: the session creator's project chat must not feed personal memory."""
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, _member, session = await _seed_project(db)
        leaked = await schedule_user_extraction(db, user_id=owner.id, session_id=session.id, watermark_sequence=2)
        await db.commit()
        assert leaked is None
        assert (await db.execute(select(UserMemoryJob))).scalars().all() == []
    await engine.dispose()


async def _ineligible_sessions_are_skipped() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, _member, _session = await _seed_project(db)
        room = ChatSession(
            id="sess-proj-room",
            user_id=owner.id,
            title="Room",
            model_id="m",
            private_mode=False,
            project_id=PROJ_ID,
            channel_kind="member",
        )
        private = ChatSession(
            id="sess-proj-private",
            user_id=owner.id,
            title="Private",
            model_id="m",
            private_mode=True,
            project_id=PROJ_ID,
            channel_kind="ai",
        )
        personal = ChatSession(
            id="sess-personal",
            user_id=owner.id,
            title="Personal",
            model_id="m",
            private_mode=False,
        )
        db.add_all([room, private, personal])
        await db.flush()
        for session_id in (room.id, private.id, personal.id):
            assert (
                await schedule_extraction(
                    db,
                    project_id=PROJ_ID,
                    session_id=session_id,
                    watermark_sequence=4,
                )
                is None
            )
        await db.commit()
        assert (await db.execute(select(ProjectMemoryJob))).scalars().all() == []
    await engine.dispose()


async def _auto_capture_off_stops_scheduling() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, _member, session = await _seed_project(db)
        from app.services.project_config_service import update_project_config

        await update_project_config(
            db,
            project_id=PROJ_ID,
            user=owner,
            memory_enabled=True,
            memory_auto_capture=False,
        )
        await db.flush()
        assert (
            await schedule_extraction(
                db,
                project_id=PROJ_ID,
                session_id=session.id,
                watermark_sequence=4,
            )
            is None
        )
        await db.commit()
        assert (await db.execute(select(ProjectMemoryJob))).scalars().all() == []
    await engine.dispose()


async def _lease_recovery_and_completion() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        _owner, _member, session = await _seed_project(db)
        job = await schedule_extraction(db, project_id=PROJ_ID, session_id=session.id, watermark_sequence=4)
        assert job is not None
        job.run_after = dt.datetime.utcnow() - dt.timedelta(seconds=1)
        await db.flush()
        claimed = await claim_job(db, job_id=job.id, worker_id="w1")
        assert claimed is not None
        assert await claim_job(db, job_id=job.id, worker_id="w2") is None
        claimed.lease_expires_at = dt.datetime.utcnow() - dt.timedelta(seconds=5)
        await db.flush()
        assert await recover_stale_jobs(db) == 1
        revived = await db.get(ProjectMemoryJob, job.id)
        assert revived.status == "retry"
        assert revived.worker_id is None
        revived.run_after = dt.datetime.utcnow() - dt.timedelta(seconds=1)
        await db.flush()
        again = await claim_job(db, job_id=job.id, worker_id="w1")
        assert again is not None
        assert await complete_job(db, again, worker_id="w1", extracted_sequence=4)
        await db.commit()
        done = await db.get(ProjectMemoryJob, job.id)
        assert done.status == "succeeded"
        assert done.extracted_sequence == 4
    await engine.dispose()


async def _delete_all_auto_resets_watermarks_and_keeps_manual() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, _member, session = await _seed_project(db)
        for seq, role in ((1, "user"), (2, "assistant"), (3, "user")):
            db.add(
                ChatMessage(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    user_id=owner.id,
                    role=role,
                    content=f"turn {seq}",
                    sequence=seq,
                )
            )
        await create_project_memory(db, project_id=PROJ_ID, user=owner, content="Owner-authored fact")
        learned, created = await create_auto_project_memory(
            db,
            project_id=PROJ_ID,
            content="The team ships on Fridays",
            session_id=session.id,
            message_id=None,
            author_user_id=owner.id,
            category="convention",
        )
        assert created is True
        job = await schedule_extraction(db, project_id=PROJ_ID, session_id=session.id, watermark_sequence=3)
        assert job is not None
        await db.commit()

        deleted = await delete_all_auto_project_memories(db, project_id=PROJ_ID, user=owner)
        await db.commit()
        assert deleted == 1
        assert await db.get(ProjectMemory, learned.id) is None
        remaining = (await db.execute(select(ProjectMemory).where(ProjectMemory.project_id == PROJ_ID))).scalars().all()
        assert [row.content for row in remaining] == ["Owner-authored fact"]
        # The old thread must not be mined again into the same facts.
        refreshed = await db.get(ProjectMemoryJob, job.id)
        assert refreshed.status == "succeeded"
        assert refreshed.extracted_sequence >= 3
    await engine.dispose()


def test_two_members_coalesce_into_one_project_job() -> None:
    asyncio.run(_two_members_coalesce_into_one_job())


def test_project_chat_never_schedules_a_personal_memory_job() -> None:
    asyncio.run(_project_chat_never_schedules_personal_job())


def test_rooms_private_and_personal_sessions_are_not_mined() -> None:
    asyncio.run(_ineligible_sessions_are_skipped())


def test_auto_capture_disabled_stops_project_scheduling() -> None:
    asyncio.run(_auto_capture_off_stops_scheduling())


def test_project_job_lease_recovery_and_completion() -> None:
    asyncio.run(_lease_recovery_and_completion())


def test_delete_all_learned_facts_resets_watermarks() -> None:
    asyncio.run(_delete_all_auto_resets_watermarks_and_keeps_manual())
