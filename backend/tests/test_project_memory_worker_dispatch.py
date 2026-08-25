"""project_memory.job.ready dispatch on the shared Knowledge worker."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from unittest.mock import patch

from qdrant_client import AsyncQdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatMessage, ChatSession, UserMemory
from app.models.knowledge import OutboxEvent
from app.models.project import (
    PROJECT_ROLE_PRIMARY_OWNER,
    Project,
    ProjectMember,
    ProjectMemory,
    ProjectMemoryJob,
)
from app.models.system import SystemSetting
from app.models.user import User
from app.services.knowledge_job_handlers import KnowledgeJobContext
from app.services.knowledge_queue import ensure_consumer_group, read_new_messages
from app.services.knowledge_worker_service import KnowledgeWorker
from app.services.outbox_service import relay_outbox_once
from app.services.project_memory_extraction_service import ProjectMemoryOperation
from app.services.project_memory_job_service import schedule_extraction
from app.services.qdrant_service import QdrantVectorService
from tests.test_memory_worker_dispatch import FakeRedis

PROJ_ID = "proj-worker"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _dispatch() -> None:
    factory, engine = await _session_factory()
    redis = FakeRedis()
    async with factory() as db:
        owner = User(
            username="proj_worker_owner",
            email="proj_worker_owner@alpha-router.local",
            hashed_password="x",
            auth_provider="local",
        )
        db.add(owner)
        await db.flush()
        db.add(
            Project(
                id=PROJ_ID,
                name="Worker",
                status="active",
                visibility="private",
                created_by_user_id=owner.id,
                revision=1,
                acl_version=1,
            )
        )
        db.add(
            ProjectMember(
                project_id=PROJ_ID, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER
            )
        )
        session = ChatSession(
            id="sess-proj-worker",
            user_id=owner.id,
            title="Kickoff",
            model_id="m",
            private_mode=False,
            project_id=PROJ_ID,
            channel_kind="ai",
        )
        db.add(session)
        db.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        for seq, role, text in (
            (1, "user", "We standardised on trunk-based development."),
            (2, "assistant", "Noted."),
        ):
            db.add(
                ChatMessage(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    user_id=owner.id if role == "user" else None,
                    role=role,
                    content=text,
                    sequence=seq,
                    author_display_name="Sara" if role == "user" else None,
                )
            )
        job = await schedule_extraction(
            db, project_id=PROJ_ID, session_id=session.id, watermark_sequence=2
        )
        assert job is not None
        past = dt.datetime.utcnow() - dt.timedelta(seconds=1)
        job.run_after = past
        outbox = (
            await db.execute(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "project_memory.job.ready"
                )
            )
        ).scalar_one()
        outbox.available_at = past
        await db.commit()
        job_id = job.id

    await relay_outbox_once(factory, redis, worker_id="scheduler-1")
    await ensure_consumer_group(redis)
    messages = await read_new_messages(redis, consumer_name="worker-1")
    assert {message.event_type for message in messages} == {
        "project_memory.job.ready"
    }

    async def fake_extract(db, *, window, completer=None):
        del db, completer
        assert window.project_id == PROJ_ID
        return (
            [
                ProjectMemoryOperation(
                    op="add",
                    content="The team uses trunk-based development",
                    category="convention",
                    salience=0.7,
                )
            ],
            0,
        )

    qdrant = QdrantVectorService(AsyncQdrantClient(location=":memory:"))
    worker = KnowledgeWorker(
        session_factory=factory,
        redis=redis,
        consumer_name="worker-1",
        context=KnowledgeJobContext(qdrant=qdrant),
    )
    with patch(
        "app.services.project_memory_extraction_service."
        "extract_project_memory_operations",
        fake_extract,
    ):
        results = [await worker.process_message(message) for message in messages]
    assert [result.outcome for result in results] == ["succeeded"]
    assert len(redis.acked) == 1

    async with factory() as db:
        persisted = await db.get(ProjectMemoryJob, job_id)
        assert persisted.status == "succeeded"
        assert persisted.extracted_sequence == 2
        rows = (
            await db.execute(
                select(ProjectMemory).where(ProjectMemory.project_id == PROJ_ID)
            )
        ).scalars().all()
        assert [row.content for row in rows] == [
            "The team uses trunk-based development"
        ]
        assert rows[0].source_type == "auto_chat"
        assert rows[0].category == "convention"
        # Nothing leaked into personal memory.
        assert (await db.execute(select(UserMemory))).scalars().all() == []

    await qdrant.close()
    await engine.dispose()


def test_project_memory_job_dispatches_on_shared_worker() -> None:
    asyncio.run(_dispatch())
