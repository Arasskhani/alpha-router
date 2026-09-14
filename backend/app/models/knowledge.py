"""Knowledge corpus, release, indexing, job, and governance records."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.database import Base

JsonDocument = JSON().with_variant(JSONB(), "postgresql")


def one_acl_target_constraint(name: str) -> CheckConstraint:
    return CheckConstraint(
        "("
        "(CASE WHEN user_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN department IS NOT NULL THEN 1 ELSE 0 END) + "
        "(CASE WHEN role_slug IS NOT NULL THEN 1 ELSE 0 END)"
        ") = 1",
        name=name,
    )


class KnowledgeBase(Base):
    """Stable security and ownership boundary for organization knowledge."""

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'suspended', 'archived')",
            name="chk_knowledge_bases_status",
        ),
        CheckConstraint(
            "access_type IN ('public', 'private')",
            name="chk_knowledge_bases_access_type",
        ),
        CheckConstraint(
            "sensitivity IN ('internal', 'confidential', 'hr_confidential', 'legal_privileged', 'finance_restricted')",
            name="chk_knowledge_bases_sensitivity",
        ),
        Index("ix_knowledge_bases_status_name", "status", "name"),
    )

    id = Column(String(36), primary_key=True)
    slug = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="draft", index=True)
    access_type = Column(String(16), nullable=False, default="private", index=True)
    sensitivity = Column(String(32), nullable=False, default="internal", index=True)
    acl_version = Column(Integer, nullable=False, default=1)
    owner_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_group_id = Column(
        Integer,
        ForeignKey("user_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    retention_days = Column(Integer, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    documents = relationship(
        "KnowledgeDocument",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
    )
    access_assignments = relationship(
        "KnowledgeBaseAccessAssignment",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
    )
    releases = relationship(
        "KnowledgeRelease",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
    )


class KnowledgeBaseAccessAssignment(Base):
    """Allow or deny one principal access to a Knowledge Base."""

    __tablename__ = "knowledge_base_access_assignments"
    __table_args__ = (
        one_acl_target_constraint("chk_kb_access_one_target"),
        CheckConstraint("effect IN ('allow', 'deny')", name="chk_kb_access_effect"),
        UniqueConstraint(
            "knowledge_base_id",
            "user_id",
            "effect",
            name="uq_kb_access_user_effect",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "group_id",
            "effect",
            name="uq_kb_access_group_effect",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "department",
            "effect",
            name="uq_kb_access_department_effect",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "role_slug",
            "effect",
            name="uq_kb_access_role_effect",
        ),
        Index("ix_kb_access_resource_effect", "knowledge_base_id", "effect"),
    )

    id = Column(Integer, primary_key=True)
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    group_id = Column(
        Integer,
        ForeignKey("user_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    department = Column(String(255), nullable=True, index=True)
    role_slug = Column(String(64), nullable=True, index=True)
    effect = Column(String(8), nullable=False, default="allow", index=True)
    assigned_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    knowledge_base = relationship("KnowledgeBase", back_populates="access_assignments")


class KnowledgeDocument(Base):
    """Stable document identity independent from uploaded/source revisions."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "canonical_key",
            name="uq_knowledge_document_canonical_key",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'superseded', 'revoked', 'deleted')",
            name="chk_knowledge_documents_status",
        ),
        Index("ix_knowledge_documents_kb_status", "knowledge_base_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    canonical_key = Column(String(512), nullable=False)
    title = Column(String(512), nullable=False)
    status = Column(String(24), nullable=False, default="draft", index=True)
    acl_version = Column(Integer, nullable=False, default=1)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )
    revoked_at = Column(DateTime, nullable=True, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    versions = relationship(
        "KnowledgeDocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    access_assignments = relationship(
        "KnowledgeDocumentAccessAssignment",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class KnowledgeDocumentAccessAssignment(Base):
    """Optional document-level override; deny always wins over inherited access."""

    __tablename__ = "knowledge_document_access_assignments"
    __table_args__ = (
        one_acl_target_constraint("chk_knowledge_document_access_one_target"),
        CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="chk_knowledge_document_access_effect",
        ),
        UniqueConstraint(
            "document_id",
            "user_id",
            "effect",
            name="uq_knowledge_document_access_user_effect",
        ),
        UniqueConstraint(
            "document_id",
            "group_id",
            "effect",
            name="uq_knowledge_document_access_group_effect",
        ),
        UniqueConstraint(
            "document_id",
            "department",
            "effect",
            name="uq_knowledge_document_access_department_effect",
        ),
        UniqueConstraint(
            "document_id",
            "role_slug",
            "effect",
            name="uq_knowledge_document_access_role_effect",
        ),
        Index("ix_document_access_resource_effect", "document_id", "effect"),
    )

    id = Column(Integer, primary_key=True)
    document_id = Column(
        String(36),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    group_id = Column(
        Integer,
        ForeignKey("user_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    department = Column(String(255), nullable=True, index=True)
    role_slug = Column(String(64), nullable=True, index=True)
    effect = Column(String(8), nullable=False, default="allow", index=True)
    assigned_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    document = relationship("KnowledgeDocument", back_populates="access_assignments")


class KnowledgeDocumentVersion(Base):
    """Immutable source revision with temporal and provenance metadata."""

    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_knowledge_document_versions_number",
        ),
        UniqueConstraint("sha256", "document_id", name="uq_document_version_hash"),
        CheckConstraint(
            "status IN ("
            "'uploaded', 'quarantined', 'processing', 'review', "
            "'published', 'superseded', 'revoked', 'failed'"
            ")",
            name="chk_knowledge_document_versions_status",
        ),
        Index(
            "ix_document_versions_document_status",
            "document_id",
            "status",
            "version_number",
        ),
        Index(
            "ix_document_versions_effective",
            "effective_from",
            "effective_to",
        ),
    )

    id = Column(String(36), primary_key=True)
    document_id = Column(
        String(36),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="uploaded", index=True)
    active_scope_key = Column(String(80), nullable=True, unique=True, index=True)
    storage_key = Column(String(1024), nullable=False, unique=True)
    file_name = Column(String(512), nullable=False)
    mime_type = Column(String(255), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    source_type = Column(String(32), nullable=False, default="upload", index=True)
    source_uri = Column(Text, nullable=True)
    language = Column(String(16), nullable=True, index=True)
    classification = Column(String(64), nullable=False, default="internal", index=True)
    authority = Column(String(32), nullable=False, default="reference", index=True)
    jurisdiction = Column(String(128), nullable=True, index=True)
    effective_from = Column(DateTime, nullable=True, index=True)
    effective_to = Column(DateTime, nullable=True, index=True)
    review_due_at = Column(DateTime, nullable=True, index=True)
    parser_version = Column(String(64), nullable=True)
    metadata_json = Column(JsonDocument, nullable=False, default=dict)
    uploaded_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True, index=True)
    revoked_at = Column(DateTime, nullable=True, index=True)
    failure_reason = Column(Text, nullable=True)

    document = relationship("KnowledgeDocument", back_populates="versions")
    chunks = relationship(
        "KnowledgeChunk",
        back_populates="document_version",
        cascade="all, delete-orphan",
    )


class KnowledgeRelease(Base):
    """Immutable published manifest of approved document versions for one KB."""

    __tablename__ = "knowledge_releases"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "version_number",
            name="uq_knowledge_releases_number",
        ),
        UniqueConstraint("fingerprint", name="uq_knowledge_releases_fingerprint"),
        CheckConstraint(
            "status IN ('draft', 'indexing', 'review', 'published', 'archived', 'failed')",
            name="chk_knowledge_releases_status",
        ),
        Index(
            "ix_knowledge_releases_kb_status",
            "knowledge_base_id",
            "status",
            "version_number",
        ),
    )

    id = Column(String(36), primary_key=True)
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="draft", index=True)
    fingerprint = Column(String(64), nullable=False)
    active_scope_key = Column(String(80), nullable=True, unique=True, index=True)
    manifest_json = Column(JsonDocument, nullable=False, default=dict)
    change_summary = Column(Text, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True, index=True)
    archived_at = Column(DateTime, nullable=True)

    knowledge_base = relationship("KnowledgeBase", back_populates="releases")
    document_versions = relationship(
        "KnowledgeReleaseDocument",
        back_populates="release",
        cascade="all, delete-orphan",
    )


class KnowledgeReleaseDocument(Base):
    """Ordered document-version membership in a Knowledge Release."""

    __tablename__ = "knowledge_release_documents"
    __table_args__ = (
        UniqueConstraint(
            "release_id",
            "document_version_id",
            name="uq_knowledge_release_document",
        ),
    )

    id = Column(Integer, primary_key=True)
    release_id = Column(
        String(36),
        ForeignKey("knowledge_releases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version_id = Column(
        String(36),
        ForeignKey("knowledge_document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sort_order = Column(Integer, nullable=False, default=0)

    release = relationship("KnowledgeRelease", back_populates="document_versions")
    document_version = relationship("KnowledgeDocumentVersion")


class KnowledgeChunk(Base):
    """Authoritative chunk text and citation offsets; vectors are derived in Qdrant."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_knowledge_chunks_index",
        ),
        UniqueConstraint(
            "document_version_id",
            "content_hash",
            name="uq_knowledge_chunks_hash",
        ),
        Index("ix_knowledge_chunks_document_page", "document_version_id", "page_number"),
    )

    id = Column(String(36), primary_key=True)
    document_version_id = Column(
        String(36),
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_chunk_id = Column(
        String(36),
        ForeignKey("knowledge_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    token_count = Column(Integer, nullable=False, default=0)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    page_number = Column(Integer, nullable=True)
    section = Column(String(512), nullable=True)
    language = Column(String(16), nullable=True, index=True)
    metadata_json = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    document_version = relationship("KnowledgeDocumentVersion", back_populates="chunks")


class KnowledgeIndexVersion(Base):
    """Qdrant collection/index contract for one release and embedding profile."""

    __tablename__ = "knowledge_index_versions"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "version_number",
            name="uq_knowledge_index_versions_number",
        ),
        UniqueConstraint("fingerprint", name="uq_knowledge_index_versions_fingerprint"),
        CheckConstraint(
            "status IN ('planned', 'building', 'validating', 'active', 'retired', 'failed')",
            name="chk_knowledge_index_versions_status",
        ),
        Index(
            "ix_knowledge_index_kb_status",
            "knowledge_base_id",
            "status",
            "version_number",
        ),
    )

    id = Column(String(36), primary_key=True)
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    release_id = Column(
        String(36),
        ForeignKey("knowledge_releases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="planned", index=True)
    embedding_provider = Column(String(64), nullable=False)
    embedding_model = Column(String(512), nullable=False)
    embedding_dimensions = Column(Integer, nullable=False)
    embedding_fingerprint = Column(String(128), nullable=False)
    sparse_profile = Column(JsonDocument, nullable=False, default=dict)
    chunker_version = Column(String(64), nullable=False)
    collection_name = Column(String(255), nullable=False, unique=True)
    collection_alias = Column(String(255), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False)
    active_scope_key = Column(String(80), nullable=True, unique=True, index=True)
    expected_point_count = Column(Integer, nullable=False, default=0)
    indexed_point_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    activated_at = Column(DateTime, nullable=True, index=True)
    retired_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)


class KnowledgeConnector(Base):
    """Pluggable source configuration with encrypted credentials and checkpoint state."""

    __tablename__ = "knowledge_connectors"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "name",
            name="uq_knowledge_connectors_name",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'failed', 'archived')",
            name="chk_knowledge_connectors_status",
        ),
        Index("ix_knowledge_connectors_kb_status", "knowledge_base_id", "status"),
    )

    id = Column(String(36), primary_key=True)
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_type = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(24), nullable=False, default="draft", index=True)
    config_json = Column(JsonDocument, nullable=False, default=dict)
    credentials_encrypted = Column(Text, nullable=True)
    checkpoint_json = Column(JsonDocument, nullable=False, default=dict)
    sync_interval_minutes = Column(Integer, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )
    last_synced_at = Column(DateTime, nullable=True, index=True)


class ConnectorSyncRun(Base):
    """One incremental connector discovery/fetch cycle."""

    __tablename__ = "connector_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="chk_connector_sync_runs_status",
        ),
        Index("ix_connector_sync_connector_time", "connector_id", "started_at"),
    )

    id = Column(String(36), primary_key=True)
    connector_id = Column(
        String(36),
        ForeignKey("knowledge_connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = Column(String(24), nullable=False, default="pending", index=True)
    discovered_count = Column(Integer, nullable=False, default=0)
    created_count = Column(Integer, nullable=False, default=0)
    updated_count = Column(Integer, nullable=False, default=0)
    deleted_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    checkpoint_json = Column(JsonDocument, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True, index=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class IngestionJob(Base):
    """Durable, idempotent work record; Redis only dispatches these rows."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ingestion_jobs_idempotency"),
        CheckConstraint(
            "status IN ('pending', 'leased', 'processing', 'retry', 'succeeded', 'dead', 'cancelled')",
            name="chk_ingestion_jobs_status",
        ),
        Index("ix_ingestion_jobs_due", "status", "next_attempt_at", "created_at"),
        Index("ix_ingestion_jobs_lease", "lease_until", "status"),
    )

    id = Column(String(36), primary_key=True)
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version_id = Column(
        String(36),
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    index_version_id = Column(
        String(36),
        ForeignKey("knowledge_index_versions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    job_type = Column(String(64), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    lease_owner = Column(String(128), nullable=True, index=True)
    lease_until = Column(DateTime, nullable=True, index=True)
    idempotency_key = Column(String(255), nullable=False)
    payload_json = Column(JsonDocument, nullable=False, default=dict)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )


class OutboxEvent(Base):
    """Transactional intent for Qdrant, Redis, audit, and deletion side effects."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency"),
        CheckConstraint(
            "status IN ('pending', 'leased', 'processed', 'retry', 'dead')",
            name="chk_outbox_events_status",
        ),
        Index("ix_outbox_events_due", "status", "available_at", "created_at"),
        Index("ix_outbox_events_lease", "lease_until", "status"),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
    )

    id = Column(String(36), primary_key=True)
    aggregate_type = Column(String(64), nullable=False, index=True)
    aggregate_id = Column(String(128), nullable=False, index=True)
    event_type = Column(String(128), nullable=False, index=True)
    payload_json = Column(JsonDocument, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    lease_owner = Column(String(128), nullable=True, index=True)
    lease_until = Column(DateTime, nullable=True, index=True)
    idempotency_key = Column(String(255), nullable=False)
    available_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    processed_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class DeletionTombstone(Base):
    """Cross-store deletion record retained until every copy is removed."""

    __tablename__ = "deletion_tombstones"
    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            name="uq_deletion_tombstone_resource",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="chk_deletion_tombstones_status",
        ),
        Index("ix_deletion_tombstones_due", "status", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    resource_type = Column(String(64), nullable=False, index=True)
    resource_id = Column(String(128), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    storage_key = Column(String(1024), nullable=True)
    vector_selector = Column(JsonDocument, nullable=False, default=dict)
    cache_selector = Column(JsonDocument, nullable=False, default=dict)
    requested_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class LegalHold(Base):
    """Prevents retention/deletion of a governed Agent or Knowledge resource."""

    __tablename__ = "legal_holds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'released')",
            name="chk_legal_holds_status",
        ),
        Index("ix_legal_holds_resource_status", "resource_type", "resource_id", "status"),
        Index(
            "uq_legal_holds_active_resource",
            "resource_type",
            "resource_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id = Column(String(36), primary_key=True)
    resource_type = Column(String(64), nullable=False, index=True)
    resource_id = Column(String(128), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="active", index=True)
    reason = Column(Text, nullable=False)
    placed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    released_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    placed_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    released_at = Column(DateTime, nullable=True)


class KnowledgeAuditEvent(Base):
    """Append-only administrative evidence for Knowledge lifecycle changes."""

    __tablename__ = "knowledge_audit_events"
    __table_args__ = (
        Index("ix_knowledge_audit_kb_time", "knowledge_base_id", "created_at"),
        Index("ix_knowledge_audit_actor_time", "actor_user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_id = Column(
        String(36),
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    release_id = Column(
        String(36),
        ForeignKey("knowledge_releases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = Column(String(64), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    payload_json = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
