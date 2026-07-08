"""AI models synced from providers — pricing is read-only from provider APIs."""

import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class AIModel(Base):
    """
    Catalog entry for a provider model.
    Costs are stored exactly as returned by the provider (per 1M or 1K tokens as noted).
    NITRO never modifies pricing — only displays and uses for billing math.
    """

    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, ForeignKey("connections.id", ondelete="CASCADE"), index=True)
    external_id = Column(String(512), nullable=False, index=True)  # e.g. openai/gpt-4o
    display_name = Column(String(512), nullable=True)
    provider_type = Column(String(64), nullable=False)
    is_enabled = Column(Boolean, default=True)
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
