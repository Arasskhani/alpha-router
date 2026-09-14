"""Build immutable hybrid Knowledge indexes and atomically activate releases."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
from app.services.knowledge_crypto_service import (
    chunk_plaintext_hash,
    decrypt_text,
)
from app.services.knowledge_embedding_service import KnowledgeEmbeddingBackend
from app.services.knowledge_publisher_service import activate_release_after_index
from app.services.knowledge_sparse_service import (
    SparseEncodingProfile,
    encode_sparse_document,
)
from app.services.qdrant_service import KnowledgeVectorPoint, QdrantVectorService
from app.services.resource_access_service import compile_acl_payload


@dataclass(frozen=True)
class KnowledgeIndexBuildResult:
    index_version_id: str
    release_id: str
    indexed_points: int
    collection_name: str
    collection_alias: str


def _utc_payload(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")


def _point_acl_payload(
    *,
    knowledge_base: KnowledgeBase,
    knowledge_base_assignments: Sequence[KnowledgeBaseAccessAssignment],
    document: KnowledgeDocument,
    document_assignments: Sequence[KnowledgeDocumentAccessAssignment],
) -> dict:
    kb_acl = compile_acl_payload(knowledge_base_assignments)
    document_acl = compile_acl_payload(document_assignments)
    kb_allows = list(kb_acl["allow_principal_tokens"])
    document_allows = list(document_acl["allow_principal_tokens"])
    denies = sorted(set(kb_acl["deny_principal_tokens"]) | set(document_acl["deny_principal_tokens"]))
    return {
        # Explicitly model both ACL layers. A union of allow lists is unsafe:
        # a principal must satisfy a private KB and a restrictive document.
        "kb_access_scope": ("public" if knowledge_base.access_type == "public" else "restricted"),
        "kb_allow_principal_tokens": kb_allows,
        "document_access_scope": ("restricted" if document_allows else "inherited"),
        "document_allow_principal_tokens": document_allows,
        "deny_principal_tokens": denies,
        # Compatibility fields remain useful for diagnostics and old tooling.
        "access_scope": "restricted" if document_allows else "inherited",
        "allow_principal_tokens": sorted(set(kb_allows) | set(document_allows)),
    }


async def _release_rows(
    db: AsyncSession,
    release_id: str,
) -> tuple[
    list[tuple[KnowledgeDocumentVersion, KnowledgeDocument]],
    dict[str, KnowledgeDocument],
]:
    rows = (
        await db.execute(
            select(KnowledgeDocumentVersion, KnowledgeDocument)
            .join(
                KnowledgeReleaseDocument,
                KnowledgeReleaseDocument.document_version_id == KnowledgeDocumentVersion.id,
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeDocumentVersion.document_id,
            )
            .where(KnowledgeReleaseDocument.release_id == release_id)
            .order_by(KnowledgeReleaseDocument.sort_order)
        )
    ).all()
    documents = {str(document.id): document for _, document in rows}
    return list(rows), documents


async def build_and_activate_knowledge_index(
    db: AsyncSession,
    *,
    index_version_id: str,
    published_by_user_id: int | None,
    qdrant: QdrantVectorService,
    embedding_backend: KnowledgeEmbeddingBackend,
) -> KnowledgeIndexBuildResult:
    index_version = await db.get(KnowledgeIndexVersion, index_version_id)
    if index_version is None:
        raise ValueError("Knowledge index version no longer exists")
    if index_version.status not in {
        "planned",
        "building",
        "validating",
        "active",
        "failed",
    }:
        raise ValueError("Knowledge index is not buildable")
    if index_version.status == "failed":
        # Manual/job retry after a transient or now-fixed verification failure.
        index_version.status = "planned"
        index_version.failure_reason = None
        index_version.indexed_point_count = 0
        await db.flush()
    release = await db.get(KnowledgeRelease, index_version.release_id)
    knowledge_base = await db.get(KnowledgeBase, index_version.knowledge_base_id)
    if release is None or knowledge_base is None:
        raise ValueError("Knowledge index references a missing release or Knowledge Base")
    if release.knowledge_base_id != knowledge_base.id:
        raise ValueError("Knowledge index release belongs to another Knowledge Base")
    if release.status not in {"indexing", "published"}:
        raise ValueError("Knowledge release is not ready for indexing")

    release_rows, documents = await _release_rows(db, release.id)
    if not release_rows:
        raise ValueError("Knowledge release manifest has no document versions")
    version_ids = [str(version.id) for version, _ in release_rows]
    for version, document in release_rows:
        if version.status not in {"review", "published"}:
            raise ValueError("Knowledge release contains an unapproved document version")
        if document.status in {"revoked", "deleted"} or document.revoked_at is not None:
            raise ValueError("Knowledge release contains a revoked document")

    kb_assignments = (
        (
            await db.execute(
                select(KnowledgeBaseAccessAssignment).where(
                    KnowledgeBaseAccessAssignment.knowledge_base_id == knowledge_base.id
                )
            )
        )
        .scalars()
        .all()
    )
    document_assignments = (
        (
            await db.execute(
                select(KnowledgeDocumentAccessAssignment).where(
                    KnowledgeDocumentAccessAssignment.document_id.in_(list(documents))
                )
            )
        )
        .scalars()
        .all()
    )
    assignments_by_document: dict[str, list[KnowledgeDocumentAccessAssignment]] = {
        document_id: [] for document_id in documents
    }
    for assignment in document_assignments:
        assignments_by_document.setdefault(str(assignment.document_id), []).append(assignment)
    version_by_id = {str(version.id): version for version, _ in release_rows}

    profile = SparseEncodingProfile.from_dict(index_version.sparse_profile)
    settings = get_settings()
    embedding_batch_size = max(
        1,
        min(256, int(settings.knowledge_embedding_batch_size)),
    )
    upsert_batch_size = max(
        1,
        min(1_000, int(settings.knowledge_index_upsert_batch_size)),
    )
    batch_size = min(embedding_batch_size, upsert_batch_size)

    index_version.status = "building"
    index_version.failure_reason = None
    await db.flush()
    await qdrant.ensure_collection(
        collection_name=index_version.collection_name,
        dense_dimensions=index_version.embedding_dimensions,
    )

    indexed = 0
    chunk_batch: list[KnowledgeChunk] = []

    async def flush_batch() -> None:
        nonlocal indexed
        if not chunk_batch:
            return
        plaintexts: list[str] = []
        for chunk in chunk_batch:
            plaintext = decrypt_text(
                chunk.content,
                associated_data=f"knowledge-chunk:{chunk.id}",
            )
            if chunk_plaintext_hash(int(chunk.chunk_index), plaintext) != chunk.content_hash:
                raise ValueError("Knowledge chunk integrity verification failed")
            plaintexts.append(plaintext)
        vectors = await embedding_backend.embed(
            db,
            provider=index_version.embedding_provider,
            model=index_version.embedding_model,
            dimensions=index_version.embedding_dimensions,
            texts=plaintexts,
        )
        if len(vectors) != len(chunk_batch):
            raise ValueError("Knowledge embedding backend returned an invalid batch")

        points: list[KnowledgeVectorPoint] = []
        for chunk, plaintext, dense in zip(
            chunk_batch,
            plaintexts,
            vectors,
            strict=True,
        ):
            version = version_by_id[str(chunk.document_version_id)]
            document = documents[str(version.document_id)]
            acl = _point_acl_payload(
                knowledge_base=knowledge_base,
                knowledge_base_assignments=kb_assignments,
                document=document,
                document_assignments=assignments_by_document.get(document.id, []),
            )
            points.append(
                KnowledgeVectorPoint(
                    point_id=str(chunk.id),
                    dense=dense,
                    sparse=encode_sparse_document(plaintext, profile=profile),
                    payload={
                        "knowledge_base_id": knowledge_base.id,
                        "release_id": release.id,
                        "document_id": document.id,
                        "document_version_id": version.id,
                        "chunk_id": chunk.id,
                        "chunk_index": int(chunk.chunk_index),
                        "page_number": chunk.page_number,
                        "acl_version": max(
                            int(knowledge_base.acl_version or 0),
                            int(document.acl_version or 0),
                        ),
                        "status": "active",
                        "classification": version.classification,
                        "language": chunk.language or version.language,
                        "authority": version.authority,
                        "effective_from": _utc_payload(version.effective_from),
                        "effective_to": _utc_payload(version.effective_to),
                        "revoked_at": _utc_payload(version.revoked_at),
                        "content_hash": chunk.content_hash,
                        "index_version_id": index_version.id,
                        **acl,
                    },
                )
            )
        indexed += await qdrant.upsert_points(
            collection_name=index_version.collection_name,
            points=points,
        )
        chunk_batch.clear()

    chunk_stream = await db.stream_scalars(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.document_version_id.in_(version_ids))
        .order_by(KnowledgeChunk.document_version_id, KnowledgeChunk.chunk_index)
    )
    async for chunk in chunk_stream:
        if dict(chunk.metadata_json or {}).get("kind") == "parent":
            continue
        chunk_batch.append(chunk)
        if len(chunk_batch) >= batch_size:
            await flush_batch()
    await flush_batch()

    if indexed != int(index_version.expected_point_count or 0):
        raise ValueError("Knowledge index build count does not match the immutable release manifest")
    persisted_count = await qdrant.count_points(collection_name=index_version.collection_name)
    if persisted_count != indexed:
        raise ValueError("Qdrant point count does not match the completed index build")

    index_version.indexed_point_count = indexed
    index_version.status = "validating"
    await db.flush()

    # Alias mutation happens before the authoritative transaction commits.
    # Replaying this idempotent operation after a crash is safe.
    await qdrant.activate_alias(
        alias_name=index_version.collection_alias,
        collection_name=index_version.collection_name,
    )
    current = (
        await db.execute(
            select(KnowledgeIndexVersion).where(
                KnowledgeIndexVersion.knowledge_base_id == knowledge_base.id,
                KnowledgeIndexVersion.active_scope_key == f"kb-index:{knowledge_base.id}",
                KnowledgeIndexVersion.id != index_version.id,
            )
        )
    ).scalar_one_or_none()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    if current is not None:
        current.status = "retired"
        current.active_scope_key = None
        current.retired_at = now
        await db.flush()
    index_version.status = "active"
    index_version.active_scope_key = f"kb-index:{knowledge_base.id}"
    index_version.activated_at = now
    await activate_release_after_index(
        db,
        index_version=index_version,
        published_by_user_id=published_by_user_id,
    )
    return KnowledgeIndexBuildResult(
        index_version_id=index_version.id,
        release_id=release.id,
        indexed_points=indexed,
        collection_name=index_version.collection_name,
        collection_alias=index_version.collection_alias,
    )
