"""Per-request API logs for admin and user dashboards."""

import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import relationship

from app.database import Base, MoneyUSD


class RequestLog(Base):
    __tablename__ = "request_logs"
    __table_args__ = (
        Index(
            "uq_request_logs_budget_reservation_id",
            "budget_reservation_id",
            unique=True,
        ),
        # "this user's calls, newest first" is the query API Logs runs. Two
        # single-column indexes answer it badly: one is used, the rest is
        # filtered and sorted. This is the largest and fastest-growing table in
        # the product, so that difference is the page's whole cost.
        Index("ix_request_logs_user_time", "user_id", text("request_time DESC")),
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
    total_cost_usd = Column(MoneyUSD, default=0.0)
    provider_cost_usd = Column(MoneyUSD, nullable=True)
    calculated_cost_usd = Column(MoneyUSD, nullable=True)
    cost_source = Column(String(32), nullable=True, default="unknown", index=True)
    cost_confidence = Column(String(24), nullable=True, default="unknown", index=True)
    has_unpriced_usage = Column(Boolean, nullable=True, default=False, index=True)
    usage_operation_id = Column(String(36), nullable=True, index=True)
    reconciled_at = Column(DateTime, nullable=True)
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL", name="fk_request_logs_project_id", use_alter=True),
        nullable=True,
        index=True,
    )

    request_time = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    response_time_ms = Column(Float, default=0.0)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    # Why it failed, in a form the admin UI can filter on (see failure_details).
    error_code = Column(String(64), nullable=True, index=True)
    # Upstream HTTP status when the provider answered with one.
    http_status = Column(Integer, nullable=True)
    # Ties this row to the container log lines for the same request or job.
    correlation_id = Column(String(64), nullable=True, index=True)
    # Provider-side job id for async media (video/image), so a row can be traced
    # back to the job that produced it.
    provider_job_id = Column(String(128), nullable=True, index=True)

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
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL", name="fk_image_generation_attempts_project_id", use_alter=True),
        nullable=True,
        index=True,
    )
    requested_model = Column(String(512), nullable=False)
    model_id = Column(String(512), index=True, nullable=False)
    operation = Column(String(32), nullable=False, default="generation")
    attempt_index = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, default=datetime.datetime.utcnow, index=True, nullable=False)
    response_time_ms = Column(Float, default=0.0, nullable=False)
    success = Column(Boolean, default=False, nullable=False)
    outcome = Column(String(32), nullable=False)
    error_message = Column(Text, nullable=True)
