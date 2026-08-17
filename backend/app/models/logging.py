"""Per-request API logs for admin and user dashboards."""

import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class RequestLog(Base):
    __tablename__ = "request_logs"
    __table_args__ = (
        Index(
            "uq_request_logs_budget_reservation_id",
            "budget_reservation_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)
    username = Column(String(255), index=True, nullable=True)
    model_id = Column(String(512), index=True, nullable=False)
    prompt_language = Column(String(32), nullable=True)  # e.g. fa, en
    source_ip = Column(String(64), nullable=True)
    source = Column(String(32), default="gateway")  # openwebui | alpha_router_key | user_key
    client_app = Column(String(128), nullable=True)  # Kilo Code, Open WebUI, etc.
    alpha_router_api_key_id = Column(
        Integer,
        ForeignKey("alpha_router_api_keys.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    user_api_key_id = Column(
        Integer,
        ForeignKey("user_api_keys.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    budget_reservation_id = Column(String(36), index=True, unique=True, nullable=True)

    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    provider_cost_usd = Column(Float, nullable=True)
    calculated_cost_usd = Column(Float, nullable=True)
    cost_source = Column(String(32), nullable=True, default="unknown", index=True)
    cost_confidence = Column(String(24), nullable=True, default="unknown", index=True)
    has_unpriced_usage = Column(Boolean, nullable=True, default=False, index=True)
    usage_operation_id = Column(String(36), nullable=True, index=True)
    reconciled_at = Column(DateTime, nullable=True)

    request_time = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    response_time_ms = Column(Float, default=0.0)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    user = relationship("User", back_populates="logs")


class ImageGenerationAttempt(Base):
    """Non-billing telemetry for each concrete upstream image-model attempt."""

    __tablename__ = "image_generation_attempts"
    __table_args__ = (
        Index(
            "ix_image_generation_attempts_model_time",
            "model_id",
            "started_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    request_id = Column(String(36), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    requested_model = Column(String(512), nullable=False)
    model_id = Column(String(512), index=True, nullable=False)
    operation = Column(String(32), nullable=False, default="generation")
    attempt_index = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)
    response_time_ms = Column(Float, default=0.0, nullable=False)
    success = Column(Boolean, default=False, nullable=False)
    outcome = Column(String(32), nullable=False)
    error_message = Column(Text, nullable=True)
