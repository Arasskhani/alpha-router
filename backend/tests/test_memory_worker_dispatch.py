"""End-to-end memory.job.ready dispatch on the shared Knowledge worker."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from unittest.mock import patch

from redis.exceptions import ResponseError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from qdrant_client import AsyncQdrantClient

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatMessage, ChatSession, UserMemory, UserMemoryJob
from app.models.knowledge import IngestionJob, KnowledgeBase, OutboxEvent
from app.models.system import SystemSetting
from app.models.user import User
from app.services.knowledge_job_handlers import KnowledgeJobContext
from app.services.knowledge_job_service import enqueue_knowledge_job
from app.services.knowledge_queue import ensure_consumer_group, read_new_messages
from app.services.knowledge_worker_service import KnowledgeWorker
from app.services.memory_extraction_service import MemoryOperation
from app.services.memory_job_service import schedule_extraction
from app.services.outbox_service import relay_outbox_once
from app.services.qdrant_service import QdrantVectorService


class FakeRedis:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, str]]] = []
        self.dead_letters: list[tuple[str, dict[str, str]]] = []
        self.acked: list[str] = []
        self.group_created = False
        self.delivered: set[str] = set()

    async def xgroup_create(self, stream, group, id, mkstream):
        del stream, group, id, mkstream
        if self.group_created:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.group_created = True

    async def xadd(self, stream, fields, **kwargs):
        del kwargs
        stream_id = f"{len(self.messages) + len(self.dead_letters) + 1}-0"
        if stream.endswith(":dead"):
            self.dead_letters.append((stream_id, dict(fields)))
        else:
            self.messages.append((stream_id, dict(fields)))
        return stream_id

    async def xreadgroup(self, group, consumer, streams, count, block):
        del group, consumer, count, block
        pending = [item for item in self.messages if item[0] not in self.delivered and item[0] not in self.acked]
        for stream_id, _fields in pending:
            self.delivered.add(stream_id)
        if not pending:
            return []
        return [(next(iter(streams)), pending)]

    async def xautoclaim(self, *args, **kwargs):
        del args, kwargs
        return ("0-0", [], [])

    async def xack(self, stream, group, stream_id):
        del stream, group
        self.acked.append(stream_id)
        return 1


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _dispatch() -> None:
    factory, engine = await _session_factory()
    redis = FakeRedis()
    async with factory() as db:
        user = User(
            username="worker",
            email="worker@alpha-router.local",
            hashed_password="x",
            auth_provider="local",
        )
        db.add(user)
        await db.flush()
        session = ChatSession(
            id="sess-worker",
            user_id=user.id,
            title="Chat",
            model_id="m",
            private_mode=False,
        )
        db.add(session)
        db.add(SystemSetting(key="memory_extraction_model_id", value="1"))
        for seq, role, text in (
            (1, "user", "I drink my coffee black"),
            (2, "assistant", "Noted."),
        ):
            db.add(
                ChatMessage(
                    id=str(uuid.uuid4()),
                    session_id=session.id,
                    user_id=user.id,
                    role=role,
                    content=text,
                    sequence=seq,
                )
            )
        memory_job = await schedule_extraction(db, user_id=user.id, session_id=session.id, watermark_sequence=2)
        assert memory_job is not None
        past = dt.datetime.utcnow() - dt.timedelta(seconds=1)
        memory_job.run_after = past
        outbox = (
            await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == "memory.job.ready"))
        ).scalar_one()
        outbox.available_at = past

        kb = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug=f"kb-{uuid.uuid4().hex[:8]}",
            name="Knowledge",
            status="active",
            access_type="private",
            sensitivity="internal",
        )
        db.add(kb)
        await db.flush()
        knowledge_job = await enqueue_knowledge_job(
            db,
            knowledge_base_id=kb.id,
            job_type="noop",
            idempotency_key="noop:memory-dispatch",
            payload={"source": "test"},
        )
        await db.commit()
        memory_job_id = memory_job.id
        knowledge_job_id = knowledge_job.id
        user_id = user.id

    await relay_outbox_once(factory, redis, worker_id="scheduler-1")
    await ensure_consumer_group(redis)
    messages = await read_new_messages(redis, consumer_name="worker-1")
    assert {message.event_type for message in messages} == {
        "memory.job.ready",
        "knowledge.job.ready",
    }

    async def fake_extract(db, *, window, completer=None):
        del db, window, completer
        return [
            MemoryOperation(
                op="add",
                content="Prefers black coffee",
                category="preference",
                salience=0.6,
            )
        ]

    qdrant = QdrantVectorService(AsyncQdrantClient(location=":memory:"))
    worker = KnowledgeWorker(
        session_factory=factory,
        redis=redis,
        consumer_name="worker-1",
        context=KnowledgeJobContext(qdrant=qdrant),
    )
    outcomes = {}
    with patch(
        "app.services.memory_extraction_service.extract_memory_operations",
        fake_extract,
    ):
        for message in messages:
            result = await worker.process_message(message)
            outcomes[message.event_type] = result.outcome
    assert outcomes["memory.job.ready"] == "succeeded"
    assert outcomes["knowledge.job.ready"] == "succeeded"
    assert len(redis.acked) == 2

    async with factory() as db:
        persisted = await db.get(UserMemoryJob, memory_job_id)
        knowledge = await db.get(IngestionJob, knowledge_job_id)
        memories = (await db.execute(select(UserMemory).where(UserMemory.user_id == user_id))).scalars().all()
        assert persisted.status == "succeeded"
        assert persisted.extracted_sequence == 2
        assert knowledge.status == "succeeded"
        assert [row.content for row in memories] == ["Prefers black coffee"]

    await qdrant.close()
    await engine.dispose()


def test_memory_and_knowledge_jobs_dispatch_on_shared_worker() -> None:
    asyncio.run(_dispatch())
