"""Immutable Knowledge release manifests and blue/green index contracts."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.knowledge import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexVersion,
    KnowledgeRelease,
    KnowledgeReleaseDocument,
)
from app.services.knowledge_chunking_service import CHUNKER_VERSION
from app.services.knowledge_ingestion_service import record_knowledge_audit
from app.services.knowledge_job_service import enqueue_knowledge_job
from app.services.knowledge_sparse_service import SparseEncodingProfile

INDEX_BUILD_JOB = "knowledge.index.build"


def _fingerprint(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_collection_component(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-_").lower()
    return normalized or "knowledge"


async def create_knowledge_release(
    db: AsyncSession,
    *,
    knowledge_base_id: str,
    document_version_ids: list[str],
    created_by_user_id: int,
    change_summary: str,
) -> KnowledgeRelease:
    if not document_version_ids:
        raise ValueError(
            "A Knowledge release must include at least one document version"
        )
    if len(set(document_version_ids)) != len(document_version_ids):
        raise ValueError(
            "A Knowledge release cannot contain duplicate document versions"
        )
    kb_statement = select(KnowledgeBase).where(
        KnowledgeBase.id == knowledge_base_id
    )
    if db.get_bind().dialect.name == "postgresql":
        kb_statement = kb_statement.with_for_update()
    knowledge_base = (await db.execute(kb_statement)).scalar_one_or_none()
    if knowledge_base is None or knowledge_base.status != "active":
        raise ValueError("Knowledge Base must be active before creating a release")

    rows = (
        await db.execute(
            select(KnowledgeDocumentVersion, KnowledgeDocument)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeDocumentVersion.document_id,
            )
            .where(KnowledgeDocumentVersion.id.in_(document_version_ids))
        )
    ).all()
    if len(rows) != len(document_version_ids):
        raise ValueError("One or more document versions do not exist")
    by_id = {version.id: (version, document) for version, document in rows}
    manifest_documents: list[dict] = []
    seen_documents: set[str] = set()
    for version_id in document_version_ids:
        version, document = by_id[version_id]
        if document.knowledge_base_id != knowledge_base_id:
            raise ValueError("Every document version must belong to the Knowledge Base")
        if document.id in seen_documents:
            raise ValueError("Only one version of a document may appear in a release")
        seen_documents.add(document.id)
        if (
            version.status not in {"review", "published"}
            or version.reviewed_at is None
            or version.reviewed_by_user_id is None
        ):
            raise ValueError("Every document version must pass review before release")
        manifest_documents.append(
            {
                "document_id": document.id,
                "document_version_id": version.id,
                "canonical_key": document.canonical_key,
                "sha256": version.sha256,
                "classification": version.classification,
                "authority": version.authority,
                "effective_from": (
                    version.effective_from.isoformat()
                    if version.effective_from is not None
                    else None
                ),
                "effective_to": (
                    version.effective_to.isoformat()
                    if version.effective_to is not None
                    else None
                ),
                "parser_version": version.parser_version,
            }
        )
    manifest = {
        "schema_version": 1,
        "knowledge_base_id": knowledge_base_id,
        "documents": manifest_documents,
    }
    fingerprint = _fingerprint(manifest)
    existing = (
        await db.execute(
            select(KnowledgeRelease).where(KnowledgeRelease.fingerprint == fingerprint)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    version_number = (
        int(
            (
                await db.execute(
                    select(func.max(KnowledgeRelease.version_number)).where(
                        KnowledgeRelease.knowledge_base_id == knowledge_base_id
                    )
                )
            ).scalar()
            or 0
        )
        + 1
    )
    release = KnowledgeRelease(
        id=str(uuid.uuid4()),
        knowledge_base_id=knowledge_base_id,
        version_number=version_number,
        status="draft",
        fingerprint=fingerprint,
        manifest_json=manifest,
        change_summary=(change_summary or "").strip()[:8000] or None,
        created_by_user_id=created_by_user_id,
    )
    db.add(release)
    await db.flush()
    for sort_order, version_id in enumerate(document_version_ids):
        db.add(
            KnowledgeReleaseDocument(
                release_id=release.id,
                document_version_id=version_id,
                sort_order=sort_order,
            )
        )
    await record_knowledge_audit(
        db,
        knowledge_base_id=knowledge_base_id,
        document_id=None,
        event_type="knowledge.release.created",
        actor_user_id=created_by_user_id,
        payload={
            "release_id": release.id,
            "version_number": version_number,
            "fingerprint": fingerprint,
        },
    )
    return release


async def submit_release_for_indexing(
    db: AsyncSession,
    *,
    release_id: str,
    submitted_by_user_id: int,
    embedding_provider: str,
    embedding_model: str,
    embedding_dimensions: int,
    embedding_fingerprint: str,
    sparse_profile: dict,
    allow_self_submit: bool = False,
) -> KnowledgeIndexVersion:
    release_statement = select(KnowledgeRelease).where(
        KnowledgeRelease.id == release_id
    )
    if db.get_bind().dialect.name == "postgresql":
        release_statement = release_statement.with_for_update()
    release = (await db.execute(release_statement)).scalar_one_or_none()
    if release is None or release.status != "draft":
        raise ValueError("Only a draft Knowledge release can be submitted")
    if (
        not allow_self_submit
        and release.created_by_user_id == submitted_by_user_id
    ):
        raise ValueError("Maker-checker policy requires a different release submitter")
    if embedding_dimensions <= 0 or embedding_dimensions > 65_536:
        raise ValueError("Embedding dimensions must be between 1 and 65536")
    provider = (embedding_provider or "").strip()
    model = (embedding_model or "").strip()
    model_fingerprint = (embedding_fingerprint or "").strip()
    if not provider or not model or not model_fingerprint:
        raise ValueError("A complete embedding profile is required")

    normalized_sparse_profile = SparseEncodingProfile.from_dict(
        sparse_profile
    ).as_dict()
    index_profile = {
        "release_fingerprint": release.fingerprint,
        "embedding_provider": provider,
        "embedding_model": model,
        "embedding_dimensions": embedding_dimensions,
        "embedding_fingerprint": model_fingerprint,
        "sparse_profile": normalized_sparse_profile,
        "chunker_version": CHUNKER_VERSION,
    }
    index_fingerprint = _fingerprint(index_profile)
    existing = (
        await db.execute(
            select(KnowledgeIndexVersion).where(
                KnowledgeIndexVersion.fingerprint == index_fingerprint
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    kb_statement = select(KnowledgeBase).where(
        KnowledgeBase.id == release.knowledge_base_id
    )
    if db.get_bind().dialect.name == "postgresql":
        kb_statement = kb_statement.with_for_update()
    knowledge_base = (await db.execute(kb_statement)).scalar_one_or_none()
    index_number = (
        int(
            (
                await db.execute(
                    select(func.max(KnowledgeIndexVersion.version_number)).where(
                        KnowledgeIndexVersion.knowledge_base_id
                        == release.knowledge_base_id
                    )
                )
            ).scalar()
            or 0
        )
        + 1
    )
    prefix = _safe_collection_component(get_settings().qdrant_collection_prefix)
    kb_component = _safe_collection_component(
        knowledge_base.slug if knowledge_base is not None else release.knowledge_base_id
    )
    collection_name = (
        f"{prefix}-{kb_component}-v{index_number}-{index_fingerprint[:10]}"
    )[:255]
    collection_alias = f"{prefix}-{kb_component}-active"[:255]
    document_version_ids = [
        item["document_version_id"]
        for item in dict(release.manifest_json or {}).get("documents", [])
    ]
    chunk_rows = (
        (
            await db.execute(
                select(KnowledgeChunk.metadata_json).where(
                    KnowledgeChunk.document_version_id.in_(document_version_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    expected_points = sum(
        1 for metadata in chunk_rows if dict(metadata or {}).get("kind") != "parent"
    )
    if expected_points <= 0:
        raise ValueError("The release has no indexable chunks")

    index_version = KnowledgeIndexVersion(
        id=str(uuid.uuid4()),
        knowledge_base_id=release.knowledge_base_id,
        release_id=release.id,
        version_number=index_number,
        status="planned",
        embedding_provider=provider,
        embedding_model=model,
        embedding_dimensions=embedding_dimensions,
        embedding_fingerprint=model_fingerprint,
        sparse_profile=normalized_sparse_profile,
        chunker_version=CHUNKER_VERSION,
        collection_name=collection_name,
        collection_alias=collection_alias,
        fingerprint=index_fingerprint,
        expected_point_count=expected_points,
        indexed_point_count=0,
    )
    db.add(index_version)
    release.status = "indexing"
    release.submitted_at = datetime.datetime.utcnow()
    await db.flush()
    await enqueue_knowledge_job(
        db,
        knowledge_base_id=release.knowledge_base_id,
        index_version_id=index_version.id,
        job_type=INDEX_BUILD_JOB,
        idempotency_key=f"knowledge-index-build:{index_version.id}:{index_fingerprint}",
        payload={
            "index_version_id": index_version.id,
            "published_by_user_id": submitted_by_user_id,
        },
    )
    await record_knowledge_audit(
        db,
        knowledge_base_id=release.knowledge_base_id,
        document_id=None,
        event_type="knowledge.release.submitted",
        actor_user_id=submitted_by_user_id,
        payload={
            "release_id": release.id,
            "index_version_id": index_version.id,
            "index_fingerprint": index_fingerprint,
        },
    )
    return index_version


async def activate_release_after_index(
    db: AsyncSession,
    *,
    index_version: KnowledgeIndexVersion,
    published_by_user_id: int | None,
) -> KnowledgeRelease:
    if index_version.status != "active":
        raise ValueError("Knowledge index must be active before release activation")
    release = await db.get(KnowledgeRelease, index_version.release_id)
    if release is None:
        raise ValueError("Knowledge release no longer exists")
    scope_key = f"kb-release:{release.knowledge_base_id}"
    current_release = (
        await db.execute(
            select(KnowledgeRelease).where(
                KnowledgeRelease.active_scope_key == scope_key,
                KnowledgeRelease.id != release.id,
            )
        )
    ).scalar_one_or_none()
    if current_release is not None:
        current_release.status = "archived"
        current_release.active_scope_key = None
        current_release.archived_at = datetime.datetime.utcnow()
        await db.flush()

    now = datetime.datetime.utcnow()
    manifest_documents = dict(release.manifest_json or {}).get("documents", [])
    for item in manifest_documents:
        version = await db.get(
            KnowledgeDocumentVersion,
            item["document_version_id"],
        )
        if version is None:
            raise ValueError("Release manifest references a missing document version")
        previous = (
            await db.execute(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == version.document_id,
                    KnowledgeDocumentVersion.active_scope_key
                    == f"document:{version.document_id}",
                    KnowledgeDocumentVersion.id != version.id,
                )
            )
        ).scalar_one_or_none()
        if previous is not None:
            previous.status = "superseded"
            previous.active_scope_key = None
            await db.flush()
        version.status = "published"
        version.active_scope_key = f"document:{version.document_id}"
        version.published_at = version.published_at or now
        document = await db.get(KnowledgeDocument, version.document_id)
        if document is not None:
            document.status = "active"
        from app.services.project_resource_service import sync_project_resources_for_document

        await sync_project_resources_for_document(db, document_id=version.document_id)

    release.status = "published"
    release.active_scope_key = scope_key
    release.published_by_user_id = published_by_user_id
    release.published_at = now
    await record_knowledge_audit(
        db,
        knowledge_base_id=release.knowledge_base_id,
        document_id=None,
        event_type="knowledge.release.published",
        actor_user_id=published_by_user_id,
        payload={
            "release_id": release.id,
            "index_version_id": index_version.id,
        },
    )
    return release
