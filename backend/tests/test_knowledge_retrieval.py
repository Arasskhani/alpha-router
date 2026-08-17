"""Hybrid indexing, RRF, post-authorization, and citation tests."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import os
import uuid

import pytest
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.agent import Agent, AgentKnowledgeBinding, AgentVersion
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeBaseAccessAssignment,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentAccessAssignment,
    KnowledgeDocumentVersion,
    KnowledgeIndexVersion,
    KnowledgeRelease,
    KnowledgeReleaseDocument,
)
from app.models.user import User
from app.services.knowledge_citation_service import verify_answer_citations
from app.services.knowledge_crypto_service import encrypt_text
from app.services.knowledge_index_service import build_and_activate_knowledge_index
from app.services.knowledge_retrieval_service import (
    build_qdrant_retrieval_filter,
    reciprocal_rank_fusion,
    retrieve_knowledge,
)
from app.services.knowledge_sparse_service import (
    SparseEncodingProfile,
    encode_sparse_query,
    lexical_tokens,
)
from app.services.qdrant_service import (
    KnowledgeSearchHit,
    KnowledgeVectorPoint,
    QdrantVectorService,
)
from app.services.resource_access_service import (
    AccessGrant,
    ResourceAccessSubject,
    resolve_resource_access_subject,
    set_document_access,
)


class FakeEmbeddingBackend:
    async def embed(
        self,
        db,
        *,
        provider: str,
        model: str,
        dimensions: int,
        texts,
    ) -> list[list[float]]:
        del db, provider, model
        vectors: list[list[float]] = []
        for text in texts:
            tokens = set(lexical_tokens(text))
            vector = [
                float(bool(tokens & {"leave", "مرخصی"})),
                float(bool(tokens & {"payroll", "salary", "حقوق"})),
                float(bool(tokens & {"vpn", "network"})),
            ]
            vectors.append(vector[:dimensions])
        return vectors


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    ), engine


async def _user(db: AsyncSession, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _chunk(
    *,
    version_id: str,
    index: int,
    text: str,
    page: int,
    section: str,
) -> KnowledgeChunk:
    chunk_id = str(uuid.uuid4())
    return KnowledgeChunk(
        id=chunk_id,
        document_version_id=version_id,
        chunk_index=index,
        content=encrypt_text(
            text,
            associated_data=f"knowledge-chunk:{chunk_id}",
        ),
        content_hash=hashlib.sha256(f"{index}\0{text}".encode()).hexdigest(),
        token_count=max(1, len(text.split())),
        page_number=page,
        section=section,
        language="en",
        metadata_json={"kind": "leaf"},
    )


async def _seed_index(db: AsyncSession):
    allowed = await _user(db, "allowed")
    finance = await _user(db, "finance")
    knowledge_base = KnowledgeBase(
        id=str(uuid.uuid4()),
        slug="enterprise-policies",
        name="Enterprise Policies",
        status="active",
        access_type="private",
        sensitivity="internal",
    )
    db.add(knowledge_base)
    await db.flush()
    for user in (allowed, finance):
        db.add(
            KnowledgeBaseAccessAssignment(
                knowledge_base_id=knowledge_base.id,
                user_id=user.id,
                effect="allow",
            )
        )

    documents: list[KnowledgeDocument] = []
    versions: list[KnowledgeDocumentVersion] = []
    source_data = [
        (
            "leave-policy",
            "Annual Leave Policy",
            "Annual leave requests must be submitted through the HR portal.",
        ),
        (
            "payroll-policy",
            "Payroll Policy",
            "Salary and payroll corrections require Finance approval.",
        ),
    ]
    for position, (key, title, text) in enumerate(source_data):
        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            knowledge_base_id=knowledge_base.id,
            canonical_key=f"{key}.txt",
            title=title,
            status="draft",
        )
        version = KnowledgeDocumentVersion(
            id=str(uuid.uuid4()),
            document_id=document.id,
            version_number=1,
            status="review",
            storage_key=f"private/knowledge/documents/{key}",
            file_name=f"{key}.txt",
            mime_type="text/plain",
            size_bytes=len(text.encode()),
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            language="en",
            classification="internal",
            authority="canonical",
            parser_version="test-v1",
            reviewed_by_user_id=finance.id,
            reviewed_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        db.add_all([document, version])
        await db.flush()
        db.add(
            _chunk(
                version_id=version.id,
                index=position,
                text=text,
                page=position + 1,
                section=title,
            )
        )
        documents.append(document)
        versions.append(version)
    await db.flush()
    db.add(
        KnowledgeDocumentAccessAssignment(
            document_id=documents[1].id,
            user_id=finance.id,
            effect="allow",
        )
    )

    release = KnowledgeRelease(
        id=str(uuid.uuid4()),
        knowledge_base_id=knowledge_base.id,
        version_number=1,
        status="indexing",
        fingerprint=uuid.uuid4().hex,
        manifest_json={
            "schema_version": 1,
            "knowledge_base_id": knowledge_base.id,
            "documents": [
                {
                    "document_id": document.id,
                    "document_version_id": version.id,
                }
                for document, version in zip(documents, versions, strict=True)
            ],
        },
        created_by_user_id=allowed.id,
    )
    db.add(release)
    await db.flush()
    for sort_order, version in enumerate(versions):
        db.add(
            KnowledgeReleaseDocument(
                release_id=release.id,
                document_version_id=version.id,
                sort_order=sort_order,
            )
        )
    index_version = KnowledgeIndexVersion(
        id=str(uuid.uuid4()),
        knowledge_base_id=knowledge_base.id,
        release_id=release.id,
        version_number=1,
        status="planned",
        embedding_provider="test",
        embedding_model="test-embedding",
        embedding_dimensions=3,
        embedding_fingerprint="test-embedding-v1",
        sparse_profile={"algorithm": "bm25"},
        chunker_version="test-v1",
        collection_name=f"test-{uuid.uuid4().hex}",
        collection_alias=f"test-{uuid.uuid4().hex}-active",
        fingerprint=uuid.uuid4().hex,
        expected_point_count=2,
    )
    db.add(index_version)

    agent = Agent(
        id=str(uuid.uuid4()),
        slug="hr-assistant",
        name="HR Assistant",
        status="active",
        access_type="public",
    )
    agent_version = AgentVersion(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        version_number=1,
        status="published",
        system_prompt="Answer from approved HR policy.",
        retrieval_policy={
            "candidate_limit": 10,
            "final_limit": 5,
            "minimum_answerability_score": 0.2,
            "citations_required": True,
            "fail_closed": True,
        },
        fingerprint=uuid.uuid4().hex,
        active_scope_key=f"agent:{agent.id}",
    )
    db.add_all([agent, agent_version])
    await db.flush()
    binding = AgentKnowledgeBinding(
        id=str(uuid.uuid4()),
        agent_version_id=agent_version.id,
        knowledge_base_id=knowledge_base.id,
        release_mode="latest",
        status="published",
    )
    db.add(binding)
    await db.flush()
    return {
        "allowed": allowed,
        "finance": finance,
        "knowledge_base": knowledge_base,
        "documents": documents,
        "versions": versions,
        "release": release,
        "index_version": index_version,
        "agent_version": agent_version,
    }


async def _test_hybrid_index_retrieval_and_stale_acl_denial() -> None:
    factory, engine = await _session_factory()
    qdrant = QdrantVectorService(AsyncQdrantClient(location=":memory:"))
    embedding = FakeEmbeddingBackend()
    async with factory() as db:
        seeded = await _seed_index(db)
        result = await build_and_activate_knowledge_index(
            db,
            index_version_id=seeded["index_version"].id,
            published_by_user_id=seeded["finance"].id,
            qdrant=qdrant,
            embedding_backend=embedding,
        )
        assert result.indexed_points == 2
        assert seeded["release"].status == "published"
        assert seeded["index_version"].status == "active"
        await db.commit()

    async with factory() as db:
        subject = await resolve_resource_access_subject(
            db,
            user_id=seeded["allowed"].id,
        )
        retrieval = await retrieve_knowledge(
            db,
            agent_version_id=seeded["agent_version"].id,
            subject=subject,
            query="How do I submit annual leave?",
            qdrant=qdrant,
            embedding_backend=embedding,
        )
        assert retrieval.answerable
        assert retrieval.evidence
        assert {evidence.citation.document_id for evidence in retrieval.evidence} == {
            seeded["documents"][0].id
        }
        assert "Annual leave requests" in retrieval.context.text
        assert "enc:v1:" not in retrieval.context.text
        citation = retrieval.evidence[0].citation
        assert citation.page_number == 1
        assert citation.section == "Annual Leave Policy"
        assert verify_answer_citations(
            f"Use the HR portal {citation.marker}",
            retrieval.context.citations,
            citations_required=True,
        ).valid
        assert not verify_answer_citations(
            "Unsupported [[cite:invented]]",
            retrieval.context.citations,
            citations_required=True,
        ).valid

        # A session-pinned behavior version remains executable after a newer
        # version becomes active; ACL and release authorization are still live.
        agent_version = await db.get(AgentVersion, seeded["agent_version"].id)
        agent_version.status = "archived"
        agent_version.published_at = datetime.datetime.now(datetime.UTC).replace(
            tzinfo=None
        )
        await db.flush()
        pinned = await retrieve_knowledge(
            db,
            agent_version_id=agent_version.id,
            subject=subject,
            query="How do I submit annual leave?",
            qdrant=qdrant,
            embedding_backend=embedding,
        )
        assert pinned.answerable
        agent_version.status = "published"
        await db.flush()

        finance_subject = await resolve_resource_access_subject(
            db,
            user_id=seeded["finance"].id,
        )
        finance_retrieval = await retrieve_knowledge(
            db,
            agent_version_id=seeded["agent_version"].id,
            subject=finance_subject,
            query="How are payroll corrections approved?",
            qdrant=qdrant,
            embedding_backend=embedding,
        )
        assert finance_retrieval.answerable
        assert {
            evidence.citation.document_id for evidence in finance_retrieval.evidence
        } == {seeded["documents"][1].id}

        unrelated = await retrieve_knowledge(
            db,
            agent_version_id=seeded["agent_version"].id,
            subject=subject,
            query="How are payroll corrections approved?",
            qdrant=qdrant,
            embedding_backend=embedding,
        )
        assert not unrelated.answerable
        assert unrelated.evidence == ()

        leave_version = await db.get(
            KnowledgeDocumentVersion,
            seeded["versions"][0].id,
        )
        leave_version.effective_to = datetime.datetime.now(datetime.UTC).replace(
            tzinfo=None
        ) - datetime.timedelta(days=1)
        await db.flush()
        expired = await retrieve_knowledge(
            db,
            agent_version_id=seeded["agent_version"].id,
            subject=subject,
            query="How do I submit annual leave?",
            qdrant=qdrant,
            embedding_backend=embedding,
        )
        assert not expired.answerable
        assert expired.evidence == ()
        leave_version.effective_to = None
        await db.flush()

        # Qdrant still contains the old inherited ACL payload. PostgreSQL is
        # authoritative, so the next request must fail closed post-retrieval.
        leave_document = await db.get(
            KnowledgeDocument,
            seeded["documents"][0].id,
        )
        await set_document_access(
            db,
            leave_document,
            grants=[AccessGrant("user", seeded["allowed"].id, "deny")],
        )
        await db.flush()
        denied = await retrieve_knowledge(
            db,
            agent_version_id=seeded["agent_version"].id,
            subject=subject,
            query="How do I submit annual leave?",
            qdrant=qdrant,
            embedding_backend=embedding,
        )
        assert not denied.answerable
        assert denied.evidence == ()
        assert denied.abstention_reason == "no_authorized_evidence"

    await qdrant.close()
    await engine.dispose()


def test_sparse_encoder_normalizes_persian_and_is_deterministic():
    profile = SparseEncodingProfile.from_dict({"algorithm": "bm25"})
    first = encode_sparse_query("مرخصي  سالانه", profile=profile)
    second = encode_sparse_query("مرخصی سالانه", profile=profile)
    assert first == second
    assert len(first.indices) == 2
    assert list(first.indices) == sorted(first.indices)


def test_rrf_combines_dense_and_sparse_rankings():
    dense = [
        KnowledgeSearchHit("a", 0.9, {"chunk_id": "a"}, "dense"),
        KnowledgeSearchHit("b", 0.8, {"chunk_id": "b"}, "dense"),
    ]
    sparse = [
        KnowledgeSearchHit("b", 9.0, {"chunk_id": "b"}, "sparse"),
        KnowledgeSearchHit("c", 8.0, {"chunk_id": "c"}, "sparse"),
    ]
    fused = reciprocal_rank_fusion(
        [("dense", dense, 1.0), ("sparse", sparse, 1.0)],
        release_id="release",
        index_version_id="index",
        rrf_k=60,
    )
    assert [item.chunk_id for item in fused] == ["b", "a", "c"]
    assert fused[0].dense_rank == 2
    assert fused[0].sparse_rank == 1


def test_hybrid_index_retrieval_and_stale_acl_denial():
    asyncio.run(_test_hybrid_index_retrieval_and_stale_acl_denial())


async def _test_live_qdrant_hybrid_acl_filter() -> None:
    qdrant = QdrantVectorService()
    collection = f"alpharouter-live-test-{uuid.uuid4().hex}"
    point_id = str(uuid.uuid4())
    blocked_id = str(uuid.uuid4())
    profile = SparseEncodingProfile.from_dict(None)
    try:
        await qdrant.ensure_collection(
            collection_name=collection,
            dense_dimensions=3,
            replication_factor=1,
        )
        common = {
            "knowledge_base_id": "kb-live",
            "release_id": "release-live",
            "document_version_id": "version-live",
            "acl_version": 1,
            "status": "active",
            "classification": "internal",
            "kb_access_scope": "restricted",
            "document_access_scope": "inherited",
            "document_allow_principal_tokens": [],
            "deny_principal_tokens": [],
            "access_scope": "inherited",
            "content_hash": "a" * 64,
            "index_version_id": "index-live",
        }
        await qdrant.upsert_points(
            collection_name=collection,
            points=[
                KnowledgeVectorPoint(
                    point_id=point_id,
                    dense=[1.0, 0.0, 0.0],
                    sparse=encode_sparse_query("annual leave", profile=profile),
                    payload={
                        **common,
                        "document_id": "doc-allowed",
                        "chunk_id": point_id,
                        "allow_principal_tokens": ["user:1"],
                        "kb_allow_principal_tokens": ["user:1"],
                    },
                ),
                KnowledgeVectorPoint(
                    point_id=blocked_id,
                    dense=[1.0, 0.0, 0.0],
                    sparse=encode_sparse_query("annual leave", profile=profile),
                    payload={
                        **common,
                        "document_id": "doc-blocked",
                        "chunk_id": blocked_id,
                        "allow_principal_tokens": ["user:2"],
                        "kb_allow_principal_tokens": ["user:2"],
                    },
                ),
            ],
        )
        dense, sparse = await qdrant.hybrid_candidates(
            collection_name=collection,
            dense=[1.0, 0.0, 0.0],
            sparse=encode_sparse_query("annual leave", profile=profile),
            query_filter=build_qdrant_retrieval_filter(
                release_id="release-live",
                subject=ResourceAccessSubject(user_id=1),
                now=datetime.datetime.now(datetime.UTC),
            ),
            limit=10,
            dense_score_threshold=0.05,
            sparse_score_threshold=0.01,
        )
        assert {hit.point_id for hit in dense} == {point_id}
        assert {hit.point_id for hit in sparse} == {point_id}
    finally:
        try:
            if await qdrant.client.collection_exists(collection):
                await qdrant.client.delete_collection(collection)
        finally:
            await qdrant.close()


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_QDRANT_TESTS") != "1",
    reason="live Qdrant integration is opt-in",
)
def test_live_qdrant_hybrid_acl_filter():
    asyncio.run(_test_live_qdrant_hybrid_acl_filter())
