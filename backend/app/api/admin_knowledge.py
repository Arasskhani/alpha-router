"""Governed administrative API for Knowledge ingestion and publication."""

from __future__ import annotations

import datetime
import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_agent_permission
from app.config import get_settings
from app.database import get_db
from app.models.connection import Connection
from app.models.knowledge import (
    IngestionJob,
    KnowledgeBase,
    KnowledgeBaseAccessAssignment,
    KnowledgeConnector,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexVersion,
    KnowledgeRelease,
)
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.agent_governance_service import append_governance_audit_event
from app.services.bounded_io import BoundedIOError, read_upload_bounded
from app.services.knowledge_connector_service import (
    create_connector,
    disable_connector,
    schedule_connector_sync,
    update_connector,
)
from app.services.knowledge_embedding_service import suggested_embedding_dimensions
from app.services.knowledge_hard_delete_service import (
    hard_delete_knowledge_base,
    is_purged_knowledge_base,
)
from app.services.knowledge_ingestion_service import (
    approve_document_version,
    soft_revoke_document,
    submit_document_bytes,
)
from app.services.knowledge_job_service import retry_dead_knowledge_job
from app.services.knowledge_publisher_service import (
    create_knowledge_release,
    submit_release_for_indexing,
)
from app.services.knowledge_retention_service import (
    LIVE_KNOWLEDGE_DOCUMENT_STATUSES,
    is_purged_knowledge_document,
    purge_expired_knowledge_retention,
    schedule_document_purge,
)
from app.services.list_bounds import ADMIN_LIST_HARD_CAP, capped, mark_truncated, split_overflow
from app.services.model_capabilities import model_kinds
from app.services.rbac import user_has_agent_permission
from app.services.resource_access_service import (
    AccessGrant,
    set_knowledge_base_access,
)
from app.services.user_role_service import (
    get_user_role_slugs,
    user_bypasses_maker_checker,
)

router = APIRouter(
    prefix="/api/admin/knowledge",
    tags=["admin-knowledge"],
)


class KnowledgeBaseCreateBody(BaseModel):
    slug: str = Field(min_length=2, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    access_type: str = Field(default="private", pattern=r"^(public|private)$")
    sensitivity: str = Field(
        default="internal",
        pattern=(
            r"^(internal|confidential|hr_confidential|"
            r"legal_privileged|finance_restricted)$"
        ),
    )
    retention_days: int | None = Field(default=None, ge=1, le=36500)


class DocumentReviewBody(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)
    allow_safety_override: bool = False


class DocumentRevokeBody(BaseModel):
    reason: str = Field(min_length=3, max_length=8000)
    purge_now: bool = False


class ConnectorUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|active|paused|failed|archived)$",
    )
    config: dict | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=43200)
    clear_sync_interval: bool = False


class ConnectorDisableBody(BaseModel):
    reason: str = Field(min_length=3, max_length=8000)
    revoke_content: bool = True
    purge_now: bool = False
    archive: bool = True


class KnowledgeBaseDeleteBody(BaseModel):
    reason: str = Field(min_length=3, max_length=8000)
    mode: str = Field(
        default="archive_and_revoke",
        pattern=r"^(archive|archive_and_revoke|purge_later)$",
    )
    purge_now: bool = False


class KnowledgeBaseHardDeleteBody(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=3, max_length=8000)


class ReleaseCreateBody(BaseModel):
    document_version_ids: list[str] = Field(min_length=1, max_length=5000)
    change_summary: str = Field(min_length=3, max_length=8000)


class ReleaseSubmitBody(BaseModel):
    embedding_provider: str = Field(min_length=1, max_length=64)
    embedding_model: str = Field(min_length=1, max_length=512)
    embedding_dimensions: int = Field(gt=0, le=65536)
    embedding_fingerprint: str = Field(min_length=8, max_length=128)
    sparse_profile: dict = Field(default_factory=dict)


class ConnectorCreateBody(BaseModel):
    connector_type: str = Field(pattern=r"^(static|http|s3)$")
    name: str = Field(min_length=1, max_length=255)
    config: dict
    credentials: dict | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=5, le=43200)
    activate: bool = False


class KnowledgeBaseUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|active|suspended|archived)$",
    )
    sensitivity: str | None = Field(
        default=None,
        pattern=(
            r"^(internal|confidential|hr_confidential|"
            r"legal_privileged|finance_restricted)$"
        ),
    )
    # Explicit null clears automatic retention cleanup for this Knowledge Base.
    retention_days: int | None = Field(default=None, ge=1, le=36500)


class AccessGrantBody(BaseModel):
    target_type: str = Field(pattern=r"^(user|group|department|role)$")
    target: int | str
    effect: str = Field(default="allow", pattern=r"^(allow|deny)$")


class KnowledgeAccessBody(BaseModel):
    access_type: str = Field(pattern=r"^(public|private)$")
    grants: list[AccessGrantBody] = Field(default_factory=list, max_length=5000)


def _embedding_fingerprint(provider: str, model: str, dimensions: int) -> str:
    raw = f"{provider.strip().lower()}|{model.strip()}|{int(dimensions)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _version_response(version: KnowledgeDocumentVersion) -> dict:
    return {
        "id": version.id,
        "document_id": version.document_id,
        "version_number": version.version_number,
        "status": version.status,
        "file_name": version.file_name,
        "mime_type": version.mime_type,
        "size_bytes": version.size_bytes,
        "sha256": version.sha256,
        "language": version.language,
        "classification": version.classification,
        "metadata": version.metadata_json or {},
        "failure_reason": version.failure_reason,
        "reviewed_by_user_id": version.reviewed_by_user_id,
        "reviewed_at": version.reviewed_at,
        "created_at": version.created_at,
    }


def _base_response(
    knowledge_base: KnowledgeBase,
    *,
    document_count: int = 0,
    release_count: int = 0,
    failed_job_count: int = 0,
) -> dict:
    return {
        "id": knowledge_base.id,
        "slug": knowledge_base.slug,
        "name": knowledge_base.name,
        "description": knowledge_base.description,
        "status": knowledge_base.status,
        "access_type": knowledge_base.access_type,
        "sensitivity": knowledge_base.sensitivity,
        "acl_version": knowledge_base.acl_version,
        "owner_user_id": knowledge_base.owner_user_id,
        "owner_group_id": knowledge_base.owner_group_id,
        "retention_days": knowledge_base.retention_days,
        "document_count": document_count,
        "release_count": release_count,
        "failed_job_count": failed_job_count,
        "created_at": knowledge_base.created_at,
        "updated_at": knowledge_base.updated_at,
    }


@router.get("/bases")
async def list_knowledge_bases(
    response: Response = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("knowledge.read")),
):
    fetched, truncated = split_overflow(
        (await db.execute(capped(select(KnowledgeBase).order_by(KnowledgeBase.name), cap=ADMIN_LIST_HARD_CAP)))
        .scalars()
        .all(),
        cap=ADMIN_LIST_HARD_CAP,
    )
    mark_truncated(response, truncated, cap=ADMIN_LIST_HARD_CAP)
    bases = [knowledge_base for knowledge_base in fetched if not is_purged_knowledge_base(knowledge_base)]
    if not bases:
        return []
    ids = [knowledge_base.id for knowledge_base in bases]
    document_counts = dict(
        (
            await db.execute(
                select(
                    KnowledgeDocument.knowledge_base_id,
                    func.count(KnowledgeDocument.id),
                )
                .where(
                    KnowledgeDocument.knowledge_base_id.in_(ids),
                    KnowledgeDocument.status.in_(LIVE_KNOWLEDGE_DOCUMENT_STATUSES),
                )
                .group_by(KnowledgeDocument.knowledge_base_id)
            )
        ).all()
    )
    release_counts = dict(
        (
            await db.execute(
                select(
                    KnowledgeRelease.knowledge_base_id,
                    func.count(KnowledgeRelease.id),
                )
                .where(KnowledgeRelease.knowledge_base_id.in_(ids))
                .group_by(KnowledgeRelease.knowledge_base_id)
            )
        ).all()
    )
    failed_counts = dict(
        (
            await db.execute(
                select(
                    IngestionJob.knowledge_base_id,
                    func.count(IngestionJob.id),
                )
                .where(
                    IngestionJob.knowledge_base_id.in_(ids),
                    IngestionJob.status == "dead",
                )
                .group_by(IngestionJob.knowledge_base_id)
            )
        ).all()
    )
    return [
        _base_response(
            knowledge_base,
            document_count=int(document_counts.get(knowledge_base.id, 0)),
            release_count=int(release_counts.get(knowledge_base.id, 0)),
            failed_job_count=int(failed_counts.get(knowledge_base.id, 0)),
        )
        for knowledge_base in bases
    ]


@router.get("/bases/{knowledge_base_id}")
async def get_knowledge_base(
    knowledge_base_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("knowledge.read")),
):
    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or is_purged_knowledge_base(knowledge_base):
        raise HTTPException(404, "Knowledge Base not found")
    documents = [
        document
        for document in (
            (
                await db.execute(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.knowledge_base_id == knowledge_base.id)
                    .order_by(KnowledgeDocument.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )
        if not is_purged_knowledge_document(document)
    ]
    versions = (
        (
            await db.execute(
                select(KnowledgeDocumentVersion)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeDocumentVersion.document_id,
                )
                .where(KnowledgeDocument.knowledge_base_id == knowledge_base.id)
                .order_by(
                    KnowledgeDocumentVersion.created_at.desc(),
                    KnowledgeDocumentVersion.version_number.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    versions_by_document: dict[str, list[dict]] = {}
    for version in versions:
        versions_by_document.setdefault(version.document_id, []).append(_version_response(version))
    connectors = (
        (
            await db.execute(
                select(KnowledgeConnector)
                .where(KnowledgeConnector.knowledge_base_id == knowledge_base.id)
                .order_by(KnowledgeConnector.name)
            )
        )
        .scalars()
        .all()
    )
    releases = (
        (
            await db.execute(
                select(KnowledgeRelease)
                .where(KnowledgeRelease.knowledge_base_id == knowledge_base.id)
                .order_by(KnowledgeRelease.version_number.desc())
            )
        )
        .scalars()
        .all()
    )
    indexes = (
        (
            await db.execute(
                select(KnowledgeIndexVersion)
                .where(KnowledgeIndexVersion.knowledge_base_id == knowledge_base.id)
                .order_by(KnowledgeIndexVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )
    jobs = (
        (
            await db.execute(
                select(IngestionJob)
                .where(IngestionJob.knowledge_base_id == knowledge_base.id)
                .order_by(IngestionJob.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    payload = _base_response(
        knowledge_base,
        document_count=len(documents),
        release_count=len(releases),
        failed_job_count=sum(1 for job in jobs if job.status == "dead"),
    )
    payload.update(
        {
            "documents": [
                {
                    "id": document.id,
                    "canonical_key": document.canonical_key,
                    "title": document.title,
                    "status": document.status,
                    "created_at": document.created_at,
                    "updated_at": document.updated_at,
                    "versions": versions_by_document.get(document.id, []),
                }
                for document in documents
            ],
            "connectors": [
                {
                    "id": connector.id,
                    "name": connector.name,
                    "connector_type": connector.connector_type,
                    "status": connector.status,
                    "config": connector.config_json or {},
                    "has_credentials": bool(connector.credentials_encrypted),
                    "sync_interval_minutes": connector.sync_interval_minutes,
                    "last_synced_at": connector.last_synced_at,
                    "updated_at": connector.updated_at,
                }
                for connector in connectors
            ],
            "releases": [
                {
                    "id": release.id,
                    "version_number": release.version_number,
                    "status": release.status,
                    "fingerprint": release.fingerprint,
                    "change_summary": release.change_summary,
                    "manifest": release.manifest_json or {},
                    "created_at": release.created_at,
                    "published_at": release.published_at,
                }
                for release in releases
            ],
            "indexes": [
                {
                    "id": index.id,
                    "release_id": index.release_id,
                    "version_number": index.version_number,
                    "status": index.status,
                    "embedding_provider": index.embedding_provider,
                    "embedding_model": index.embedding_model,
                    "expected_point_count": index.expected_point_count,
                    "indexed_point_count": index.indexed_point_count,
                    "collection_alias": index.collection_alias,
                    "created_at": index.created_at,
                    "activated_at": index.activated_at,
                    "failure_reason": index.failure_reason,
                }
                for index in indexes
            ],
            "jobs": [
                {
                    "id": job.id,
                    "job_type": job.job_type,
                    "status": job.status,
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "error_code": job.error_code,
                    "error_message": job.error_message,
                    "index_version_id": job.index_version_id,
                    "document_version_id": job.document_version_id,
                    "created_at": job.created_at,
                    "completed_at": job.completed_at,
                }
                for job in jobs
            ],
        }
    )
    return payload


@router.patch("/bases/{knowledge_base_id}")
async def update_knowledge_base(
    knowledge_base_id: str,
    body: KnowledgeBaseUpdateBody,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("knowledge.edit")),
):
    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(404, "Knowledge Base not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = " ".join((changes["name"] or "").split())
    if "description" in changes:
        changes["description"] = (changes["description"] or "").strip() or None
    for key, value in changes.items():
        setattr(knowledge_base, key, value)
    knowledge_base.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    await db.commit()
    return _base_response(knowledge_base)


@router.post("/bases/{knowledge_base_id}/retention/cleanup", status_code=202)
async def cleanup_knowledge_base_retention(
    knowledge_base_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.purge")),
):
    """Purge revoked/deleted docs past this KB's retention window immediately."""

    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(404, "Knowledge Base not found")
    if knowledge_base.retention_days is None:
        raise HTTPException(
            400,
            "Set retention days on this Knowledge Base before running cleanup.",
        )
    result = await purge_expired_knowledge_retention(
        db,
        actor_user_id=user.id,
        knowledge_base_id=knowledge_base.id,
    )
    await db.commit()
    return {
        "knowledge_base_id": knowledge_base.id,
        "retention_days": knowledge_base.retention_days,
        **result,
    }


@router.get("/bases/{knowledge_base_id}/access")
async def get_knowledge_access(
    knowledge_base_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("knowledge.read")),
):
    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(404, "Knowledge Base not found")
    rows = (
        (
            await db.execute(
                select(KnowledgeBaseAccessAssignment)
                .where(KnowledgeBaseAccessAssignment.knowledge_base_id == knowledge_base.id)
                .order_by(KnowledgeBaseAccessAssignment.id)
            )
        )
        .scalars()
        .all()
    )
    grants = []
    for row in rows:
        if row.user_id is not None:
            target_type, target = "user", row.user_id
        elif row.group_id is not None:
            target_type, target = "group", row.group_id
        elif row.department is not None:
            target_type, target = "department", row.department
        else:
            target_type, target = "role", row.role_slug
        grants.append(
            {
                "id": row.id,
                "target_type": target_type,
                "target": target,
                "effect": row.effect,
            }
        )
    return {
        "access_type": knowledge_base.access_type,
        "acl_version": knowledge_base.acl_version,
        "grants": grants,
    }


@router.put("/bases/{knowledge_base_id}/access")
async def replace_knowledge_access(
    knowledge_base_id: str,
    body: KnowledgeAccessBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.access.manage")),
):
    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(404, "Knowledge Base not found")
    try:
        await set_knowledge_base_access(
            db,
            knowledge_base,
            access_type=body.access_type,
            grants=[
                AccessGrant(
                    target_type=grant.target_type,
                    target=grant.target,
                    effect=grant.effect,
                )
                for grant in body.grants
            ],
            assigned_by_user_id=user.id,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return await get_knowledge_access(knowledge_base_id, db, user)


@router.post("/bases")
async def create_knowledge_base(
    body: KnowledgeBaseCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.create")),
):
    existing = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.slug == body.slug))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "Knowledge Base slug already exists")
    knowledge_base = KnowledgeBase(
        id=str(uuid.uuid4()),
        slug=body.slug,
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        status="active",
        access_type=body.access_type,
        sensitivity=body.sensitivity,
        owner_user_id=user.id,
        retention_days=body.retention_days,
        created_by_user_id=user.id,
    )
    db.add(knowledge_base)
    await db.commit()
    return {
        "id": knowledge_base.id,
        "slug": knowledge_base.slug,
        "name": knowledge_base.name,
        "status": knowledge_base.status,
        "access_type": knowledge_base.access_type,
        "sensitivity": knowledge_base.sensitivity,
    }


@router.post("/bases/{knowledge_base_id}/documents", status_code=202)
async def upload_document(
    knowledge_base_id: str,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    canonical_key: str | None = Form(default=None),
    classification: str | None = Form(default=None),
    authority: str = Form(default="reference"),
    language: str | None = Form(default=None),
    jurisdiction: str | None = Form(default=None),
    effective_from: datetime.datetime | None = Form(default=None),
    effective_to: datetime.datetime | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.documents.write")),
):
    try:
        data = await read_upload_bounded(
            file,
            max_bytes=get_settings().knowledge_max_upload_bytes,
        )
        result = await submit_document_bytes(
            db,
            knowledge_base_id=knowledge_base_id,
            file_name=file.filename or "document",
            declared_mime=file.content_type,
            data=data,
            uploaded_by_user_id=user.id,
            title=title,
            canonical_key=canonical_key,
            classification=classification,
            authority=authority,
            language=language,
            jurisdiction=jurisdiction,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        await db.commit()
    except (BoundedIOError, ValueError) as exc:
        await db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(503, "Knowledge object storage is unavailable") from exc
    return {
        "document_id": result.document.id,
        "document_version": _version_response(result.version),
        "job_id": result.job.id if result.job is not None else None,
        "duplicate": result.duplicate,
    }


@router.post("/document-versions/{document_version_id}/approve")
async def approve_document(
    document_version_id: str,
    body: DocumentReviewBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.review")),
):
    try:
        version = await approve_document_version(
            db,
            document_version_id=document_version_id,
            reviewer_user_id=user.id,
            reason=body.reason,
            allow_safety_override=body.allow_safety_override,
            allow_self_review=await user_bypasses_maker_checker(db, user.id),
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return _version_response(version)


@router.post("/documents/{document_id}/revoke")
async def revoke_document(
    document_id: str,
    body: DocumentRevokeBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.documents.write")),
):
    if body.purge_now:
        slugs = await get_user_role_slugs(db, user.id)
        if not user_has_agent_permission(slugs, "knowledge.purge"):
            raise HTTPException(403, "Missing Agent Platform permission: knowledge.purge")
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    try:
        version_ids = await soft_revoke_document(
            db,
            document=document,
            actor_user_id=user.id,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await append_governance_audit_event(
        db,
        event_type="governance.knowledge.document.revoked",
        resource_type="knowledge_document",
        resource_id=document.id,
        actor_user_id=user.id,
        payload={
            "knowledge_base_id": document.knowledge_base_id,
            "reason": body.reason,
            "version_count": len(version_ids),
            "purge_now": bool(body.purge_now),
        },
    )
    purge_payload = {
        "requested": False,
        "job_ids": [],
        "held": False,
        "scheduled_versions": 0,
    }
    if body.purge_now:
        purge_result = await schedule_document_purge(
            db,
            document=document,
            actor_user_id=user.id,
            reason="purge_now",
        )
        purge_payload = {
            "requested": True,
            "job_ids": list(purge_result.get("job_ids") or []),
            "held": bool(purge_result.get("held")),
            "scheduled_versions": int(purge_result.get("scheduled_versions") or 0),
        }
    await db.commit()
    status_code_hint = 202 if purge_payload["requested"] else 200
    del status_code_hint  # response body carries async purge state
    return {
        "ok": True,
        "document_id": document.id,
        "status": document.status,
        "revoked_at": document.revoked_at,
        "revoked_version_ids": version_ids,
        "purge": purge_payload,
    }


@router.get("/embedding-models")
async def list_knowledge_embedding_models(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("knowledge.read")),
):
    rows = (
        await db.execute(
            select(AIModel, Connection)
            .join(Connection, Connection.id == AIModel.connection_id)
            .where(
                AIModel.is_enabled.is_(True),
                AIModel.admin_disabled.is_(False),
                Connection.is_active.is_(True),
            )
            .order_by(AIModel.external_id)
        )
    ).all()
    models = []
    for model, connection in rows:
        provider = (connection.provider_type or model.provider_type or "").strip().lower()
        kinds = model_kinds(
            external_id=model.external_id or "",
            is_image_model=bool(model.is_image_model),
            is_video_model=bool(getattr(model, "is_video_model", False)),
            pricing_raw=model.pricing_raw,
            provider_type=provider,
        )
        if "embeddings" not in kinds:
            continue
        dimensions = suggested_embedding_dimensions(model.external_id or "")
        models.append(
            {
                "id": model.id,
                "external_id": model.external_id,
                "display_name": model.display_name,
                "provider": provider,
                "suggested_dimensions": dimensions,
                "embedding_fingerprint": _embedding_fingerprint(
                    provider,
                    model.external_id or "",
                    dimensions,
                ),
            }
        )
    return models


@router.post("/bases/{knowledge_base_id}/releases")
async def create_release(
    knowledge_base_id: str,
    body: ReleaseCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.publish")),
):
    try:
        release = await create_knowledge_release(
            db,
            knowledge_base_id=knowledge_base_id,
            document_version_ids=body.document_version_ids,
            created_by_user_id=user.id,
            change_summary=body.change_summary,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {
        "id": release.id,
        "version_number": release.version_number,
        "status": release.status,
        "fingerprint": release.fingerprint,
        "manifest": release.manifest_json,
    }


@router.post("/releases/{release_id}/submit", status_code=202)
async def submit_release(
    release_id: str,
    body: ReleaseSubmitBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.publish")),
):
    try:
        index = await submit_release_for_indexing(
            db,
            release_id=release_id,
            submitted_by_user_id=user.id,
            embedding_provider=body.embedding_provider,
            embedding_model=body.embedding_model,
            embedding_dimensions=body.embedding_dimensions,
            embedding_fingerprint=body.embedding_fingerprint,
            sparse_profile=body.sparse_profile,
            allow_self_submit=await user_bypasses_maker_checker(db, user.id),
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {
        "index_version_id": index.id,
        "status": index.status,
        "collection_name": index.collection_name,
        "expected_point_count": index.expected_point_count,
        "fingerprint": index.fingerprint,
    }


@router.post("/bases/{knowledge_base_id}/connectors")
async def add_connector(
    knowledge_base_id: str,
    body: ConnectorCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.connectors.manage")),
):
    try:
        connector = await create_connector(
            db,
            knowledge_base_id=knowledge_base_id,
            connector_type=body.connector_type,
            name=body.name,
            config=body.config,
            credentials=body.credentials,
            created_by_user_id=user.id,
            sync_interval_minutes=body.sync_interval_minutes,
            activate=body.activate,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return {
        "id": connector.id,
        "name": connector.name,
        "connector_type": connector.connector_type,
        "status": connector.status,
        "sync_interval_minutes": connector.sync_interval_minutes,
    }


@router.patch("/connectors/{connector_id}")
async def patch_connector(
    connector_id: str,
    body: ConnectorUpdateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.connectors.manage")),
):
    try:
        connector = await update_connector(
            db,
            connector_id=connector_id,
            actor_user_id=user.id,
            name=body.name,
            status=body.status,
            config=body.config,
            sync_interval_minutes=body.sync_interval_minutes,
            clear_sync_interval=body.clear_sync_interval,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return {
        "id": connector.id,
        "name": connector.name,
        "connector_type": connector.connector_type,
        "status": connector.status,
        "config": connector.config_json or {},
        "sync_interval_minutes": connector.sync_interval_minutes,
        "updated_at": connector.updated_at,
    }


@router.post("/connectors/{connector_id}/disable", status_code=202)
async def disable_connector_endpoint(
    connector_id: str,
    body: ConnectorDisableBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.connectors.manage")),
):
    if body.purge_now:
        slugs = await get_user_role_slugs(db, user.id)
        if not user_has_agent_permission(slugs, "knowledge.purge"):
            raise HTTPException(403, "Missing Agent Platform permission: knowledge.purge")
    try:
        connector, revoked_documents = await disable_connector(
            db,
            connector_id=connector_id,
            actor_user_id=user.id,
            reason=body.reason,
            revoke_content=body.revoke_content,
            archive=body.archive,
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    job_ids: list[str] = []
    if body.purge_now:
        for document in revoked_documents:
            result = await schedule_document_purge(
                db,
                document=document,
                actor_user_id=user.id,
                reason="connector_disable_purge",
            )
            job_ids.extend(str(item) for item in (result.get("job_ids") or []))
    await db.commit()
    return {
        "connector_id": connector.id,
        "status": connector.status,
        "revoked_document_count": len(revoked_documents),
        "purge": {
            "requested": bool(body.purge_now),
            "job_ids": job_ids,
        },
    }


@router.post("/bases/{knowledge_base_id}/delete", status_code=202)
async def delete_knowledge_base(
    knowledge_base_id: str,
    body: KnowledgeBaseDeleteBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.edit")),
):
    if body.purge_now:
        slugs = await get_user_role_slugs(db, user.id)
        if not user_has_agent_permission(slugs, "knowledge.purge"):
            raise HTTPException(403, "Missing Agent Platform permission: knowledge.purge")
    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(404, "Knowledge Base not found")
    knowledge_base.status = "archived"
    knowledge_base.updated_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    revoked_document_count = 0
    disabled_connector_count = 0
    job_ids: list[str] = []
    if body.mode in {"archive_and_revoke", "purge_later"}:
        connectors = (
            (
                await db.execute(
                    select(KnowledgeConnector).where(
                        KnowledgeConnector.knowledge_base_id == knowledge_base.id,
                        KnowledgeConnector.status != "archived",
                    )
                )
            )
            .scalars()
            .all()
        )
        for connector in connectors:
            _, revoked_documents = await disable_connector(
                db,
                connector_id=connector.id,
                actor_user_id=user.id,
                reason=body.reason,
                revoke_content=True,
                archive=True,
            )
            disabled_connector_count += 1
            revoked_document_count += len(revoked_documents)
        documents = (
            (
                await db.execute(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.knowledge_base_id == knowledge_base.id,
                        KnowledgeDocument.status.notin_(("revoked", "deleted")),
                    )
                )
            )
            .scalars()
            .all()
        )
        for document in documents:
            await soft_revoke_document(
                db,
                document=document,
                actor_user_id=user.id,
                reason=body.reason,
            )
            revoked_document_count += 1
        if body.purge_now:
            all_docs = (
                (
                    await db.execute(
                        select(KnowledgeDocument).where(
                            KnowledgeDocument.knowledge_base_id == knowledge_base.id,
                            KnowledgeDocument.status.in_(("revoked", "deleted")),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for document in all_docs:
                result = await schedule_document_purge(
                    db,
                    document=document,
                    actor_user_id=user.id,
                    reason="knowledge_base_delete_purge",
                )
                job_ids.extend(str(item) for item in (result.get("job_ids") or []))
    elif body.purge_now:
        documents = (
            (
                await db.execute(
                    select(KnowledgeDocument).where(
                        KnowledgeDocument.knowledge_base_id == knowledge_base.id,
                        KnowledgeDocument.status.in_(("revoked", "deleted")),
                    )
                )
            )
            .scalars()
            .all()
        )
        for document in documents:
            result = await schedule_document_purge(
                db,
                document=document,
                actor_user_id=user.id,
                reason="knowledge_base_delete_purge",
            )
            job_ids.extend(str(item) for item in (result.get("job_ids") or []))
    await append_governance_audit_event(
        db,
        event_type="governance.knowledge.base.deleted",
        resource_type="knowledge_base",
        resource_id=knowledge_base.id,
        actor_user_id=user.id,
        payload={
            "mode": body.mode,
            "reason": body.reason,
            "purge_now": bool(body.purge_now),
            "revoked_document_count": revoked_document_count,
            "disabled_connector_count": disabled_connector_count,
        },
    )
    await db.commit()
    return {
        "knowledge_base_id": knowledge_base.id,
        "status": knowledge_base.status,
        "revoked_document_count": revoked_document_count,
        "disabled_connector_count": disabled_connector_count,
        "purge": {
            "requested": bool(body.purge_now),
            "job_ids": job_ids,
        },
    }


@router.post("/bases/{knowledge_base_id}/hard-delete", status_code=202)
async def hard_delete_knowledge_base_endpoint(
    knowledge_base_id: str,
    body: KnowledgeBaseHardDeleteBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.purge")),
):
    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or is_purged_knowledge_base(knowledge_base):
        raise HTTPException(404, "Knowledge Base not found")
    try:
        result = await hard_delete_knowledge_base(
            db,
            knowledge_base=knowledge_base,
            confirm_name=body.confirm_name,
            actor_user_id=user.id,
            reason=body.reason,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return result


@router.post("/connectors/{connector_id}/sync", status_code=202)
async def sync_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.sync.run")),
):
    try:
        run = await schedule_connector_sync(
            db,
            connector_id=connector_id,
            requested_by_user_id=user.id,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"sync_run_id": run.id, "status": run.status}


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("operations.read")),
):
    job = await db.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(404, "Knowledge job not found")
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


@router.post("/indexes/{index_version_id}/retry", status_code=202)
async def retry_index_build(
    index_version_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("knowledge.publish")),
):
    index = await db.get(KnowledgeIndexVersion, index_version_id)
    if index is None:
        raise HTTPException(404, "Knowledge index not found")
    if index.status != "failed":
        raise HTTPException(409, "Only a failed Knowledge index can be retried")
    dead_job = (
        await db.execute(
            select(IngestionJob)
            .where(
                IngestionJob.index_version_id == index.id,
                IngestionJob.job_type == "knowledge.index.build",
                IngestionJob.status == "dead",
            )
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if dead_job is None:
        raise HTTPException(409, "No dead index-build job found to retry")
    index.status = "planned"
    index.failure_reason = None
    index.indexed_point_count = 0
    try:
        job = await retry_dead_knowledge_job(db, job_id=dead_job.id)
        await append_governance_audit_event(
            db,
            event_type="governance.knowledge.index.retry",
            resource_type="knowledge_index_version",
            resource_id=index.id,
            actor_user_id=user.id,
            payload={"job_id": job.id},
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job.id, "index_version_id": index.id, "status": "pending"}


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("operations.retry")),
):
    try:
        job = await retry_dead_knowledge_job(db, job_id=job_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(409, str(exc)) from exc
    return {"id": job.id, "status": job.status}
