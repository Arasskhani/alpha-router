"""AI models synced from providers — pricing is read-only from provider APIs."""

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
)
from sqlalchemy.orm import relationship

from app.database import Base


class AIModel(Base):
    """
    Catalog entry for a provider model.
    Costs are stored exactly as returned by the provider (per 1M or 1K tokens as noted).
    Alpharouter never modifies pricing — only displays and uses it for billing math.
    """

    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("connections.id", ondelete="CASCADE"), index=True)
    external_id = Column(String(512), nullable=False, index=True)  # e.g. openai/gpt-4o
    display_name = Column(String(512), nullable=True)
    provider_type = Column(String(64), nullable=False)
    is_enabled = Column(Boolean, default=True)
    # Sticky admin lock: sync / connection enable must not clear this until admin re-enables.
    admin_disabled = Column(Boolean, nullable=False, default=False)
    # public = all users; private = only assigned users/groups (empty = super admin only)
    access_type = Column(String(16), nullable=False, default="public")
    is_image_model = Column(Boolean, default=False)
    is_video_model = Column(Boolean, default=False)

    # Per 1K token USD from provider (nullable if provider does not expose)
    input_cost_per_1k = Column(Float, nullable=True)
    output_cost_per_1k = Column(Float, nullable=True)
    # Some providers return per-token; we normalize to per-1k on sync
    pricing_unit = Column(String(16), default="1k")  # 1k | 1m
    pricing_raw = Column(Text, nullable=True)  # JSON snapshot from provider

    context_length = Column(Integer, nullable=True)
    last_synced_at = Column(DateTime, default=datetime.datetime.utcnow)
    # First catalog insert in Alpha Router. Re-sync must not overwrite this.
    first_seen_at = Column(DateTime, nullable=True, index=True)

    connection = relationship("Connection")
    access_assignments = relationship(
        "ModelAccessAssignment",
        back_populates="model",
        cascade="all, delete-orphan",
    )


class ModelAccessAssignment(Base):
    """User or group grant for a private catalog model (exactly one target per row)."""

    __tablename__ = "model_access_assignments"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND group_id IS NULL) OR (user_id IS NULL AND group_id IS NOT NULL)",
            name="chk_model_access_target",
        ),
        UniqueConstraint("model_id", "user_id", name="uq_model_access_user"),
        UniqueConstraint("model_id", "group_id", name="uq_model_access_group"),
    )

    id = Column(Integer, primary_key=True)
    model_id = Column(
        Integer, ForeignKey("ai_models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    group_id = Column(
        Integer, ForeignKey("user_groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)

    model = relationship("AIModel", back_populates="access_assignments")
    user = relationship("User", foreign_keys=[user_id])
    group = relationship("UserGroup", foreign_keys=[group_id])


class ModelToolCompatibility(Base):
    """Observed compatibility of one provider model with an Alpharouter tool."""

    __tablename__ = "model_tool_compatibilities"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "external_model_id",
            "tool",
            name="uq_model_tool_compatibility_target",
        ),
        Index(
            "ix_model_tool_compatibility_due",
            "tool",
            "status",
            "next_probe_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    connection_id = Column(
        Integer,
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id = Column(
        Integer,
        ForeignKey("ai_models.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_model_id = Column(String(512), nullable=False, index=True)
    tool = Column(String(64), nullable=False, default="code_interpreter", index=True)
    status = Column(String(24), nullable=False, default="unknown", index=True)
    score = Column(Float, nullable=False, default=0.5)
    consecutive_successes = Column(Integer, nullable=False, default=0)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    total_successes = Column(Integer, nullable=False, default=0)
    total_failures = Column(Integer, nullable=False, default=0)
    reason_code = Column(String(64), nullable=True)
    reason_detail = Column(Text, nullable=True)
    manual_override = Column(String(24), nullable=True)
    probe_version = Column(String(32), nullable=False, default="v1")
    evidence_json = Column(Text, nullable=True)
    last_probe_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_failure_at = Column(DateTime, nullable=True)
    next_probe_at = Column(DateTime, nullable=True, index=True)
    quarantine_until = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    model = relationship("AIModel")
    connection = relationship("Connection")
    events = relationship(
        "ModelToolCompatibilityEvent",
        back_populates="compatibility",
        cascade="all, delete-orphan",
    )


class ModelToolCompatibilityEvent(Base):
    """Bounded audit evidence used by compatibility scoring and Admin UI."""

    __tablename__ = "model_tool_compatibility_events"
    __table_args__ = (
        Index(
            "ix_model_tool_compatibility_event_time",
            "compatibility_id",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    compatibility_id = Column(
        Integer,
        ForeignKey("model_tool_compatibilities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source = Column(String(24), nullable=False)
    success = Column(Boolean, nullable=False)
    reason_code = Column(String(64), nullable=True)
    detail = Column(Text, nullable=True)
    requested_model_id = Column(String(512), nullable=True)
    upstream_request_id = Column(String(255), nullable=True)
    evidence_json = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)

    compatibility = relationship("ModelToolCompatibility", back_populates="events")
