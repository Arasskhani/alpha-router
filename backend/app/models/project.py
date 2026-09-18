"""Projects domain: shared workspaces with role-based membership, invitations,
config versions, memory, cross-project memory grants, and chat pinning."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapper
from sqlalchemy.types import JSON

from app.database import Base

JsonDocument = JSON().with_variant(JSONB(), "postgresql")

PROJECT_ROLE_PRIMARY_OWNER = "primary_owner"
PROJECT_ROLE_OWNER = "owner"
PROJECT_ROLE_CONTRIBUTOR = "contributor"
PROJECT_ROLE_VIEWER = "viewer"
PROJECT_ROLES = (
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_VIEWER,
)
PROJECT_OWNER_ROLES = (PROJECT_ROLE_PRIMARY_OWNER, PROJECT_ROLE_OWNER)

PROJECT_STATUS_ACTIVE = "active"
PROJECT_STATUS_ARCHIVED = "archived"
PROJECT_STATUS_DELETION_PENDING = "deletion_pending"

PROJECT_VISIBILITY_PRIVATE = "private"
PROJECT_VISIBILITY_PUBLIC = "public"


class Project(Base):
    """A shared workspace owned by its creator with role-based membership."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{PROJECT_STATUS_ACTIVE}', '{PROJECT_STATUS_ARCHIVED}', '{PROJECT_STATUS_DELETION_PENDING}')",
            name="chk_projects_status",
        ),
        CheckConstraint(
            f"visibility IN ('{PROJECT_VISIBILITY_PRIVATE}', '{PROJECT_VISIBILITY_PUBLIC}')",
            name="chk_projects_visibility",
        ),
        Index("ix_projects_status_updated", "status", "updated_at"),
        Index("ix_projects_visibility", "visibility"),
    )

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default=PROJECT_STATUS_ACTIVE, index=True)
    visibility = Column(
        String(16),
        nullable=False,
        default=PROJECT_VISIBILITY_PRIVATE,
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    active_config_version_id = Column(
        String(36),
        ForeignKey("project_config_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision = Column(Integer, nullable=False, default=1)
    acl_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )
    archived_at = Column(DateTime, nullable=True)


class ProjectMember(Base):
    """Explicit membership with a project role; the source of truth for access."""

    __tablename__ = "project_members"
    __table_args__ = (
        CheckConstraint(
            f"role IN ('{PROJECT_ROLE_PRIMARY_OWNER}', '{PROJECT_ROLE_OWNER}', "
            f"'{PROJECT_ROLE_CONTRIBUTOR}', '{PROJECT_ROLE_VIEWER}')",
            name="chk_project_members_role",
        ),
        Index("ix_project_members_project_role", "project_id", "role"),
        Index(
            "uq_project_members_one_primary_owner",
            "project_id",
            unique=True,
            sqlite_where=text("role = 'primary_owner'"),
            postgresql_where=text("role = 'primary_owner'"),
        ),
    )

    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role = Column(String(16), nullable=False, default=PROJECT_ROLE_VIEWER)
    invited_by_user_id = Column(
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


class ProjectChatComposerPref(Base):
    """Per-user composer state (tools, model, Agent) for one project chat."""

    __tablename__ = "project_chat_composer_prefs"
    __table_args__ = (
        Index("ix_project_chat_composer_prefs_user", "user_id"),
        Index("ix_project_chat_composer_prefs_session", "session_id"),
    )

    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tools = Column(JsonDocument, nullable=False, default=dict)
    tools_touched = Column(Boolean, nullable=False, default=False)
    model_id = Column(String(512), nullable=True)
    selected_agent_slug = Column(String(128), nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )


class ProjectUserPref(Base):
    """Per-user workspace prefs (last opened chat / recency) for a project."""

    __tablename__ = "project_user_prefs"
    __table_args__ = (Index("ix_project_user_prefs_user_opened", "user_id", "last_opened_at"),)

    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_opened_session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_opened_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        index=True,
    )


class ProjectInvitation(Base):
    """Single- or limited-use invitation link; never grants Owner or Primary Owner."""

    __tablename__ = "project_invitations"
    __table_args__ = (
        CheckConstraint(
            f"role IN ('{PROJECT_ROLE_CONTRIBUTOR}', '{PROJECT_ROLE_VIEWER}')",
            name="chk_project_invitations_role",
        ),
        Index("ix_project_invitations_project", "project_id"),
        Index("ix_project_invitations_token_hash", "token_hash", unique=True),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(16), nullable=False, default=PROJECT_ROLE_VIEWER)
    token_hash = Column(String(128), nullable=False)
    max_uses = Column(Integer, nullable=False, default=1)
    use_count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime, nullable=False)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    claimed_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    claimed_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ProjectConfigVersion(Base):
    """Immutable snapshot of project Advanced settings for reproducible AI runs."""

    __tablename__ = "project_config_versions"
    __table_args__ = (Index("ix_project_config_versions_project", "project_id"),)

    id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        # Named to match the migration: an unnamed ``use_alter`` constraint
        # cannot be emitted as DROP CONSTRAINT, which made metadata.drop_all()
        # impossible on PostgreSQL and kept the test fixtures on SQLite.
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
            use_alter=True,
            name="fk_project_config_versions_project_id",
        ),
        nullable=False,
    )
    revision = Column(Integer, nullable=False)
    custom_prompt = Column(Text, nullable=True)
    memory_enabled = Column(Boolean, nullable=False, default=True)
    memory_auto_capture = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    grounding_policy = Column(JsonDocument, nullable=False, default=dict)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ProjectMemory(Base):
    """Project-scoped memory items: owner-authored facts plus facts learned
    automatically from the project AI chat tab."""

    __tablename__ = "project_memories"
    __table_args__ = (
        UniqueConstraint("project_id", "content_hash", name="uq_project_memories_project_hash"),
        Index("ix_project_memories_project_enabled", "project_id", "enabled"),
        Index(
            "ix_project_memories_project_enabled_salience",
            "project_id",
            "enabled",
            "salience",
        ),
        Index("ix_project_memories_embedding_status", "embedding_status"),
        Index("ix_project_memories_expires_at", "expires_at"),
        Index("ix_project_memories_deleted_at", "deleted_at"),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    # "manual" for owner-authored facts, "auto_chat" for extracted facts.
    source_type = Column(String(32), nullable=False, default="manual")
    source_id = Column(String(128), nullable=True)
    authority = Column(String(32), nullable=False, default="user")
    enabled = Column(Boolean, nullable=False, default=True)
    category = Column(String(32), nullable=False, default="other", server_default="other")
    sensitivity = Column(String(16), nullable=False, default="normal", server_default="normal")
    confidence = Column(Float, nullable=False, default=0.5, server_default="0.5")
    salience = Column(Float, nullable=False, default=0.5, server_default="0.5")
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    use_count = Column(Integer, nullable=False, default=0, server_default="0")
    source_session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_message_id = Column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    supersedes_id = Column(
        String(36),
        ForeignKey("project_memories.id", ondelete="SET NULL"),
        nullable=True,
    )
    embedding_status = Column(String(16), nullable=False, default="pending", server_default="pending")
    embedding_model = Column(String(255), nullable=True)
    embedding_dims = Column(Integer, nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
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


class ProjectMemoryJob(Base):
    """Debounced per-session extraction job for automatic project memory.

    Keyed on (project_id, session_id) rather than the posting member, so
    concurrent members in one thread coalesce into a single job.
    """

    __tablename__ = "project_memory_jobs"

    id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status = Column(String(16), nullable=False, default="pending")
    watermark_sequence = Column(Integer, nullable=False, default=0)
    extracted_sequence = Column(Integer, nullable=False, default=0)
    run_after = Column(DateTime, nullable=False, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    lease_expires_at = Column(DateTime, nullable=True)
    worker_id = Column(String(64), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    __table_args__ = (
        Index("ix_project_memory_jobs_status_run", "status", "run_after"),
        Index(
            "ux_project_memory_jobs_open",
            "project_id",
            "session_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'retry')"),
            postgresql_where=text("status IN ('pending', 'retry')"),
        ),
    )


class ProjectMemoryEvent(Base):
    """Append-only audit trail for project memory mutations (no memory text)."""

    __tablename__ = "project_memory_events"

    id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    memory_id = Column(
        String(36),
        ForeignKey("project_memories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = Column(String(32), nullable=False)
    actor = Column(String(16), nullable=False, default="system")
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id = Column(String(36), nullable=True)
    detail = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    __table_args__ = (Index("ix_project_memory_events_created", "created_at"),)


class ProjectMemorySuppression(Base):
    """Blocks a deleted project fact from being re-learned from old chats."""

    __tablename__ = "project_memory_suppressions"

    id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    content_hash = Column(String(64), nullable=False, index=True)
    vector_indexed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "content_hash",
            name="ux_project_memory_suppressions_project_hash",
        ),
        Index("ix_project_memory_suppressions_expires", "expires_at"),
    )


class ProjectMemoryGrant(Base):
    """Directional, non-transitive grant letting a consumer read a source project's memory items."""

    __tablename__ = "project_memory_grants"
    __table_args__ = (
        UniqueConstraint(
            "consumer_project_id",
            "source_project_id",
            name="uq_project_memory_grants_pair",
        ),
        CheckConstraint(
            "consumer_project_id <> source_project_id",
            name="chk_project_memory_grants_no_self",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="chk_project_memory_grants_status",
        ),
        Index("ix_project_memory_grants_consumer", "consumer_project_id"),
        Index("ix_project_memory_grants_source", "source_project_id"),
    )

    id = Column(String(36), primary_key=True)
    consumer_project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String(16), nullable=False, default="active")
    revision = Column(Integer, nullable=False, default=1)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )


class ProjectChatPin(Base):
    """Shared pin state for a project chat thread, visible to all members."""

    __tablename__ = "project_chat_pins"
    __table_args__ = (UniqueConstraint("project_id", "session_id", name="uq_project_chat_pins_session"),)

    id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pinned_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    pinned_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ProjectAuditEvent(Base):
    """Append-only audit trail for project lifecycle and membership actions."""

    __tablename__ = "project_audit_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('success', 'denied', 'failed')",
            name="chk_project_audit_outcome",
        ),
        Index("ix_project_audit_project_time", "project_id", "created_at"),
        Index("ix_project_audit_actor_time", "actor_user_id", "created_at"),
        Index("ix_project_audit_event_type", "event_type"),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), nullable=True, index=True)
    event_type = Column(String(96), nullable=False)
    actor_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    outcome = Column(String(16), nullable=False, default="success")
    payload_json = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        index=True,
    )


def _reject_project_audit_mutation(
    _mapper: Mapper,
    _connection: object,
    _target: ProjectAuditEvent,
) -> None:
    raise ValueError("Project audit events are append-only")


event.listen(ProjectAuditEvent, "before_update", _reject_project_audit_mutation)
event.listen(ProjectAuditEvent, "before_delete", _reject_project_audit_mutation)


# ---------------------------------------------------------------------------
# Project resources — files uploaded by Owner/Contributor and ingested through
# the secure Knowledge pipeline.  Each resource links a project to a
# KnowledgeDocument inside an internal, project-scoped KnowledgeBase.
# ---------------------------------------------------------------------------

PROJECT_RESOURCE_STATUS_PROCESSING = "processing"
PROJECT_RESOURCE_STATUS_ACTIVE = "active"
PROJECT_RESOURCE_STATUS_REVOKED = "revoked"
PROJECT_RESOURCE_STATUS_FAILED = "failed"


class ProjectResource(Base):
    """A file attached to a project as a shared resource.

    The heavy lifting (validation, malware scan, text extraction, chunking,
    encryption-at-rest) is delegated to the existing Knowledge ingestion
    pipeline.  This table only stores the project ↔ document link and a
    denormalized status for fast listing without joining the Knowledge
    domain.
    """

    __tablename__ = "project_resources"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{PROJECT_RESOURCE_STATUS_PROCESSING}', "
            f"'{PROJECT_RESOURCE_STATUS_ACTIVE}', "
            f"'{PROJECT_RESOURCE_STATUS_REVOKED}', "
            f"'{PROJECT_RESOURCE_STATUS_FAILED}')",
            name="chk_project_resources_status",
        ),
        UniqueConstraint(
            "project_id",
            "document_id",
            name="uq_project_resources_project_document",
        ),
        # Named as revision c3d4e5f6a7b8 created it.
        Index("ix_project_resources_project", "project_id"),
        Index("ix_project_resources_project_status", "project_id", "status"),
        Index("ix_project_resources_uploaded_by", "uploaded_by_user_id"),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id = Column(
        String(36),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(512), nullable=False)
    status = Column(
        String(24),
        nullable=False,
        default=PROJECT_RESOURCE_STATUS_PROCESSING,
        index=True,
    )
    failure_reason = Column(Text, nullable=True)
    uploaded_by_user_id = Column(
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


# ---------------------------------------------------------------------------
# Project media — binary assets (images, videos, documents) owned by the
# project, not by the uploading user.  When a user is removed from a project
# or their account is deleted, the files remain (uploaded_by_user_id → NULL).
# When the project is hard-deleted, the files are cascaded and the object
# storage is cleaned up by the service layer.
# ---------------------------------------------------------------------------

PROJECT_MEDIA_KIND_IMAGE = "image"
PROJECT_MEDIA_KIND_VIDEO = "video"
PROJECT_MEDIA_KIND_DOCUMENT = "document"
PROJECT_MEDIA_KIND_OTHER = "other"
PROJECT_MEDIA_KINDS = (
    PROJECT_MEDIA_KIND_IMAGE,
    PROJECT_MEDIA_KIND_VIDEO,
    PROJECT_MEDIA_KIND_DOCUMENT,
    PROJECT_MEDIA_KIND_OTHER,
)


class ProjectMediaAsset(Base):
    """A binary file owned by a project, shared with all members.

    Mirrors ``MediaAsset`` but with project-scoped ownership: ``project_id``
    cascades on project hard-delete, while ``uploaded_by_user_id`` is set to
    NULL when the uploading user is deleted (files are preserved).
    """

    __tablename__ = "project_media_assets"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "content_hash",
            name="uq_project_media_assets_project_hash",
        ),
        Index("ix_project_media_project_kind", "project_id", "kind"),
        Index("ix_project_media_uploaded_by", "uploaded_by_user_id"),
    )

    id = Column(Integer, primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    kind = Column(String(32), nullable=False, default=PROJECT_MEDIA_KIND_IMAGE)
    mime_type = Column(String(128), nullable=False, default="application/octet-stream")
    file_name = Column(String(255), nullable=False)
    storage_path = Column(Text, nullable=False)  # object key under S3 (cdn/p/{project}/…)
    content_hash = Column(String(64), nullable=True, index=True)  # SHA-256 hex; deduped per project
    size_bytes = Column(Integer, nullable=False, default=0)
    source_model = Column(String(512), nullable=True)
    source_prompt = Column(Text, nullable=True)
    chat_session_id = Column(String(128), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class ProjectRoomHandoff(Base):
    """A brief-only handoff from a member room into a new AI project chat."""

    __tablename__ = "project_room_handoffs"
    __table_args__ = (
        Index("ix_project_room_handoffs_source", "source_session_id"),
        Index("ix_project_room_handoffs_target", "target_session_id"),
        Index("ix_project_room_handoffs_created", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    source_session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    brief = Column(Text, nullable=False)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
