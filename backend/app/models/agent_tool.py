"""Versioned Agent tool registry and append-only governance audit."""

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


class AgentTool(Base):
    """Stable tool identity; executable contracts live in immutable versions."""

    __tablename__ = "agent_tools"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="chk_agent_tools_status",
        ),
        Index("ix_agent_tools_status_name", "status", "name"),
    )

    id = Column(String(36), primary_key=True)
    slug = Column(String(128), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(24), nullable=False, default="draft", index=True)
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
        "AgentToolVersion",
        back_populates="tool",
        cascade="all, delete-orphan",
    )


class AgentToolVersion(Base):
    """Immutable published input/output contract for one registered tool."""

    __tablename__ = "agent_tool_versions"
    __table_args__ = (
        UniqueConstraint(
            "tool_id",
            "version_number",
            name="uq_agent_tool_versions_number",
        ),
        UniqueConstraint("fingerprint", name="uq_agent_tool_versions_fingerprint"),
        CheckConstraint(
            "status IN ('draft', 'review', 'published', 'archived')",
            name="chk_agent_tool_versions_status",
        ),
        CheckConstraint(
            "effect_type IN ('read_only', 'side_effecting')",
            name="chk_agent_tool_versions_effect",
        ),
        CheckConstraint(
            "approval_mode IN ('never', 'required')",
            name="chk_agent_tool_versions_approval",
        ),
        CheckConstraint(
            "timeout_seconds BETWEEN 1 AND 120",
            name="chk_agent_tool_versions_timeout",
        ),
        CheckConstraint(
            "max_retries BETWEEN 0 AND 3",
            name="chk_agent_tool_versions_retries",
        ),
        Index(
            "ix_agent_tool_versions_tool_status",
            "tool_id",
            "status",
            "version_number",
        ),
    )

    id = Column(String(36), primary_key=True)
    tool_id = Column(
        String(36),
        ForeignKey("agent_tools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, default="draft", index=True)
    input_schema = Column(JsonDocument, nullable=False, default=dict)
    output_schema = Column(JsonDocument, nullable=False, default=dict)
    handler_key = Column(String(128), nullable=False)
    effect_type = Column(String(24), nullable=False, default="read_only", index=True)
    required_permission = Column(String(128), nullable=True)
    timeout_seconds = Column(Integer, nullable=False, default=20)
    max_retries = Column(Integer, nullable=False, default=0)
    idempotent = Column(Boolean, nullable=False, default=True)
    approval_mode = Column(String(16), nullable=False, default="never")
    secret_ref = Column(String(255), nullable=True)
    model_compatibility = Column(JsonDocument, nullable=False, default=dict)
    rate_limit_policy = Column(JsonDocument, nullable=False, default=dict)
    cost_policy = Column(JsonDocument, nullable=False, default=dict)
    fingerprint = Column(String(64), nullable=False)
    active_scope_key = Column(String(80), nullable=True, unique=True, index=True)
    change_summary = Column(Text, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_modified_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitted_by_user_id = Column(
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

    tool = relationship("AgentTool", back_populates="versions")


class AgentToolAuditEvent(Base):
    """Append-only evidence for registry lifecycle and policy changes."""

    __tablename__ = "agent_tool_audit_events"
    __table_args__ = (
        Index("ix_agent_tool_audit_tool_time", "tool_id", "created_at"),
        Index("ix_agent_tool_audit_actor_time", "actor_user_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    tool_id = Column(
        String(36),
        ForeignKey("agent_tools.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tool_version_id = Column(
        String(36),
        ForeignKey("agent_tool_versions.id", ondelete="SET NULL"),
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
    created_at = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow, index=True
    )
