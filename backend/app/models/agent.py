"""Versioned Agent definitions, access grants, bindings, and audit records."""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from app.database import Base

JsonDocument = JSON().with_variant(JSONB(), "postgresql")


class Agent(Base):
    """Stable Agent identity; runtime behavior lives in immutable versions."""

    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="chk_agents_status",
        ),
        CheckConstraint(
            "access_type IN ('public', 'private')",
            name="chk_agents_access_type",
        ),
        Index("ix_agents_status_sort", "status", "sort_order", "name"),
    )

    id = Column(String(36), primary_key=True)
    slug = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(128), nullable=True)
    category = Column(String(128), nullable=True, index=True)
    status = Column(String(24), nullable=False, default="draft", index=True)
    access_type = Column(String(16), nullable=False, default="private", index=True)
    acl_version = Column(Integer, nullable=False, default=1)
    sort_order = Column(Integer, nullable=False, default=0)
    is_system = Column(Boolean, nullable=False, default=False)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    versions = relationship(
        "AgentVersion",
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    access_assignments = relationship(
        "AgentAccessAssignment",
        back_populates="agent",
        cascade="all, delete-orphan",
    )


class AgentVersion(Base):
    """Immutable published configuration; drafts are replaced, never edited after publish."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "version_number",
            name="uq_agent_versions_number",
        ),
        UniqueConstraint("fingerprint", name="uq_agent_versions_fingerprint"),
        CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name="chk_agent_versions_status",
        ),
        Index("ix_agent_versions_agent_status", "agent_id", "status", "version_number"),
    )

    id = Column(String(36), primary_key=True)
    agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="draft", index=True)
    system_prompt = Column(Text, nullable=False, default="")
    model_policy = Column(JsonDocument, nullable=False, default=dict)
    tool_policy = Column(JsonDocument, nullable=False, default=dict)
    retrieval_policy = Column(JsonDocument, nullable=False, default=dict)
    memory_policy = Column(JsonDocument, nullable=False, default=dict)
    profile_policy = Column(JsonDocument, nullable=False, default=dict)
    routing_policy = Column(JsonDocument, nullable=False, default=dict)
    escalation_policy = Column(JsonDocument, nullable=False, default=dict)
    disclaimer_policy = Column(JsonDocument, nullable=False, default=dict)
    guardrail_policy = Column(JsonDocument, nullable=False, default=dict)
    locale_policy = Column(JsonDocument, nullable=False, default=dict)
    fingerprint = Column(String(64), nullable=False)
    # Only the active published version owns ``agent:{agent_id}``.
    active_scope_key = Column(String(80), nullable=True, unique=True, index=True)
    change_summary = Column(Text, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True, index=True)
    archived_at = Column(DateTime, nullable=True)

    agent = relationship("Agent", back_populates="versions")
    knowledge_bindings = relationship(
        "AgentKnowledgeBinding",
        back_populates="agent_version",
        cascade="all, delete-orphan",
    )


class AgentAccessAssignment(Base):
    """Allow or deny one principal access to an Agent."""

    __tablename__ = "agent_access_assignments"
    __table_args__ = (
        CheckConstraint(
            "("
            "(CASE WHEN user_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN group_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN department IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN role_slug IS NOT NULL THEN 1 ELSE 0 END)"
            ") = 1",
            name="chk_agent_access_one_target",
        ),
        CheckConstraint(
            "effect IN ('allow', 'deny')",
            name="chk_agent_access_effect",
        ),
        UniqueConstraint(
            "agent_id",
            "user_id",
            "effect",
            name="uq_agent_access_user_effect",
        ),
        UniqueConstraint(
            "agent_id",
            "group_id",
            "effect",
            name="uq_agent_access_group_effect",
        ),
        UniqueConstraint(
            "agent_id",
            "department",
            "effect",
            name="uq_agent_access_department_effect",
        ),
        UniqueConstraint(
            "agent_id",
            "role_slug",
            "effect",
            name="uq_agent_access_role_effect",
        ),
        Index("ix_agent_access_agent_effect", "agent_id", "effect"),
    )

    id = Column(Integer, primary_key=True)
    agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
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

    agent = relationship("Agent", back_populates="access_assignments")


class AgentKnowledgeBinding(Base):
    """Versioned permission for an Agent configuration to retrieve from one KB."""

    __tablename__ = "agent_knowledge_bindings"
    __table_args__ = (
        UniqueConstraint(
            "agent_version_id",
            "knowledge_base_id",
            name="uq_agent_knowledge_binding",
        ),
        CheckConstraint(
            "status IN ("
            "'draft', 'pending_kb_approval', 'pending_domain_approval', "
            "'approved', 'published', 'suspended', 'revoked'"
            ")",
            name="chk_agent_knowledge_binding_status",
        ),
        CheckConstraint(
            "release_mode IN ('latest', 'pinned')",
            name="chk_agent_knowledge_release_mode",
        ),
    )

    id = Column(String(36), primary_key=True)
    agent_version_id = Column(
        String(36),
        ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id = Column(
        String(36),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    release_mode = Column(String(16), nullable=False, default="latest")
    pinned_release_id = Column(
        String(36),
        ForeignKey("knowledge_releases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(32), nullable=False, default="draft", index=True)
    retrieval_policy = Column(JsonDocument, nullable=False, default=dict)
    requested_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    kb_approved_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    domain_approved_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    kb_approved_at = Column(DateTime, nullable=True)
    domain_approved_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)

    agent_version = relationship("AgentVersion", back_populates="knowledge_bindings")


class AgentHandoffEvent(Base):
    """Auditable transition between active specialist Agents in one chat."""

    __tablename__ = "agent_handoff_events"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "turn_id",
            "turn_ordinal",
            name="uq_agent_handoff_turn_ordinal",
        ),
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'declined', 'completed', 'failed')",
            name="chk_agent_handoff_status",
        ),
        CheckConstraint(
            "turn_ordinal BETWEEN 1 AND 4",
            name="chk_agent_handoff_turn_ordinal",
        ),
        Index("ix_agent_handoff_session_time", "session_id", "created_at"),
        Index(
            "ix_agent_handoff_session_turn",
            "session_id",
            "turn_id",
            "created_at",
        ),
    )

    id = Column(String(36), primary_key=True)
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    turn_id = Column(String(64), nullable=False, index=True)
    turn_ordinal = Column(Integer, nullable=False)
    from_agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    to_agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    from_agent_version_id = Column(
        String(36),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_agent_version_id = Column(
        String(36),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    initiated_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="proposed", index=True)
    consent_required = Column(Boolean, nullable=False, default=False)
    consented_at = Column(DateTime, nullable=True)
    failure_code = Column(String(64), nullable=True)
    context_digest = Column(String(64), nullable=True)
    context_payload = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class AgentAuditEvent(Base):
    """Append-only administrative evidence for Agent lifecycle changes."""

    __tablename__ = "agent_audit_events"
    __table_args__ = (
        Index("ix_agent_audit_agent_time", "agent_id", "created_at"),
        Index("ix_agent_audit_actor_time", "actor_user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    agent_id = Column(
        String(36),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_version_id = Column(
        String(36),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
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
    payload = Column(JsonDocument, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
