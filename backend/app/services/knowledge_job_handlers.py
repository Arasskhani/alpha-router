"""Built-in data-plane handlers for durable Knowledge jobs."""

from __future__ import annotations

import datetime
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from qdrant_client import models
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    DeletionTombstone,
    IngestionJob,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexVersion,
)
from app.services.agent_governance_service import (
    append_governance_audit_event,
    has_active_legal_hold,
)
from app.services.knowledge_connector_service import (
    CONNECTOR_SYNC_JOB,
    process_connector_sync,
)
from app.services.knowledge_embedding_service import (
    CatalogKnowledgeEmbeddingBackend,
    KnowledgeEmbeddingBackend,
)
from app.services.knowledge_index_service import build_and_activate_knowledge_index
from app.services.knowledge_ingestion_service import (
    DOCUMENT_PROCESS_JOB,
    OBJECT_PURGE_JOB,
    MalwareScanner,
    process_document_version,
    purge_knowledge_object,
)
from app.services.knowledge_object_store import (
    KnowledgeObjectStoreProtocol,
    default_knowledge_object_store,
)
from app.services.knowledge_publisher_service import INDEX_BUILD_JOB
from app.services.malware_scan_service import scan_bytes
from app.services.qdrant_service import QdrantVectorService


@dataclass(frozen=True)
class KnowledgeJobContext:
    qdrant: QdrantVectorService
    object_store: KnowledgeObjectStoreProtocol | None = None
    malware_scanner: MalwareScanner = scan_bytes
    embedding_backend: KnowledgeEmbeddingBackend | None = None


KnowledgeJobHandler = Callable[
    [AsyncSession, IngestionJob, KnowledgeJobContext],
    Awaitable[None],
]


async def handle_noop(
    db: AsyncSession,
    job: IngestionJob,
    context: KnowledgeJobContext,
) -> None:
    del db, job, context


async def handle_qdrant_ensure_index(
    db: AsyncSession,
    job: IngestionJob,
    context: KnowledgeJobContext,
) -> None:
    if not job.index_version_id:
        raise ValueError("qdrant.ensure_index job requires index_version_id")
    index_version = await db.get(KnowledgeIndexVersion, job.index_version_id)
    if index_version is None:
        raise ValueError("Knowledge index version no longer exists")
    index_version.status = "building"
    await db.flush()
    await context.qdrant.ensure_collection(
        collection_name=index_version.collection_name,
        dense_dimensions=index_version.embedding_dimensions,
    )


async def handle_qdrant_activate_index(
    db: AsyncSession,
    job: IngestionJob,
    context: KnowledgeJobContext,
) -> None:
    if not job.index_version_id:
        raise ValueError("qdrant.activate_index job requires index_version_id")
    target = await db.get(KnowledgeIndexVersion, job.index_version_id)
    if target is None:
        raise ValueError("Knowledge index version no longer exists")
    if target.status not in {"validating", "active"}:
        raise ValueError("Knowledge index must pass validation before activation")
    if int(target.indexed_point_count or 0) != int(target.expected_point_count or 0):
        raise ValueError(
            "Knowledge index point count does not match its release manifest"
        )

    current = (
        await db.execute(
            select(KnowledgeIndexVersion).where(
                KnowledgeIndexVersion.knowledge_base_id == target.knowledge_base_id,
                KnowledgeIndexVersion.active_scope_key
                == f"kb-index:{target.knowledge_base_id}",
                KnowledgeIndexVersion.id != target.id,
            )
        )
    ).scalar_one_or_none()
    if current is not None:
        current.status = "retired"
        current.active_scope_key = None
        current.retired_at = datetime.datetime.utcnow()
        await db.flush()

    await context.qdrant.activate_alias(
        alias_name=target.collection_alias,
        collection_name=target.collection_name,
    )
    target.status = "active"
    target.active_scope_key = f"kb-index:{target.knowledge_base_id}"
    target.activated_at = datetime.datetime.utcnow()


async def handle_qdrant_delete_tombstone(
    db: AsyncSession,
    job: IngestionJob,
    context: KnowledgeJobContext,
) -> None:
    tombstone_id = str((job.payload_json or {}).get("tombstone_id") or "")
    tombstone = await db.get(DeletionTombstone, tombstone_id)
    if tombstone is None:
        raise ValueError("Deletion tombstone no longer exists")
    selector = dict(tombstone.vector_selector or {})
    collection_name = str(selector.get("collection_name") or "")
    collections = selector.get("collections")
    if isinstance(collections, list):
        collection_names = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in collections
                if isinstance(item, str) and item.strip()
            )
        )
    else:
        collection_names = ()
    if collection_name and collection_name not in collection_names:
        collection_names = (*collection_names, collection_name)
    field_name = str(selector.get("field") or "")
    value = selector.get("value")
    allowed_fields = {
        "knowledge_base_id",
        "release_id",
        "document_id",
        "document_version_id",
        "chunk_id",
    }
    if not collection_names and not tombstone.storage_key:
        raise ValueError("Deletion tombstone has no external resource selector")
    if collection_names and (
        field_name not in allowed_fields or not isinstance(value, str)
    ):
        raise ValueError("Deletion tombstone has an invalid vector selector")

    version: KnowledgeDocumentVersion | None = None
    document: KnowledgeDocument | None = None
    if tombstone.resource_type == "knowledge_document_version":
        version = await db.get(KnowledgeDocumentVersion, tombstone.resource_id)
        if version is None:
            raise ValueError("Knowledge document version no longer exists")
        document = await db.get(KnowledgeDocument, version.document_id)
        if document is None:
            raise ValueError("Knowledge document no longer exists")
        held_resources = (
            ("knowledge_base", document.knowledge_base_id),
            ("knowledge_document", document.id),
            ("knowledge_document_version", version.id),
        )
        for resource_type, resource_id in held_resources:
            if await has_active_legal_hold(
                db,
                resource_type=resource_type,
                resource_id=resource_id,
            ):
                raise ValueError("Retention purge is blocked by an active legal hold")

    tombstone.status = "processing"
    for target_collection in collection_names:
        await context.qdrant.delete_by_filter(
            collection_name=target_collection,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key=field_name,
                        match=models.MatchValue(value=value),
                    )
                ]
            ),
        )
    if tombstone.storage_key:
        store = context.object_store or default_knowledge_object_store()
        await store.delete(tombstone.storage_key)
    if version is not None and document is not None:
        await db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.document_version_id == version.id
            )
        )
        metadata = dict(version.metadata_json or {})
        metadata["retention"] = {
            "purged": True,
            "purged_at": datetime.datetime.now(datetime.UTC)
            .replace(tzinfo=None)
            .isoformat(),
            "tombstone_id": tombstone.id,
        }
        version.metadata_json = metadata
        version.status = "revoked"
        version.active_scope_key = None
        version.revoked_at = version.revoked_at or datetime.datetime.utcnow()
        document.status = "deleted"
        document.deleted_at = document.deleted_at or datetime.datetime.utcnow()
        await append_governance_audit_event(
            db,
            event_type="governance.retention.knowledge.purged",
            resource_type="knowledge_document_version",
            resource_id=version.id,
            actor_user_id=tombstone.requested_by_user_id,
            payload={
                "knowledge_base_id": document.knowledge_base_id,
                "document_id": document.id,
                "tombstone_id": tombstone.id,
                "vector_collections": list(collection_names),
                "object_deleted": bool(tombstone.storage_key),
            },
        )
    tombstone.status = "completed"
    tombstone.completed_at = datetime.datetime.utcnow()
    tombstone.error_message = None


async def handle_document_scan_extract(
    db: AsyncSession,
    job: IngestionJob,
    context: KnowledgeJobContext,
) -> None:
    await process_document_version(
        db,
        job,
        object_store=context.object_store,
        malware_scanner=context.malware_scanner,
    )


async def handle_object_purge(
    db: AsyncSession,
    job: IngestionJob,
    context: KnowledgeJobContext,
) -> None:
    del db
    await purge_knowledge_object(job, object_store=context.object_store)


async def handle_connector_sync(
    db: AsyncSession,
    job: IngestionJob,
    context: KnowledgeJobContext,
) -> None:
    await process_connector_sync(
        db,
        job,
        object_store=context.object_store,
    )


async def handle_knowledge_index_build(
    db: AsyncSession,
    job: IngestionJob,
    context: KnowledgeJobContext,
) -> None:
    if not job.index_version_id:
        raise ValueError("knowledge.index.build job requires index_version_id")
    published_by_user_id = (job.payload_json or {}).get("published_by_user_id")
    await build_and_activate_knowledge_index(
        db,
        index_version_id=job.index_version_id,
        published_by_user_id=(
            int(published_by_user_id) if published_by_user_id is not None else None
        ),
        qdrant=context.qdrant,
        embedding_backend=(
            context.embedding_backend or CatalogKnowledgeEmbeddingBackend()
        ),
    )


BUILTIN_KNOWLEDGE_JOB_HANDLERS: dict[str, KnowledgeJobHandler] = {
    "noop": handle_noop,
    "qdrant.ensure_index": handle_qdrant_ensure_index,
    "qdrant.activate_index": handle_qdrant_activate_index,
    "qdrant.delete_tombstone": handle_qdrant_delete_tombstone,
    DOCUMENT_PROCESS_JOB: handle_document_scan_extract,
    OBJECT_PURGE_JOB: handle_object_purge,
    CONNECTOR_SYNC_JOB: handle_connector_sync,
    INDEX_BUILD_JOB: handle_knowledge_index_build,
}
