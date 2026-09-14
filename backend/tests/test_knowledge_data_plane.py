"""Qdrant, outbox, Redis stream, and durable Knowledge worker tests."""

from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest
from qdrant_client import AsyncQdrantClient, models
from redis.exceptions import ResponseError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.knowledge import IngestionJob, KnowledgeBase, OutboxEvent
from app.services.knowledge_job_handlers import KnowledgeJobContext
from app.services.knowledge_job_service import (
    claim_knowledge_job,
    enqueue_knowledge_job,
    recover_stale_knowledge_jobs,
)
from app.services.knowledge_queue import (
    ensure_consumer_group,
    read_new_messages,
)
from app.services.knowledge_worker_service import KnowledgeWorker
from app.services.outbox_service import (
    claim_outbox_events,
    mark_outbox_failed,
    relay_outbox_once,
)
from app.services.qdrant_service import (
    KnowledgeVectorPoint,
    QdrantVectorService,
    SparseValues,
)


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


async def _knowledge_base(db: AsyncSession) -> KnowledgeBase:
    row = KnowledgeBase(
        id=str(uuid.uuid4()),
        slug=f"kb-{uuid.uuid4().hex[:8]}",
        name="Knowledge",
        status="active",
        access_type="private",
        sensitivity="internal",
    )
    db.add(row)
    await db.flush()
    return row


async def _test_qdrant_hybrid_collection_and_acl_payload() -> None:
    client = AsyncQdrantClient(location=":memory:")
    service = QdrantVectorService(client)
    collection = "test-kb-v1"
    assert await service.ensure_collection(
        collection_name=collection,
        dense_dimensions=3,
        replication_factor=1,
    )
    assert not await service.ensure_collection(
        collection_name=collection,
        dense_dimensions=3,
        replication_factor=1,
    )
    with pytest.raises(ValueError, match="incompatible"):
        await service.ensure_collection(
            collection_name=collection,
            dense_dimensions=4,
            replication_factor=1,
        )

    point_id = str(uuid.uuid4())
    count = await service.upsert_points(
        collection_name=collection,
        points=[
            KnowledgeVectorPoint(
                point_id=point_id,
                dense=[1.0, 0.0, 0.0],
                sparse=SparseValues(indices=[3, 8], values=[1.0, 0.5]),
                payload={
                    "knowledge_base_id": "kb-1",
                    "release_id": "release-1",
                    "document_id": "doc-1",
                    "document_version_id": "doc-version-1",
                    "chunk_id": point_id,
                    "chunk_index": 0,
                    "acl_version": 2,
                    "status": "active",
                    "classification": "internal",
                    "allow_principal_tokens": ["group:1"],
                    "deny_principal_tokens": [],
                },
            )
        ],
    )
    assert count == 1
    await service.activate_alias(alias_name="test-kb-active", collection_name=collection)
    response = await client.query_points(
        "test-kb-active",
        query=[1.0, 0.0, 0.0],
        using="dense",
        limit=5,
        with_payload=True,
    )
    assert [str(point.id) for point in response.points] == [point_id]
    assert response.points[0].payload["allow_principal_tokens"] == ["group:1"]

    await service.delete_by_filter(
        collection_name=collection,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value="doc-1"),
                )
            ]
        ),
    )
    after_delete = await client.count(collection, exact=True)
    assert after_delete.count == 0
    await service.close()


async def _test_outbox_relay_and_successful_worker() -> None:
    factory, engine = await _session_factory()
    redis = FakeRedis()
    async with factory() as db:
        kb = await _knowledge_base(db)
        job = await enqueue_knowledge_job(
            db,
            knowledge_base_id=kb.id,
            job_type="noop",
            idempotency_key="noop:1",
            payload={"source": "test"},
        )
        duplicate = await enqueue_knowledge_job(
            db,
            knowledge_base_id=kb.id,
            job_type="noop",
            idempotency_key="noop:1",
            payload={"source": "different"},
        )
        assert duplicate.id == job.id
        await db.commit()

    stats = await relay_outbox_once(factory, redis, worker_id="scheduler-1")
    assert (stats.claimed, stats.published, stats.retried, stats.dead) == (1, 1, 0, 0)
    await ensure_consumer_group(redis)
    await ensure_consumer_group(redis)
    messages = await read_new_messages(redis, consumer_name="worker-1")
    assert len(messages) == 1

    qdrant = QdrantVectorService(AsyncQdrantClient(location=":memory:"))
    worker = KnowledgeWorker(
        session_factory=factory,
        redis=redis,
        consumer_name="worker-1",
        context=KnowledgeJobContext(qdrant=qdrant),
    )
    result = await worker.process_message(messages[0])
    assert result.outcome == "succeeded"
    assert messages[0].stream_id in redis.acked
    async with factory() as db:
        persisted = await db.get(IngestionJob, result.job_id)
        outbox = (await db.execute(select(OutboxEvent))).scalars().all()
        assert persisted.status == "succeeded"
        assert persisted.attempt_count == 1
        assert [event.status for event in outbox] == ["processed"]
    await qdrant.close()
    await engine.dispose()


async def _test_worker_dead_letters_unsupported_job() -> None:
    factory, engine = await _session_factory()
    redis = FakeRedis()
    async with factory() as db:
        kb = await _knowledge_base(db)
        job = await enqueue_knowledge_job(
            db,
            knowledge_base_id=kb.id,
            job_type="unsupported.type",
            idempotency_key="unsupported:1",
            payload={},
            max_attempts=1,
        )
        await db.commit()
    await relay_outbox_once(factory, redis, worker_id="scheduler-1")
    await ensure_consumer_group(redis)
    message = (await read_new_messages(redis, consumer_name="worker-1"))[0]

    qdrant = QdrantVectorService(AsyncQdrantClient(location=":memory:"))
    worker = KnowledgeWorker(
        session_factory=factory,
        redis=redis,
        consumer_name="worker-1",
        context=KnowledgeJobContext(qdrant=qdrant),
    )
    result = await worker.process_message(message)
    assert result.outcome == "dead"
    assert len(redis.dead_letters) == 1
    async with factory() as db:
        persisted = await db.get(IngestionJob, job.id)
        assert persisted.status == "dead"
        assert persisted.error_code == "handler_failed"
    await qdrant.close()
    await engine.dispose()


async def _test_outbox_retry_and_stale_job_recovery() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        kb = await _knowledge_base(db)
        job = await enqueue_knowledge_job(
            db,
            knowledge_base_id=kb.id,
            job_type="noop",
            idempotency_key="recover:1",
            payload={},
        )
        await db.commit()

    async with factory() as db:
        event = (await claim_outbox_events(db, worker_id="scheduler-1"))[0]
        status = await mark_outbox_failed(
            db,
            event,
            worker_id="scheduler-1",
            error="Redis unavailable",
        )
        assert status == "retry"
        assert event.attempt_count == 1
        assert event.available_at > datetime.datetime.utcnow()
        await db.commit()

    expired = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
    async with factory() as db:
        claimed = await claim_knowledge_job(
            db,
            job_id=job.id,
            worker_id="worker-crashed",
        )
        claimed.lease_until = expired
        await db.commit()
    async with factory() as db:
        assert await recover_stale_knowledge_jobs(db) == 1
        await db.commit()
        recovered = await db.get(IngestionJob, job.id)
        assert recovered.status == "retry"
        assert recovered.lease_owner is None
        assert recovered.error_code == "lease_expired"
    await engine.dispose()


def test_qdrant_hybrid_collection_and_acl_payload():
    asyncio.run(_test_qdrant_hybrid_collection_and_acl_payload())


def test_outbox_relay_and_successful_worker():
    asyncio.run(_test_outbox_relay_and_successful_worker())


def test_worker_dead_letters_unsupported_job():
    asyncio.run(_test_worker_dead_letters_unsupported_job())


def test_outbox_retry_and_stale_job_recovery():
    asyncio.run(_test_outbox_retry_and_stale_job_recovery())
