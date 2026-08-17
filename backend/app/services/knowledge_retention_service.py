"""Retention scheduling for revoked Knowledge content across every data store."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    DeletionTombstone,
    IngestionJob,
    KnowledgeBase,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexVersion,
)
from app.services.agent_governance_service import (
    append_governance_audit_event,
    has_active_legal_hold,
)
from app.services.knowledge_job_handlers import (
    KnowledgeJobContext,
    handle_qdrant_delete_tombstone,
)
from app.services.knowledge_job_service import (
    claim_knowledge_job,
    complete_knowledge_job,
    enqueue_knowledge_job,
    fail_knowledge_job,
)
from app.services.knowledge_object_store import (
    KnowledgeObjectStoreProtocol,
    default_knowledge_object_store,
)
from app.services.qdrant_service import QdrantVectorService

KNOWLEDGE_RETENTION_PURGE_JOB = "qdrant.delete_tombstone"
_INLINE_CLEANUP_WORKER = "admin-retention-cleanup"


LIVE_KNOWLEDGE_DOCUMENT_STATUSES = ("draft", "active", "superseded")


def is_purged_knowledge_document(document: KnowledgeDocument) -> bool:
    return (document.status or "") == "deleted"


def is_live_knowledge_document(document: KnowledgeDocument) -> bool:
    return (document.status or "") in LIVE_KNOWLEDGE_DOCUMENT_STATUSES


async def _resource_or_parent_is_held(
    db: AsyncSession,
    *,
    knowledge_base_id: str,
    document_id: str,
    document_version_id: str | None = None,
) -> bool:
    resources = [
        ("knowledge_base", knowledge_base_id),
        ("knowledge_document", document_id),
    ]
    if document_version_id:
        resources.append(("knowledge_document_version", document_version_id))
    for resource_type, resource_id in resources:
        if await has_active_legal_hold(
            db,
            resource_type=resource_type,
            resource_id=resource_id,
        ):
            return True
    return False


async def _collection_names_for_base(
    db: AsyncSession,
    knowledge_base_id: str,
) -> list[str]:
    return list(
        (
            await db.execute(
                select(KnowledgeIndexVersion.collection_name)
                .where(
                    KnowledgeIndexVersion.knowledge_base_id == knowledge_base_id,
                    KnowledgeIndexVersion.status.in_({"active", "retired"}),
                )
                .distinct()
            )
        ).scalars()
    )


async def schedule_document_purge(
    db: AsyncSession,
    *,
    document: KnowledgeDocument,
    actor_user_id: int | None = None,
    reason: str = "purge_now",
) -> dict[str, object]:
    """Create idempotent purge tombstones/jobs for every version of a document."""

    if await _resource_or_parent_is_held(
        db,
        knowledge_base_id=document.knowledge_base_id,
        document_id=document.id,
    ):
        return {
            "document_id": document.id,
            "scheduled_versions": 0,
            "held": True,
            "job_ids": [],
        }

    collections = await _collection_names_for_base(db, document.knowledge_base_id)
    versions = (
        (
            await db.execute(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == document.id
                )
            )
        )
        .scalars()
        .all()
    )
    job_ids: list[str] = []
    scheduled = 0
    for version in versions:
        if await _resource_or_parent_is_held(
            db,
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            document_version_id=version.id,
        ):
            continue
        existing = (
            await db.execute(
                select(DeletionTombstone).where(
                    DeletionTombstone.resource_type == "knowledge_document_version",
                    DeletionTombstone.resource_id == version.id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        tombstone = DeletionTombstone(
            id=str(uuid.uuid4()),
            resource_type="knowledge_document_version",
            resource_id=version.id,
            status="pending",
            storage_key=version.storage_key,
            vector_selector={
                "collections": sorted(set(collections)),
                "field": "document_version_id",
                "value": version.id,
            },
            cache_selector={
                "knowledge_base_id": document.knowledge_base_id,
                "document_id": document.id,
                "document_version_id": version.id,
            },
            requested_by_user_id=actor_user_id,
        )
        db.add(tombstone)
        await db.flush()
        job = await enqueue_knowledge_job(
            db,
            knowledge_base_id=document.knowledge_base_id,
            document_version_id=version.id,
            job_type=KNOWLEDGE_RETENTION_PURGE_JOB,
            idempotency_key=f"retention-purge:{version.id}",
            payload={"tombstone_id": tombstone.id, "reason": reason},
        )
        job_ids.append(job.id)
        await append_governance_audit_event(
            db,
            event_type="governance.retention.knowledge.scheduled",
            resource_type="knowledge_document_version",
            resource_id=version.id,
            actor_user_id=actor_user_id,
            outcome="scheduled",
            payload={
                "knowledge_base_id": document.knowledge_base_id,
                "document_id": document.id,
                "tombstone_id": tombstone.id,
                "reason": reason,
            },
        )
        scheduled += 1
    return {
        "document_id": document.id,
        "scheduled_versions": scheduled,
        "held": False,
        "job_ids": job_ids,
    }


async def schedule_expired_knowledge_retention(
    db: AsyncSession,
    *,
    actor_user_id: int | None = None,
    now: datetime.datetime | None = None,
    limit: int = 100,
    knowledge_base_id: str | None = None,
) -> dict[str, object]:
    """Create idempotent purge tombstones for expired revoked documents."""

    current = now or datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    filters = [
        KnowledgeBase.retention_days.is_not(None),
        KnowledgeDocument.status.in_({"revoked", "deleted"}),
    ]
    if knowledge_base_id:
        filters.append(KnowledgeBase.id == knowledge_base_id)
    rows = (
        await db.execute(
            select(KnowledgeDocument, KnowledgeBase)
            .join(
                KnowledgeBase,
                KnowledgeBase.id == KnowledgeDocument.knowledge_base_id,
            )
            .where(*filters)
            .order_by(KnowledgeDocument.updated_at, KnowledgeDocument.id)
            .limit(max(1, min(int(limit), 1_000)))
        )
    ).all()
    scheduled = 0
    held = 0
    not_expired = 0
    job_ids: list[str] = []
    for document, knowledge_base in rows:
        terminal_at = (
            document.deleted_at
            or document.revoked_at
            or document.updated_at
            or document.created_at
        )
        cutoff = current - datetime.timedelta(
            days=max(1, int(knowledge_base.retention_days or 1))
        )
        if terminal_at > cutoff:
            not_expired += 1
            continue
        result = await schedule_document_purge(
            db,
            document=document,
            actor_user_id=actor_user_id,
            reason="retention_expired",
        )
        if result.get("held"):
            held += 1
            continue
        scheduled += int(result.get("scheduled_versions") or 0)
        job_ids.extend(str(item) for item in (result.get("job_ids") or []))
    return {
        "scheduled_versions": scheduled,
        "held_resources": held,
        "not_expired_documents": not_expired,
        "job_ids": job_ids,
    }


async def _pending_retention_job_ids(
    db: AsyncSession,
    *,
    knowledge_base_id: str,
) -> list[str]:
    return list(
        (
            await db.execute(
                select(IngestionJob.id).where(
                    IngestionJob.knowledge_base_id == knowledge_base_id,
                    IngestionJob.job_type == KNOWLEDGE_RETENTION_PURGE_JOB,
                    IngestionJob.status.in_(
                        ("pending", "retry", "leased", "processing")
                    ),
                )
            )
        ).scalars()
    )


async def execute_retention_purge_jobs(
    db: AsyncSession,
    *,
    job_ids: list[str],
    qdrant: QdrantVectorService | None = None,
    object_store: KnowledgeObjectStoreProtocol | None = None,
) -> dict[str, int]:
    """Run scheduled retention purge jobs in-process so admin cleanup is immediate."""

    context = KnowledgeJobContext(
        qdrant=qdrant or QdrantVectorService(),
        object_store=object_store or default_knowledge_object_store(),
    )
    purged = 0
    failed = 0
    seen: set[str] = set()
    for job_id in job_ids:
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        job = await claim_knowledge_job(
            db,
            job_id=job_id,
            worker_id=_INLINE_CLEANUP_WORKER,
        )
        if job is None:
            continue
        try:
            await handle_qdrant_delete_tombstone(db, job, context)
            await complete_knowledge_job(
                db,
                job,
                worker_id=_INLINE_CLEANUP_WORKER,
            )
            purged += 1
        except Exception as exc:
            await fail_knowledge_job(
                db,
                job,
                worker_id=_INLINE_CLEANUP_WORKER,
                error=exc,
            )
            failed += 1
    return {"purged_versions": purged, "failed_versions": failed}


async def purge_expired_knowledge_retention(
    db: AsyncSession,
    *,
    actor_user_id: int | None = None,
    now: datetime.datetime | None = None,
    limit: int = 100,
    knowledge_base_id: str,
    qdrant: QdrantVectorService | None = None,
    object_store: KnowledgeObjectStoreProtocol | None = None,
) -> dict[str, object]:
    """Schedule and immediately purge expired revoked documents for one KB."""

    scheduled = await schedule_expired_knowledge_retention(
        db,
        actor_user_id=actor_user_id,
        now=now,
        limit=limit,
        knowledge_base_id=knowledge_base_id,
    )
    job_ids = list(scheduled.get("job_ids") or [])
    job_ids.extend(
        await _pending_retention_job_ids(db, knowledge_base_id=knowledge_base_id)
    )
    executed = await execute_retention_purge_jobs(
        db,
        job_ids=job_ids,
        qdrant=qdrant,
        object_store=object_store,
    )
    return {**scheduled, **executed}
