"""Lifecycle helpers for revoke, connector disable, and purge scheduling."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.knowledge import (
    KnowledgeAuditEvent,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from app.models.user import User
from app.services.agent_definition_service import (
    create_agent,
    create_agent_version,
    purge_agent,
)
from app.services.knowledge_hard_delete_service import hard_delete_knowledge_base
from app.services.knowledge_ingestion_service import soft_revoke_document
from app.services.knowledge_retention_service import (
    LIVE_KNOWLEDGE_DOCUMENT_STATUSES,
    is_live_knowledge_document,
    purge_expired_knowledge_retention,
    schedule_expired_knowledge_retention,
)


async def _run_soft_revoke_document_marks_document() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        kb = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug="kb-lifecycle",
            name="KB",
            status="active",
            access_type="private",
            sensitivity="internal",
            acl_version=1,
        )
        doc = KnowledgeDocument(
            id=str(uuid.uuid4()),
            knowledge_base_id=kb.id,
            canonical_key="file.pdf",
            title="file.pdf",
            status="active",
            acl_version=1,
        )
        db.add(kb)
        db.add(doc)
        await db.flush()
        version_ids = await soft_revoke_document(
            db,
            document=doc,
            actor_user_id=None,
            reason="retired",
        )
        assert doc.status == "revoked"
        assert isinstance(doc.revoked_at, datetime.datetime)
        assert version_ids == []
    await engine.dispose()


async def _run_hard_delete_knowledge_base_tombstones_row() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    class _Store:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def put(self, key: str, body: bytes) -> None:
            del key, body

        async def get(self, key: str, *, max_bytes: int) -> bytes:
            del key, max_bytes
            return b""

        async def delete(self, key: str) -> None:
            self.deleted.append(key)

    class _Qdrant:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def delete_collection(self, *, collection_name: str) -> None:
            self.deleted.append(collection_name)

    store = _Store()
    qdrant = _Qdrant()
    async with Session() as db:
        kb = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug="kb-hard-delete",
            name="Temp KB",
            status="active",
            access_type="private",
            sensitivity="internal",
            acl_version=1,
        )
        doc = KnowledgeDocument(
            id=str(uuid.uuid4()),
            knowledge_base_id=kb.id,
            canonical_key="a.pdf",
            title="a.pdf",
            status="active",
            acl_version=1,
        )
        version = KnowledgeDocumentVersion(
            id=str(uuid.uuid4()),
            document_id=doc.id,
            version_number=1,
            status="published",
            storage_key="knowledge/a.pdf",
            file_name="a.pdf",
            mime_type="application/pdf",
            size_bytes=12,
            sha256="c" * 64,
        )
        db.add(
            KnowledgeAuditEvent(
                id=str(uuid.uuid4()),
                knowledge_base_id=kb.id,
                document_id=doc.id,
                event_type="knowledge.document.created",
                reason="seed",
                payload_json={},
            )
        )
        db.add_all([kb, doc, version])
        await db.flush()
        result = await hard_delete_knowledge_base(
            db,
            knowledge_base=kb,
            confirm_name="Temp KB",
            actor_user_id=None,
            reason="Created by mistake",
            object_store=store,  # type: ignore[arg-type]
            qdrant=qdrant,  # type: ignore[arg-type]
        )
        await db.commit()
        assert result["name"] == "Temp KB"
        assert store.deleted == ["knowledge/a.pdf"]
        remaining = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb.id))).scalar_one_or_none()
        assert remaining is not None
        assert remaining.slug.startswith("purged-")
        assert remaining.status == "archived"
        assert result.get("tombstoned") is True
        docs = (
            (await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == kb.id)))
            .scalars()
            .all()
        )
        assert all(doc.status == "deleted" for doc in docs)
        versions_left = (
            (
                await db.execute(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.document_id.in_([doc.id for doc in docs] or ["__none__"])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert versions_left == []
        audit = (
            (await db.execute(select(KnowledgeAuditEvent).where(KnowledgeAuditEvent.knowledge_base_id == kb.id)))
            .scalars()
            .all()
        )
        assert len(audit) == 1
    await engine.dispose()


async def _run_purge_agent_tombstones_row() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        user = User(
            username="purge-admin",
            email="purge-admin@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        agent = await create_agent(
            db,
            name="Temp Agent",
            slug="temp-agent",
            created_by_user_id=user.id,
        )
        await create_agent_version(
            db,
            agent,
            system_prompt="You are temporary.",
            created_by_user_id=user.id,
            model_policy={"primary_model_id": "gpt-test"},
        )
        await db.flush()
        result = await purge_agent(
            db,
            agent,
            confirm_name="Temp Agent",
            actor_user_id=user.id,
            reason="Created by mistake",
        )
        await db.commit()
        assert result["tombstoned"] is True
        assert agent.slug.startswith("purged-")
        assert agent.status == "archived"
        assert agent.name.startswith("[Deleted]")
    await engine.dispose()


async def _run_schedule_expired_retention_can_scope_to_one_base() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    old = datetime.datetime.utcnow() - datetime.timedelta(days=40)
    async with Session() as db:
        target = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug="kb-target",
            name="Target",
            status="active",
            access_type="private",
            sensitivity="internal",
            acl_version=1,
            retention_days=30,
        )
        other = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug="kb-other",
            name="Other",
            status="active",
            access_type="private",
            sensitivity="internal",
            acl_version=1,
            retention_days=30,
        )
        docs = []
        for kb in (target, other):
            doc = KnowledgeDocument(
                id=str(uuid.uuid4()),
                knowledge_base_id=kb.id,
                canonical_key=f"{kb.slug}.pdf",
                title=kb.slug,
                status="revoked",
                acl_version=1,
                revoked_at=old,
                updated_at=old,
            )
            version = KnowledgeDocumentVersion(
                id=str(uuid.uuid4()),
                document_id=doc.id,
                version_number=1,
                status="revoked",
                storage_key=f"knowledge/{kb.slug}.pdf",
                file_name=f"{kb.slug}.pdf",
                mime_type="application/pdf",
                size_bytes=12,
                sha256=("a" if kb is target else "b") * 64,
            )
            docs.extend([doc, version])
        db.add_all([target, other, *docs])
        await db.flush()
        result = await schedule_expired_knowledge_retention(
            db,
            knowledge_base_id=target.id,
            now=datetime.datetime.utcnow(),
        )
        assert result["scheduled_versions"] == 1
    await engine.dispose()


async def test_soft_revoke_document_marks_document():
    await _run_soft_revoke_document_marks_document()


async def test_hard_delete_knowledge_base_tombstones_row():
    await _run_hard_delete_knowledge_base_tombstones_row()


async def test_purge_agent_tombstones_row():
    await _run_purge_agent_tombstones_row()


async def test_schedule_expired_retention_can_scope_to_one_base():
    await _run_schedule_expired_retention_can_scope_to_one_base()


async def _run_purge_expired_retention_removes_expired_files() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    old = datetime.datetime.utcnow() - datetime.timedelta(days=3)
    recent = datetime.datetime.utcnow() - datetime.timedelta(hours=2)

    class _Store:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def delete(self, key: str) -> None:
            self.deleted.append(key)

    class _Qdrant:
        async def delete_by_filter(self, *, collection_name: str, query_filter: object) -> None:
            del collection_name, query_filter

    store = _Store()
    async with Session() as db:
        knowledge_base = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug="kb-cleanup",
            name="Cleanup",
            status="active",
            access_type="private",
            sensitivity="internal",
            acl_version=1,
            retention_days=1,
        )
        expired = KnowledgeDocument(
            id=str(uuid.uuid4()),
            knowledge_base_id=knowledge_base.id,
            canonical_key="old.pdf",
            title="old.pdf",
            status="revoked",
            acl_version=1,
            revoked_at=old,
            updated_at=old,
        )
        fresh = KnowledgeDocument(
            id=str(uuid.uuid4()),
            knowledge_base_id=knowledge_base.id,
            canonical_key="new.pdf",
            title="new.pdf",
            status="revoked",
            acl_version=1,
            revoked_at=recent,
            updated_at=recent,
        )
        expired_version = KnowledgeDocumentVersion(
            id=str(uuid.uuid4()),
            document_id=expired.id,
            version_number=1,
            status="revoked",
            storage_key="knowledge/old.pdf",
            file_name="old.pdf",
            mime_type="application/pdf",
            size_bytes=12,
            sha256="a" * 64,
        )
        fresh_version = KnowledgeDocumentVersion(
            id=str(uuid.uuid4()),
            document_id=fresh.id,
            version_number=1,
            status="revoked",
            storage_key="knowledge/new.pdf",
            file_name="new.pdf",
            mime_type="application/pdf",
            size_bytes=12,
            sha256="b" * 64,
        )
        db.add_all([knowledge_base, expired, fresh, expired_version, fresh_version])
        await db.flush()
        result = await purge_expired_knowledge_retention(
            db,
            knowledge_base_id=knowledge_base.id,
            object_store=store,  # type: ignore[arg-type]
            qdrant=_Qdrant(),  # type: ignore[arg-type]
        )
        await db.flush()
        assert result["purged_versions"] == 1
        assert result["not_expired_documents"] == 1
        assert store.deleted == ["knowledge/old.pdf"]
        assert (await db.get(KnowledgeDocument, expired.id)).status == "deleted"
        assert (await db.get(KnowledgeDocument, fresh.id)).status == "revoked"


async def test_purge_expired_retention_removes_expired_files():
    await _run_purge_expired_retention_removes_expired_files()


async def _run_overview_counts_only_live_documents() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        knowledge_base = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug="kb-live-count",
            name="Live count KB",
            status="active",
            access_type="private",
            sensitivity="internal",
            acl_version=1,
        )
        db.add(knowledge_base)
        statuses = ("draft", "active", "superseded", "revoked", "deleted")
        for status in statuses:
            db.add(
                KnowledgeDocument(
                    id=str(uuid.uuid4()),
                    knowledge_base_id=knowledge_base.id,
                    canonical_key=f"{status}.pdf",
                    title=f"{status}.pdf",
                    status=status,
                    acl_version=1,
                )
            )
        await db.flush()
        live = [
            document
            for document in (await db.execute(select(KnowledgeDocument))).scalars().all()
            if is_live_knowledge_document(document)
        ]
        assert {document.status for document in live} == set(LIVE_KNOWLEDGE_DOCUMENT_STATUSES)
        assert len(live) == 3
    await engine.dispose()


async def test_overview_counts_only_live_documents():
    await _run_overview_counts_only_live_documents()
