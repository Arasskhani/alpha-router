"""Secure Knowledge upload, extraction, review, and quarantine lifecycle."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import delete, func, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.knowledge import (
    IngestionJob,
    KnowledgeAuditEvent,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from app.services.knowledge_chunking_service import CHUNKER_VERSION, chunk_segments
from app.services.knowledge_crypto_service import (
    chunk_plaintext_hash,
    decrypt_bytes,
    encrypt_bytes,
    encrypt_text,
    plaintext_sha256,
)
from app.services.knowledge_file_service import (
    UnsafeDocumentError,
    validate_document,
)
from app.services.knowledge_job_service import enqueue_knowledge_job
from app.services.knowledge_object_store import (
    KnowledgeObjectStoreProtocol,
    default_knowledge_object_store,
)
from app.services.knowledge_parser_sandbox import parse_document_in_sandbox
from app.services.knowledge_safety_service import scan_knowledge_text
from app.services.malware_scan_service import MalwareScanResult, scan_bytes

DOCUMENT_PROCESS_JOB = "document.scan_extract"
OBJECT_PURGE_JOB = "object.purge"
PARSER_VERSION = "alpharouter-parser-v1"

MalwareScanner = Callable[[bytes], Awaitable[MalwareScanResult]]


@dataclass(frozen=True)
class DocumentSubmission:
    document: KnowledgeDocument
    version: KnowledgeDocumentVersion
    job: IngestionJob | None
    duplicate: bool


def _safe_file_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = PurePath(normalized.replace("\\", "/")).name
    normalized = "".join(char for char in normalized if char.isprintable() and char not in {"/", "\\"}).strip(" .")
    if not normalized:
        raise ValueError("A valid file name is required")
    return normalized[:512]


def _safe_canonical_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().lower()
    normalized = re.sub(r"[\x00-\x1f\x7f]+", "", normalized)
    normalized = normalized.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        raise ValueError("A valid canonical key is required")
    return normalized[:512]


def _infer_language(texts: tuple[str, ...]) -> str | None:
    sample = " ".join(texts)[:20_000]
    if not sample:
        return None
    arabic = len(re.findall(r"[\u0600-\u06ff]", sample))
    latin = len(re.findall(r"[A-Za-z]", sample))
    if arabic > max(20, latin * 2):
        return "fa"
    if latin > max(20, arabic * 2):
        return "en"
    return None


def _quarantine_key(knowledge_base_id: str, version_id: str) -> str:
    prefix = get_settings().knowledge_quarantine_prefix.strip("/")
    return f"{prefix}/{knowledge_base_id}/{version_id}.akn"


def _trusted_key(
    knowledge_base_id: str,
    document_id: str,
    version_id: str,
    digest: str,
) -> str:
    prefix = get_settings().knowledge_object_prefix.strip("/")
    return f"{prefix}/{knowledge_base_id}/{document_id}/{version_id}/{digest}.akn"


def _object_aad(version_id: str) -> str:
    return f"document-version:{version_id}"


async def record_knowledge_audit(
    db: AsyncSession,
    *,
    knowledge_base_id: str | None,
    document_id: str | None,
    event_type: str,
    actor_user_id: int | None,
    reason: str | None = None,
    payload: dict | None = None,
) -> KnowledgeAuditEvent:
    event = KnowledgeAuditEvent(
        id=str(uuid.uuid4()),
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        reason=reason,
        payload_json=payload or {},
    )
    db.add(event)
    await db.flush()
    return event


async def submit_document_bytes(
    db: AsyncSession,
    *,
    knowledge_base_id: str,
    file_name: str,
    declared_mime: str | None,
    data: bytes,
    uploaded_by_user_id: int | None,
    title: str | None = None,
    canonical_key: str | None = None,
    source_type: str = "upload",
    source_uri: str | None = None,
    classification: str | None = None,
    authority: str = "reference",
    language: str | None = None,
    jurisdiction: str | None = None,
    effective_from: datetime.datetime | None = None,
    effective_to: datetime.datetime | None = None,
    object_store: KnowledgeObjectStoreProtocol | None = None,
) -> DocumentSubmission:
    """Validate and quarantine immutable source bytes, then enqueue processing."""

    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or knowledge_base.status in {"suspended", "archived"}:
        raise ValueError("Knowledge Base is not available for ingestion")
    safe_name = _safe_file_name(file_name)
    validation = validate_document(
        file_name=safe_name,
        data=data,
        claimed_mime_type=declared_mime,
    )
    digest = plaintext_sha256(data)
    canonical = _safe_canonical_key(canonical_key or safe_name)
    if db.get_bind().dialect.name == "postgresql":
        lock_digest = hashlib.sha256(f"{knowledge_base_id}\0{canonical}".encode()).digest()
        lock_key = int.from_bytes(lock_digest[:8], "big", signed=True)
        await db.execute(
            sql_text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

    document = (
        await db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == knowledge_base_id,
                KnowledgeDocument.canonical_key == canonical,
            )
        )
    ).scalar_one_or_none()
    if document is not None:
        existing = (
            await db.execute(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == document.id,
                    KnowledgeDocumentVersion.sha256 == digest,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            job = (
                await db.execute(
                    select(IngestionJob)
                    .where(
                        IngestionJob.document_version_id == existing.id,
                        IngestionJob.job_type == DOCUMENT_PROCESS_JOB,
                    )
                    .order_by(IngestionJob.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return DocumentSubmission(document, existing, job, True)
        document_statement = select(KnowledgeDocument).where(KnowledgeDocument.id == document.id)
        if db.get_bind().dialect.name == "postgresql":
            document_statement = document_statement.with_for_update()
        document = (await db.execute(document_statement)).scalar_one()
    else:
        document = KnowledgeDocument(
            id=str(uuid.uuid4()),
            knowledge_base_id=knowledge_base_id,
            canonical_key=canonical,
            title=(title or safe_name).strip()[:512],
            status="draft",
            created_by_user_id=uploaded_by_user_id,
        )
        db.add(document)
        await db.flush()

    version_number = (
        int(
            (
                await db.execute(
                    select(func.max(KnowledgeDocumentVersion.version_number)).where(
                        KnowledgeDocumentVersion.document_id == document.id
                    )
                )
            ).scalar()
            or 0
        )
        + 1
    )
    version_id = str(uuid.uuid4())
    storage_key = _quarantine_key(knowledge_base_id, version_id)
    metadata = {
        "validation": {
            "detected_format": validation.format_name,
            "detected_mime": validation.mime_type,
        },
        "encryption": {"profile": "AES-256-GCM", "envelope_version": 1},
        "malware_scan": {"status": "pending"},
        "prompt_injection_scan": {"status": "pending"},
    }
    version = KnowledgeDocumentVersion(
        id=version_id,
        document_id=document.id,
        version_number=version_number,
        status="quarantined",
        storage_key=storage_key,
        file_name=safe_name,
        mime_type=validation.mime_type,
        size_bytes=len(data),
        sha256=digest,
        source_type=source_type[:32],
        source_uri=source_uri,
        language=language,
        classification=(classification or knowledge_base.sensitivity)[:64],
        authority=authority[:32],
        jurisdiction=jurisdiction,
        effective_from=effective_from,
        effective_to=effective_to,
        metadata_json=metadata,
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.add(version)
    await db.flush()

    store = object_store or default_knowledge_object_store()
    encrypted = await asyncio.to_thread(
        encrypt_bytes,
        data,
        associated_data=_object_aad(version_id),
    )
    await store.put(storage_key, encrypted)

    job = await enqueue_knowledge_job(
        db,
        knowledge_base_id=knowledge_base_id,
        document_version_id=version.id,
        job_type=DOCUMENT_PROCESS_JOB,
        idempotency_key=f"document-process:{version.id}:{version.sha256}",
        payload={"document_version_id": version.id},
    )
    await record_knowledge_audit(
        db,
        knowledge_base_id=knowledge_base_id,
        document_id=document.id,
        event_type="document.version.quarantined",
        actor_user_id=uploaded_by_user_id,
        payload={
            "document_version_id": version.id,
            "sha256": digest,
            "size_bytes": len(data),
            "format": validation.format_name,
        },
    )
    return DocumentSubmission(document, version, job, False)


async def _schedule_purge(
    db: AsyncSession,
    *,
    knowledge_base_id: str,
    document_version_id: str,
    storage_key: str,
    purpose: str,
) -> None:
    await enqueue_knowledge_job(
        db,
        knowledge_base_id=knowledge_base_id,
        document_version_id=document_version_id,
        job_type=OBJECT_PURGE_JOB,
        idempotency_key=f"object-purge:{document_version_id}:{hashlib.sha256(storage_key.encode()).hexdigest()}",
        payload={"storage_key": storage_key, "purpose": purpose},
    )


async def process_document_version(
    db: AsyncSession,
    job: IngestionJob,
    *,
    object_store: KnowledgeObjectStoreProtocol | None = None,
    malware_scanner: MalwareScanner = scan_bytes,
) -> None:
    version_id = str(job.document_version_id or dict(job.payload_json or {}).get("document_version_id") or "")
    version = await db.get(KnowledgeDocumentVersion, version_id)
    if version is None:
        raise ValueError(f"Document version not found: {version_id}")
    document = await db.get(KnowledgeDocument, version.document_id)
    if document is None:
        raise ValueError(f"Document not found: {version.document_id}")
    if version.status in {"review", "published", "superseded", "revoked"}:
        return

    version.status = "processing"
    await db.flush()
    store = object_store or default_knowledge_object_store()
    settings = get_settings()
    envelope = await store.get(
        version.storage_key,
        max_bytes=settings.knowledge_max_upload_bytes + 64 * 1024,
    )
    data = await asyncio.to_thread(
        decrypt_bytes,
        envelope,
        associated_data=_object_aad(version.id),
    )
    if len(data) != version.size_bytes or plaintext_sha256(data) != version.sha256:
        version.status = "failed"
        version.failure_reason = "Source integrity verification failed"
        version.metadata_json = {
            **dict(version.metadata_json or {}),
            "integrity": {"status": "failed"},
        }
        await record_knowledge_audit(
            db,
            knowledge_base_id=job.knowledge_base_id,
            document_id=document.id,
            event_type="document.version.integrity_failed",
            actor_user_id=None,
            payload={"document_version_id": version.id},
        )
        return

    try:
        validation = validate_document(
            file_name=version.file_name,
            data=data,
            claimed_mime_type=version.mime_type,
        )
    except UnsafeDocumentError as exc:
        version.status = "failed"
        version.failure_reason = str(exc)[:8000]
        await _schedule_purge(
            db,
            knowledge_base_id=job.knowledge_base_id,
            document_version_id=version.id,
            storage_key=version.storage_key,
            purpose="invalid-source",
        )
        return

    malware = await malware_scanner(data)
    metadata = dict(version.metadata_json or {})
    metadata["malware_scan"] = {
        "status": "skipped" if malware.skipped else ("clean" if malware.clean else "infected"),
        "signature": malware.signature,
    }
    version.metadata_json = metadata
    if not malware.clean:
        version.status = "failed"
        version.failure_reason = f"Malware detected: {malware.signature or 'unknown'}"
        await _schedule_purge(
            db,
            knowledge_base_id=job.knowledge_base_id,
            document_version_id=version.id,
            storage_key=version.storage_key,
            purpose="malware",
        )
        await record_knowledge_audit(
            db,
            knowledge_base_id=job.knowledge_base_id,
            document_id=document.id,
            event_type="document.version.malware_rejected",
            actor_user_id=None,
            payload={
                "document_version_id": version.id,
                "signature": malware.signature,
            },
        )
        return

    try:
        parsed_document = await parse_document_in_sandbox(
            data,
            validation,
        )
        parsed = parsed_document.segments
        if not parsed:
            raise UnsafeDocumentError("Document did not contain extractable text")
    except UnsafeDocumentError as exc:
        version.status = "failed"
        version.failure_reason = str(exc)[:8000]
        await _schedule_purge(
            db,
            knowledge_base_id=job.knowledge_base_id,
            document_version_id=version.id,
            storage_key=version.storage_key,
            purpose="parser-rejected",
        )
        return

    safety = scan_knowledge_text(tuple(segment.text for segment in parsed))
    drafts = chunk_segments(parsed)
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_version_id == version.id))
    chunk_ids = {draft.local_key: str(uuid.uuid5(uuid.UUID(version.id), draft.local_key)) for draft in drafts}
    for index, draft in enumerate(drafts):
        chunk_id = chunk_ids[draft.local_key]
        plaintext_digest = chunk_plaintext_hash(index, draft.text)
        encrypted_content = await asyncio.to_thread(
            encrypt_text,
            draft.text,
            associated_data=f"knowledge-chunk:{chunk_id}",
        )
        db.add(
            KnowledgeChunk(
                id=chunk_id,
                document_version_id=version.id,
                parent_chunk_id=(chunk_ids[draft.parent_local_key] if draft.parent_local_key is not None else None),
                chunk_index=index,
                content=encrypted_content,
                content_hash=plaintext_digest,
                token_count=max(1, len(re.findall(r"\w+|[^\w\s]", draft.text))),
                page_number=draft.page_number,
                section=draft.section,
                language=version.language,
                metadata_json={
                    "kind": draft.kind,
                    "chunker_version": CHUNKER_VERSION,
                    "encrypted": True,
                },
            )
        )
    await db.flush()

    trusted_key = _trusted_key(
        job.knowledge_base_id,
        document.id,
        version.id,
        version.sha256,
    )
    trusted_envelope = await asyncio.to_thread(
        encrypt_bytes,
        data,
        associated_data=_object_aad(version.id),
    )
    await store.put(trusted_key, trusted_envelope)
    quarantine_key = version.storage_key
    version.storage_key = trusted_key
    version.status = "review"
    version.parser_version = PARSER_VERSION
    version.language = version.language or _infer_language(tuple(segment.text for segment in parsed))
    version.failure_reason = None
    version.metadata_json = {
        **dict(version.metadata_json or {}),
        "extraction": {
            "status": "complete",
            "segment_count": len(parsed),
            "chunk_count": len(drafts),
            "parser_version": PARSER_VERSION,
            "chunker_version": CHUNKER_VERSION,
            "document_metadata": parsed_document.metadata,
            "parser_security_flags": list(parsed_document.security_flags),
        },
        "prompt_injection_scan": {
            "status": safety.status,
            "score": safety.score,
            "matches": [{"rule_id": match.rule_id, "severity": match.severity} for match in safety.matches],
        },
    }
    await _schedule_purge(
        db,
        knowledge_base_id=job.knowledge_base_id,
        document_version_id=version.id,
        storage_key=quarantine_key,
        purpose="quarantine-promoted",
    )
    await record_knowledge_audit(
        db,
        knowledge_base_id=job.knowledge_base_id,
        document_id=document.id,
        event_type="document.version.extracted",
        actor_user_id=None,
        payload={
            "document_version_id": version.id,
            "chunk_count": len(drafts),
            "safety_status": safety.status,
        },
    )


async def purge_knowledge_object(
    job: IngestionJob,
    *,
    object_store: KnowledgeObjectStoreProtocol | None = None,
) -> None:
    storage_key = str(job.payload_json.get("storage_key") or "").replace("\\", "/").lstrip("/")
    settings = get_settings()
    allowed_prefixes = {
        settings.knowledge_quarantine_prefix.strip("/"),
        settings.knowledge_object_prefix.strip("/"),
    }
    if not storage_key or not any(storage_key.startswith(f"{prefix}/") for prefix in allowed_prefixes):
        raise ValueError("Object purge key is outside Knowledge storage")
    await (object_store or default_knowledge_object_store()).delete(storage_key)


async def approve_document_version(
    db: AsyncSession,
    *,
    document_version_id: str,
    reviewer_user_id: int,
    reason: str,
    allow_safety_override: bool = False,
    allow_self_review: bool = False,
) -> KnowledgeDocumentVersion:
    statement = select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.id == document_version_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    version = (await db.execute(statement)).scalar_one_or_none()
    if version is None or version.status != "review":
        raise ValueError("Document version is not awaiting review")
    if not allow_self_review and version.uploaded_by_user_id == reviewer_user_id:
        raise ValueError("Maker-checker policy requires a different reviewer")
    safety_status = dict(version.metadata_json or {}).get("prompt_injection_scan", {}).get("status")
    if safety_status == "blocked" and not allow_safety_override:
        raise ValueError("Blocked prompt-injection findings require an explicit override")
    normalized_reason = (reason or "").strip()
    if not normalized_reason:
        raise ValueError("Review reason is required")

    version.reviewed_by_user_id = reviewer_user_id
    version.reviewed_at = datetime.datetime.utcnow()
    version.status = "published"
    version.metadata_json = {
        **dict(version.metadata_json or {}),
        "approval": {
            "reviewer_user_id": reviewer_user_id,
            "reason": normalized_reason[:2000],
            "safety_override": bool(allow_safety_override),
        },
    }
    document = await db.get(KnowledgeDocument, version.document_id)
    if document is not None and document.status == "draft":
        document.status = "active"
    from app.services.project_resource_service import sync_project_resources_for_document

    await sync_project_resources_for_document(db, document_id=version.document_id)
    await record_knowledge_audit(
        db,
        knowledge_base_id=document.knowledge_base_id if document else None,
        document_id=version.document_id,
        event_type="document.version.approved",
        actor_user_id=reviewer_user_id,
        reason=normalized_reason[:2000],
        payload={
            "document_version_id": version.id,
            "safety_override": bool(allow_safety_override),
            "status": version.status,
        },
    )
    return version


async def soft_revoke_document(
    db: AsyncSession,
    *,
    document: KnowledgeDocument,
    actor_user_id: int | None,
    reason: str,
) -> list[str]:
    """Mark a document and its non-terminal versions as revoked. Returns version ids."""

    if document.status == "deleted":
        raise ValueError("Knowledge document is already deleted")
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    already_revoked = document.status == "revoked"
    document.status = "revoked"
    document.revoked_at = document.revoked_at or now
    document.updated_at = now
    versions = (
        (
            await db.execute(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == document.id,
                    KnowledgeDocumentVersion.status.in_(
                        {
                            "uploaded",
                            "quarantined",
                            "processing",
                            "review",
                            "published",
                            "failed",
                        }
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    version_ids = [version.id for version in versions]
    for version in versions:
        version.status = "revoked"
        version.active_scope_key = None
        version.revoked_at = version.revoked_at or now
    if not already_revoked or version_ids:
        await record_knowledge_audit(
            db,
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            event_type="knowledge.document.revoked",
            actor_user_id=actor_user_id,
            reason=(reason or "")[:8000],
            payload={"version_ids": version_ids},
        )
    return version_ids
