"""Permanent Knowledge Base deletion across DB, object storage, and Qdrant.

PostgreSQL keeps ``knowledge_audit_events`` append-only. Foreign keys from that
table use ``ON DELETE SET NULL``, so deleting a KB / document / release would
UPDATE the audit rows and raise. Permanent delete therefore tombstones the
audited parents while wiping storage, vectors, and deletable children.
"""

from __future__ import annotations

import datetime
import logging

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentKnowledgeBinding
from app.models.knowledge import (
    IngestionJob,
    KnowledgeBase,
    KnowledgeBaseAccessAssignment,
    KnowledgeChunk,
    KnowledgeConnector,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexVersion,
    KnowledgeRelease,
    KnowledgeReleaseDocument,
)
from app.services.agent_governance_service import (
    append_governance_audit_event,
    has_active_legal_hold,
)
from app.services.knowledge_object_store import (
    KnowledgeObjectStoreProtocol,
    default_knowledge_object_store,
)
from app.services.qdrant_service import QdrantVectorService

logger = logging.getLogger(__name__)

PURGED_SLUG_PREFIX = "purged-"


def is_purged_knowledge_base(knowledge_base: KnowledgeBase) -> bool:
    return (knowledge_base.slug or "").startswith(PURGED_SLUG_PREFIX)


async def _assert_not_held(db: AsyncSession, knowledge_base: KnowledgeBase) -> None:
    if await has_active_legal_hold(
        db,
        resource_type="knowledge_base",
        resource_id=knowledge_base.id,
    ):
        raise ValueError("Hard delete is blocked by an active legal hold on this Knowledge Base")
    documents = (
        (
            await db.execute(
                select(KnowledgeDocument.id).where(
                    KnowledgeDocument.knowledge_base_id == knowledge_base.id
                )
            )
        )
        .scalars()
        .all()
    )
    for document_id in documents:
        if await has_active_legal_hold(
            db,
            resource_type="knowledge_document",
            resource_id=document_id,
        ):
            raise ValueError(
                "Hard delete is blocked by an active legal hold on a document in this Knowledge Base"
            )


async def hard_delete_knowledge_base(
    db: AsyncSession,
    *,
    knowledge_base: KnowledgeBase,
    confirm_name: str,
    actor_user_id: int | None,
    reason: str,
    object_store: KnowledgeObjectStoreProtocol | None = None,
    qdrant: QdrantVectorService | None = None,
) -> dict[str, object]:
    """Erase a Knowledge Base permanently (tombstone + wipe content)."""

    if is_purged_knowledge_base(knowledge_base):
        raise ValueError("Knowledge Base is already permanently deleted")
    if (confirm_name or "").strip() != knowledge_base.name:
        raise ValueError("Confirmation name does not match the Knowledge Base name")
    await _assert_not_held(db, knowledge_base)

    store = object_store or default_knowledge_object_store()
    vector = qdrant or QdrantVectorService()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    versions = (
        (
            await db.execute(
                select(KnowledgeDocumentVersion)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeDocumentVersion.document_id,
                )
                .where(KnowledgeDocument.knowledge_base_id == knowledge_base.id)
            )
        )
        .scalars()
        .all()
    )
    version_ids = [version.id for version in versions]
    storage_keys = sorted(
        {
            (version.storage_key or "").strip()
            for version in versions
            if (version.storage_key or "").strip()
        }
    )
    indexes = (
        (
            await db.execute(
                select(KnowledgeIndexVersion).where(
                    KnowledgeIndexVersion.knowledge_base_id == knowledge_base.id
                )
            )
        )
        .scalars()
        .all()
    )
    collections = sorted(
        {
            name
            for index in indexes
            for name in (index.collection_name, index.collection_alias)
            if (name or "").strip()
        }
    )

    release_ids = (
        (
            await db.execute(
                select(KnowledgeRelease.id).where(
                    KnowledgeRelease.knowledge_base_id == knowledge_base.id
                )
            )
        )
        .scalars()
        .all()
    )
    if release_ids:
        await db.execute(
            delete(KnowledgeReleaseDocument).where(
                KnowledgeReleaseDocument.release_id.in_(release_ids)
            )
        )

    await db.execute(
        delete(AgentKnowledgeBinding).where(
            AgentKnowledgeBinding.knowledge_base_id == knowledge_base.id
        )
    )
    await db.execute(
        delete(IngestionJob).where(IngestionJob.knowledge_base_id == knowledge_base.id)
    )
    await db.execute(
        delete(KnowledgeBaseAccessAssignment).where(
            KnowledgeBaseAccessAssignment.knowledge_base_id == knowledge_base.id
        )
    )

    if version_ids:
        # Clear parent pointers first so chunk deletes do not fight self-FKs.
        await db.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.document_version_id.in_(version_ids))
            .values(parent_chunk_id=None)
        )
        await db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.document_version_id.in_(version_ids)
            )
        )
        await db.execute(
            delete(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.id.in_(version_ids)
            )
        )

    await db.execute(
        delete(KnowledgeIndexVersion).where(
            KnowledgeIndexVersion.knowledge_base_id == knowledge_base.id
        )
    )
    await db.execute(
        delete(KnowledgeConnector).where(
            KnowledgeConnector.knowledge_base_id == knowledge_base.id
        )
    )

    documents = (
        (
            await db.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_base_id == knowledge_base.id
                )
            )
        )
        .scalars()
        .all()
    )
    for document in documents:
        document.status = "deleted"
        document.title = "[deleted]"
        document.canonical_key = f"deleted:{knowledge_base.id}:{document.id}"
        document.updated_at = now
        document.deleted_at = now
        if document.revoked_at is None:
            document.revoked_at = now

    releases = (
        (
            await db.execute(
                select(KnowledgeRelease).where(
                    KnowledgeRelease.knowledge_base_id == knowledge_base.id
                )
            )
        )
        .scalars()
        .all()
    )
    for release in releases:
        release.status = "archived"
        release.active_scope_key = None
        release.archived_at = now
        release.change_summary = "Permanently deleted with Knowledge Base"
        release.manifest_json = {}

    kb_id = knowledge_base.id
    kb_name = knowledge_base.name
    kb_slug = knowledge_base.slug
    document_count = len(documents)

    await append_governance_audit_event(
        db,
        event_type="governance.knowledge_base.hard_deleted",
        resource_type="knowledge_base",
        resource_id=kb_id,
        actor_user_id=actor_user_id,
        outcome="success",
        payload={
            "name": kb_name,
            "slug": kb_slug,
            "reason": reason,
            "document_count": document_count,
            "storage_key_count": len(storage_keys),
            "collection_count": len(collections),
            "tombstone": True,
        },
    )

    knowledge_base.status = "archived"
    knowledge_base.slug = f"{PURGED_SLUG_PREFIX}{kb_id}"
    knowledge_base.name = f"[Deleted] {kb_name}"
    knowledge_base.description = None
    knowledge_base.updated_at = now
    await db.flush()

    deleted_objects = 0
    for key in storage_keys:
        try:
            await store.delete(key)
            deleted_objects += 1
        except Exception:
            logger.exception("Failed deleting Knowledge object %s during hard delete", key)

    deleted_collections = 0
    for collection_name in collections:
        try:
            await vector.delete_collection(collection_name=collection_name)
            deleted_collections += 1
        except Exception:
            logger.exception(
                "Failed deleting Qdrant collection %s during hard delete",
                collection_name,
            )

    return {
        "knowledge_base_id": kb_id,
        "name": kb_name,
        "slug": kb_slug,
        "document_count": document_count,
        "deleted_storage_objects": deleted_objects,
        "deleted_collections": deleted_collections,
        "tombstoned": True,
    }
