"""Project memory retrieval, injection, usage, and personal-memory isolation."""

from __future__ import annotations

import asyncio
import uuid

from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatSession
from app.models.project import (
    PROJECT_ROLE_PRIMARY_OWNER,
    Project,
    ProjectMember,
    ProjectMemory,
)
from app.models.user import User
from app.services.memory_vector_service import (
    KIND_MEMORY,
    SCOPE_PROJECT,
    SCOPE_USER,
    MemoryVectorPoint,
    MemoryVectorService,
    memory_collection_name,
)
from app.services.project_memory_service import (
    create_auto_project_memory,
    create_project_memory,
    format_project_memory_block,
    load_injectable_project_memories,
    record_project_memory_usage,
)
from app.services.project_turn_planner import augment_messages_with_project_context
from app.services.user_memory_service import create_memory

PROJ_ID = "proj-retrieval"
OTHER_PROJ_ID = "proj-retrieval-other"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _seed(db: AsyncSession) -> tuple[User, ChatSession]:
    owner = User(
        username="owner_retrieval",
        email="owner_retrieval@alpha-router.local",
        hashed_password="x",
        auth_provider="local",
    )
    db.add(owner)
    await db.flush()
    db.add(
        Project(
            id=PROJ_ID,
            name="Retrieval",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ_ID, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    session = ChatSession(
        id="sess-retrieval",
        user_id=owner.id,
        title="Retrieval",
        model_id="m",
        private_mode=False,
        project_id=PROJ_ID,
        channel_kind="ai",
    )
    db.add(session)
    await db.flush()
    return owner, session


async def _manual_facts_stay_pinned() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, _session = await _seed(db)
        await create_project_memory(db, project_id=PROJ_ID, user=owner, content="Invoices are issued monthly")
        for index in range(3):
            await create_auto_project_memory(
                db,
                project_id=PROJ_ID,
                content=f"Learned fact number {index}",
                session_id=None,
                message_id=None,
                author_user_id=owner.id,
                category="convention",
            )
        await db.commit()

        injection = await load_injectable_project_memories(
            db, project_id=PROJ_ID, memory_enabled=True, query="invoices"
        )
        assert injection.own_facts == ("Invoices are issued monthly",)
        assert len(injection.auto_facts) == 3
        assert injection.total_facts == 4

        block = format_project_memory_block(injection)
        manual_at = block.index("Invoices are issued monthly")
        learned_at = block.index("### Learned from project chats")
        assert manual_at < learned_at
        assert "[convention] Learned fact number 0" in block
    await engine.dispose()


async def _usage_is_recorded_for_injected_facts() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, _session = await _seed(db)
        row, _ = await create_auto_project_memory(
            db,
            project_id=PROJ_ID,
            content="Deployments happen on Thursday",
            session_id=None,
            message_id=None,
            author_user_id=owner.id,
            category="convention",
        )
        await db.commit()
        injection = await load_injectable_project_memories(
            db, project_id=PROJ_ID, memory_enabled=True, query="deployments"
        )
        assert row.id in injection.memory_ids
        await record_project_memory_usage(db, PROJ_ID, injection.memory_ids)
        await db.commit()
        refreshed = await db.get(ProjectMemory, row.id)
        assert refreshed.use_count == 1
        assert refreshed.last_used_at is not None
    await engine.dispose()


async def _disabled_and_expired_facts_are_not_injected() -> None:
    import datetime as dt

    factory, engine = await _session_factory()
    async with factory() as db:
        owner, _session = await _seed(db)
        stale, _ = await create_auto_project_memory(
            db,
            project_id=PROJ_ID,
            content="Sprint 1 ends tomorrow",
            session_id=None,
            message_id=None,
            author_user_id=owner.id,
            category="milestone",
        )
        stale.expires_at = dt.datetime.utcnow() - dt.timedelta(days=1)
        off, _ = await create_auto_project_memory(
            db,
            project_id=PROJ_ID,
            content="We might switch to GraphQL",
            session_id=None,
            message_id=None,
            author_user_id=owner.id,
            category="stack",
        )
        off.enabled = False
        await db.commit()
        injection = await load_injectable_project_memories(
            db, project_id=PROJ_ID, memory_enabled=True, query="sprint graphql"
        )
        contents = {fact.content for fact in injection.auto_facts}
        assert contents == set()
    await engine.dispose()


async def _personal_memory_never_reaches_a_project_turn() -> None:
    """Regression: a project chat sees project memory only, never personal facts."""
    factory, engine = await _session_factory()
    async with factory() as db:
        owner, session = await _seed(db)
        await create_memory(db, owner.id, "Prefers black coffee with no sugar")
        await create_auto_project_memory(
            db,
            project_id=PROJ_ID,
            content="The API is versioned under /v2",
            session_id=session.id,
            message_id=None,
            author_user_id=owner.id,
            category="convention",
        )
        await db.commit()

        messages = [{"role": "user", "content": "What do you know about my coffee?"}]
        injected: list[str] = []
        augmented = await augment_messages_with_project_context(
            db,
            messages,
            user_id=owner.id,
            chat_session_id=session.id,
            query="coffee",
            injected_memory_ids=injected,
        )
        blob = "\n".join(str(item.get("content") or "") for item in augmented if item.get("role") == "system")
        assert "## Project memory" in blob
        assert "/v2" in blob
        assert "black coffee" not in blob
        assert injected

        # The proxy resolves the project from the session, so the personal
        # augmenter is skipped entirely for this turn.
        from app.services.proxy_service import _resolve_session_project_id

        assert await _resolve_session_project_id(db, session.id) == PROJ_ID
        personal = ChatSession(
            id="sess-personal-retrieval",
            user_id=owner.id,
            title="Personal",
            model_id="m",
            private_mode=False,
        )
        db.add(personal)
        await db.commit()
        assert await _resolve_session_project_id(db, personal.id) is None
    await engine.dispose()


async def _project_vectors_are_tenant_isolated() -> None:
    client = AsyncQdrantClient(location=":memory:")
    service = MemoryVectorService(client)
    collection = memory_collection_name(version=7)
    await service.ensure_collection(collection_name=collection, dims=4)

    a_id = str(uuid.uuid4())
    b_id = str(uuid.uuid4())
    personal_id = str(uuid.uuid4())
    await service.upsert(
        collection_name=collection,
        points=[
            MemoryVectorPoint(
                point_id=a_id,
                dense=[1.0, 0.0, 0.0, 0.0],
                payload={
                    "memory_id": a_id,
                    "project_id": PROJ_ID,
                    "scope": SCOPE_PROJECT,
                    "kind": KIND_MEMORY,
                    "enabled": True,
                    "category": "decision",
                    "sensitivity": "normal",
                    "updated_at_ms": 1,
                },
            ),
            MemoryVectorPoint(
                point_id=b_id,
                dense=[0.99, 0.01, 0.0, 0.0],
                payload={
                    "memory_id": b_id,
                    "project_id": OTHER_PROJ_ID,
                    "scope": SCOPE_PROJECT,
                    "kind": KIND_MEMORY,
                    "enabled": True,
                    "category": "decision",
                    "sensitivity": "normal",
                    "updated_at_ms": 1,
                },
            ),
            MemoryVectorPoint(
                point_id=personal_id,
                dense=[0.98, 0.02, 0.0, 0.0],
                payload={
                    "memory_id": personal_id,
                    "user_id": "31",
                    "scope": SCOPE_USER,
                    "kind": KIND_MEMORY,
                    "enabled": True,
                    "category": "preference",
                    "sensitivity": "normal",
                    "updated_at_ms": 1,
                },
            ),
        ],
    )

    hits = await service.search(
        collection_name=collection,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
        project_id=PROJ_ID,
        scope=SCOPE_PROJECT,
    )
    assert [hit.point_id for hit in hits] == [a_id]

    other = await service.search(
        collection_name=collection,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
        project_id=OTHER_PROJ_ID,
        scope=SCOPE_PROJECT,
    )
    assert [hit.point_id for hit in other] == [b_id]

    # A personal search never returns project points, and vice versa.
    personal_hits = await service.search(
        collection_name=collection,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
        user_id=31,
    )
    assert [hit.point_id for hit in personal_hits] == [personal_id]

    await service.delete_project(collection_name=collection, project_id=PROJ_ID)
    after = await service.search(
        collection_name=collection,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
        project_id=PROJ_ID,
        scope=SCOPE_PROJECT,
    )
    assert after == []
    still_there = await service.search(
        collection_name=collection,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
        project_id=OTHER_PROJ_ID,
        scope=SCOPE_PROJECT,
    )
    assert [hit.point_id for hit in still_there] == [b_id]
    personal_survives = await service.search(
        collection_name=collection,
        vector=[1.0, 0.0, 0.0, 0.0],
        limit=10,
        score_threshold=0.0,
        user_id=31,
    )
    assert [hit.point_id for hit in personal_survives] == [personal_id]
    await service.close()


def _upsert_requires_the_scope_owner_key() -> None:
    async def run() -> None:
        client = AsyncQdrantClient(location=":memory:")
        service = MemoryVectorService(client)
        collection = memory_collection_name(version=8)
        await service.ensure_collection(collection_name=collection, dims=4)
        try:
            await service.upsert(
                collection_name=collection,
                points=[
                    MemoryVectorPoint(
                        point_id=str(uuid.uuid4()),
                        dense=[1.0, 0.0, 0.0, 0.0],
                        payload={"scope": SCOPE_PROJECT, "kind": KIND_MEMORY},
                    )
                ],
            )
            raise AssertionError("expected a missing project_id to be rejected")
        except ValueError as exc:
            assert "project_id" in str(exc)
        await service.close()

    asyncio.run(run())


def test_manual_project_facts_stay_pinned_above_learned_facts() -> None:
    asyncio.run(_manual_facts_stay_pinned())


def test_injected_project_facts_record_usage() -> None:
    asyncio.run(_usage_is_recorded_for_injected_facts())


def test_disabled_and_expired_project_facts_are_not_injected() -> None:
    asyncio.run(_disabled_and_expired_facts_are_not_injected())


def test_personal_memory_is_not_injected_into_a_project_chat() -> None:
    asyncio.run(_personal_memory_never_reaches_a_project_turn())


def test_project_vectors_are_isolated_by_project_and_scope() -> None:
    asyncio.run(_project_vectors_are_tenant_isolated())


def test_project_vector_upsert_requires_project_id() -> None:
    _upsert_requires_the_scope_owner_key()
