"""AI models synced from providers — pricing is read-only from provider APIs."""

import datetime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
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
    Alpha Router never modifies pricing — only displays and uses it for billing math.
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

    # Per 1K token USD from provider (nullable if provider does not expose)
    input_cost_per_1k = Column(Float, nullable=True)
    output_cost_per_1k = Column(Float, nullable=True)
    # Some providers return per-token; we normalize to per-1k on sync
    pricing_unit = Column(String(16), default="1k")  # 1k | 1m
    pricing_raw = Column(Text, nullable=True)  # JSON snapshot from provider

    context_length = Column(Integer, nullable=True)
    last_synced_at = Column(DateTime, default=datetime.datetime.utcnow)

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
