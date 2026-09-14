"""Project resource upload, listing, and deletion.

File ingestion is delegated to the existing secure Knowledge pipeline
(``knowledge_ingestion_service.submit_document_bytes``) so that every
project resource benefits from:

* bounded upload validation (``bounded_io``)
* format / archive-bomb / malware scanning (``knowledge_file_service``,
  ``malware_scan_service``)
* sandboxed text extraction (``knowledge_parser_sandbox``)
* prompt-injection scanning (``knowledge_safety_service``)
* chunking + encryption-at-rest (``knowledge_chunking_service``,
  ``knowledge_crypto_service``)

Each project gets a lazily-created, private internal KnowledgeBase that
serves as the storage and ACL boundary for its documents.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion
from app.models.project import (
    PROJECT_RESOURCE_STATUS_ACTIVE,
    PROJECT_RESOURCE_STATUS_FAILED,
    PROJECT_RESOURCE_STATUS_PROCESSING,
    PROJECT_RESOURCE_STATUS_REVOKED,
    Project,
    ProjectResource,
)
from app.services.knowledge_ingestion_service import (
    DocumentSubmission,
    submit_document_bytes,
)
from app.services.knowledge_object_store import KnowledgeObjectStoreProtocol
from app.services.project_access_service import (
    append_project_audit,
    require_capability,
)

ResourceStatus = Literal["processing", "active", "revoked", "failed"]

_PROJECT_KB_SLUG_PREFIX = "project-internal-"


@dataclass(frozen=True)
class ProjectResourceUpload:
    resource: ProjectResource
    submission: DocumentSubmission


async def ensure_project_knowledge_base(
    db: AsyncSession,
    *,
    project: Project,
) -> KnowledgeBase:
    """Return the project's internal KB, creating it on first use."""

    if project.knowledge_base_id:
        kb = await db.get(KnowledgeBase, project.knowledge_base_id)
        if kb is not None and kb.status != "archived":
            return kb

    slug = f"{_PROJECT_KB_SLUG_PREFIX}{project.id}"
    existing = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.slug == slug))).scalar_one_or_none()
    if existing is not None and existing.status != "archived":
        kb = existing
    else:
        kb = KnowledgeBase(
            id=str(uuid.uuid4()),
            slug=slug,
            name=f"Project: {project.name}"[:255],
            description="Internal KnowledgeBase for project resources.",
            status="active",
            access_type="private",
            sensitivity="internal",
            owner_user_id=project.created_by_user_id,
            created_by_user_id=project.created_by_user_id,
        )
        db.add(kb)
        await db.flush()

    project.knowledge_base_id = kb.id
    project.updated_at = datetime.datetime.utcnow()
    await db.flush()
    return kb


async def upload_project_resource(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    file_name: str,
    declared_mime: str | None,
    data: bytes,
    title: str | None = None,
    object_store: KnowledgeObjectStoreProtocol | None = None,
) -> ProjectResourceUpload:
    """Upload a file as a project resource through the secure Knowledge pipeline.

    Requires ``resource.upload`` capability (Owner or Contributor).
    """

    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="resource.upload",
    )
    project = await db.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")

    kb = await ensure_project_knowledge_base(db, project=project)

    safe_title = (title or file_name or "resource").strip()[:512] or "resource"

    submission = await submit_document_bytes(
        db,
        knowledge_base_id=kb.id,
        file_name=file_name,
        declared_mime=declared_mime,
        data=data,
        uploaded_by_user_id=access.user_id,
        title=safe_title,
        canonical_key=f"project/{project_id}/{file_name}",
        source_type="project_upload",
        object_store=object_store,
    )

    resource = ProjectResource(
        id=str(uuid.uuid4()),
        project_id=project_id,
        document_id=submission.document.id,
        title=safe_title,
        status=PROJECT_RESOURCE_STATUS_PROCESSING,
        uploaded_by_user_id=access.user_id,
    )
    db.add(resource)
    await db.flush()

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="project.resource.uploaded",
        actor_user_id=access.user_id,
        payload={
            "resource_id": resource.id,
            "document_id": submission.document.id,
            "version_id": submission.version.id,
            "duplicate": submission.duplicate,
            "file_name": file_name,
        },
    )

    return ProjectResourceUpload(resource=resource, submission=submission)


def _resource_status_from_version(
    version_status: str | None,
    *,
    current: str,
) -> str:
    if version_status == "published":
        return PROJECT_RESOURCE_STATUS_ACTIVE
    if version_status == "revoked":
        return PROJECT_RESOURCE_STATUS_REVOKED
    if version_status == "failed":
        return PROJECT_RESOURCE_STATUS_FAILED
    if version_status in {"quarantined", "processing", "review", "uploaded"}:
        return PROJECT_RESOURCE_STATUS_PROCESSING
    return current


def _apply_version_status(
    resource: ProjectResource,
    version: KnowledgeDocumentVersion,
) -> bool:
    new_status = _resource_status_from_version(version.status, current=resource.status)
    if new_status == resource.status and (
        not version.failure_reason or resource.failure_reason == version.failure_reason
    ):
        return False
    resource.status = new_status
    resource.failure_reason = version.failure_reason
    resource.updated_at = datetime.datetime.utcnow()
    return True


async def sync_project_resource_status(
    db: AsyncSession,
    *,
    resource_id: str,
) -> ProjectResource | None:
    """Synchronize a project resource's denormalized status from its
    latest KnowledgeDocumentVersion.

    Called after approve/publish (and as a list catch-up). Returns the
    updated resource or ``None`` if it no longer exists.
    """

    resource = await db.get(ProjectResource, resource_id)
    if resource is None:
        return None

    latest_version = (
        await db.execute(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == resource.document_id)
            .order_by(KnowledgeDocumentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_version is None:
        return resource

    if _apply_version_status(resource, latest_version):
        await db.flush()

    return resource


async def sync_project_resources_for_document(
    db: AsyncSession,
    *,
    document_id: str,
) -> int:
    """Sync every project resource linked to a Knowledge document."""

    doc_id = (document_id or "").strip()
    if not doc_id:
        return 0
    rows = (await db.execute(select(ProjectResource).where(ProjectResource.document_id == doc_id))).scalars().all()
    updated = 0
    for resource in rows:
        synced = await sync_project_resource_status(db, resource_id=resource.id)
        if synced is not None:
            updated += 1
    return updated


async def _latest_versions_by_document(
    db: AsyncSession,
    document_ids: list[str],
) -> dict[str, KnowledgeDocumentVersion]:
    ids = [did for did in document_ids if did]
    if not ids:
        return {}
    rows = (
        (
            await db.execute(
                select(KnowledgeDocumentVersion)
                .where(KnowledgeDocumentVersion.document_id.in_(ids))
                .order_by(
                    KnowledgeDocumentVersion.document_id,
                    KnowledgeDocumentVersion.version_number.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[str, KnowledgeDocumentVersion] = {}
    for row in rows:
        if row.document_id not in latest:
            latest[row.document_id] = row
    return latest


def _resource_to_client(
    resource: ProjectResource,
    *,
    document: KnowledgeDocument | None = None,
    version: KnowledgeDocumentVersion | None = None,
) -> dict:
    return {
        "id": resource.id,
        "projectId": resource.project_id,
        "documentId": resource.document_id,
        "title": resource.title,
        "status": resource.status,
        "versionStatus": version.status if version else None,
        "documentStatus": document.status if document else None,
        "failureReason": resource.failure_reason or (version.failure_reason if version else None),
        "uploadedByUserId": resource.uploaded_by_user_id,
        "createdAt": resource.created_at.isoformat() if resource.created_at else None,
        "updatedAt": resource.updated_at.isoformat() if resource.updated_at else None,
    }


async def list_project_resources(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List project resources visible to any member (or public viewer)."""

    await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="resource.read",
    )

    base = (
        select(ProjectResource, KnowledgeDocument)
        .outerjoin(
            KnowledgeDocument,
            KnowledgeDocument.id == ProjectResource.document_id,
        )
        .where(ProjectResource.project_id == project_id)
    )

    count_stmt = select(func.count()).select_from(ProjectResource).where(ProjectResource.project_id == project_id)

    if status is not None:
        base = base.where(ProjectResource.status == status)
        count_stmt = count_stmt.where(ProjectResource.status == status)

    base = base.order_by(ProjectResource.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(base)).all()
    total = (await db.execute(count_stmt)).scalar() or 0
    versions = await _latest_versions_by_document(db, [resource.document_id for resource, _document in rows])
    dirty = False
    for resource, _document in rows:
        version = versions.get(resource.document_id)
        if version is not None and _apply_version_status(resource, version):
            dirty = True
    if dirty:
        await db.flush()

    items = [
        _resource_to_client(
            resource,
            document=document,
            version=versions.get(resource.document_id),
        )
        for resource, document in rows
    ]
    return items, total


async def get_project_resource(
    db: AsyncSession,
    *,
    project_id: str,
    resource_id: str,
    user: object,
) -> dict | None:
    """Return a single project resource (visible to any member)."""

    await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="resource.read",
    )

    resource = await db.get(ProjectResource, resource_id)
    if resource is None or resource.project_id != project_id:
        return None

    document = await db.get(KnowledgeDocument, resource.document_id)
    versions = await _latest_versions_by_document(db, [resource.document_id])
    version = versions.get(resource.document_id)
    if version is not None and _apply_version_status(resource, version):
        await db.flush()
    return _resource_to_client(
        resource,
        document=document,
        version=version,
    )


async def delete_project_resource(
    db: AsyncSession,
    *,
    project_id: str,
    resource_id: str,
    user: object,
) -> bool:
    """Revoke (soft-delete) a project resource.

    * Owner: can revoke any resource.
    * Contributor: can revoke only resources they uploaded.
    * Viewer: denied.

    The underlying KnowledgeDocument is soft-revoked via the existing
    pipeline so that chunks and object-store entries are purged through
    the normal retention workflow.
    """

    access = await require_capability(
        db,
        project_id=project_id,
        user=user,
        capability="resource.upload",
    )

    resource = await db.get(ProjectResource, resource_id)
    if resource is None or resource.project_id != project_id:
        return False

    is_owner = access.can("resource.manage")
    is_uploader = resource.uploaded_by_user_id == access.user_id
    if not is_owner and not is_uploader:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete resources you uploaded",
        )

    from app.services.knowledge_ingestion_service import soft_revoke_document

    document = await db.get(KnowledgeDocument, resource.document_id)
    if document is not None and document.status != "deleted":
        await soft_revoke_document(
            db,
            document=document,
            actor_user_id=access.user_id,
            reason=f"Project resource deleted by user {access.user_id}",
        )

    resource.status = PROJECT_RESOURCE_STATUS_REVOKED
    resource.updated_at = datetime.datetime.utcnow()
    await db.flush()

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="project.resource.deleted",
        actor_user_id=access.user_id,
        payload={
            "resource_id": resource_id,
            "document_id": resource.document_id,
        },
    )
    return True
