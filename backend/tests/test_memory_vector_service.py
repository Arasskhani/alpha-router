"""Dedicated memory vector collection: tenant isolation and lifecycle."""

from __future__ import annotations

import asyncio
import uuid

from qdrant_client import AsyncQdrantClient

from app.services.memory_vector_service import (
    KIND_MEMORY,
    MemoryVectorPoint,
    MemoryVectorService,
    memory_collection_alias,
    memory_collection_name,
)


async def _tenant_and_lifecycle() -> None:
    client = AsyncQdrantClient(location=":memory:")
    service = MemoryVectorService(client)
    collection = memory_collection_name(version=1)
    created = await service.ensure_collection(collection_name=collection, dims=4)
    assert created is True
    assert await service.ensure_collection(collection_name=collection, dims=4) is False

    alice_id = str(uuid.uuid4())
    bob_id = str(uuid.uuid4())
    await service.upsert(
        collection_name=collection,
        points=[
            MemoryVectorPoint(
                point_id=alice_id,
                dense=[1.0, 0.0, 0.0, 0.0],
                payload={
                    "memory_id": alice_id,
                    "user_id": "11",
                    "kind": KIND_MEMORY,
                    "enabled": True,
                    "category": "health",
                    "sensitivity": "sensitive",
                    "updated_at_ms": 1,
                },
            ),
            MemoryVectorPoint(
                point_id=bob_id,
                dense=[0.9, 0.1, 0.0, 0.0],
                payload={
                    "memory_id": bob_id,
                    "user_id": "22",
                    "kind": KIND_MEMORY,
                    "enabled": True,
                    "category": "preference",
                    "sensitivity": "normal",
                    "updated_at_ms": 1,
                },
            ),
        ],
    )
    # Idempotent upsert of Alice's point.
    await service.upsert(
        collection_name=collection,
        points=[
            MemoryVectorPoint(
                point_id=alice_id,
                dense=[1.0, 0.0, 0.0, 0.0],
                payload={
                    "memory_id": alice_id,
                    "user_id": "11",
                    "kind": KIND_MEMORY,
                    "enabled": True,
                    "category": "health",
                    "sensitivity": "sensitive",
                    "updated_at_ms": 2,
                },
            )
        ],
    )
    alice_hits = await service.search(
        collection_name=collection,
        user_id=11,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
    )
    assert [hit.point_id for hit in alice_hits] == [alice_id]
    assert "content" not in alice_hits[0].payload
    bob_from_alice = [hit for hit in alice_hits if hit.point_id == bob_id]
    assert bob_from_alice == []

    bob_hits = await service.search(
        collection_name=collection,
        user_id=22,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
    )
    assert [hit.point_id for hit in bob_hits] == [bob_id]

    await service.delete_ids(collection_name=collection, point_ids=[alice_id])
    after_delete = await service.search(
        collection_name=collection,
        user_id=11,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
    )
    assert after_delete == []

    await service.delete_user(collection_name=collection, user_id=22)
    after_user = await service.search(
        collection_name=collection,
        user_id=22,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
    )
    assert after_user == []

    v2 = memory_collection_name(version=2)
    await service.ensure_collection(collection_name=v2, dims=4)
    await service.activate_alias(collection_name=v2)
    assert await service.resolve_target_collection() == v2
    assert memory_collection_alias().endswith("-active")
    await service.close()


def test_memory_vector_tenant_isolation_and_alias() -> None:
    asyncio.run(_tenant_and_lifecycle())
