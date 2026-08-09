"""Async video generation jobs (OpenRouter /videos)."""

import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.database import Base


class VideoGenerationJob(Base):
    """Server-owned async video generation job (never expose provider polling URLs)."""

    __tablename__ = "video_generation_jobs"
    __table_args__ = (
        Index("uq_video_job_user_idempotency", "user_id", "idempotency_key", unique=True),
        Index("ix_video_jobs_due", "status", "next_action_at"),
        Index("ix_video_jobs_lease", "status", "lease_expires_at"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    chat_session_id = Column(String(128), nullable=True, index=True)
    model_id = Column(String(512), nullable=False)
    catalog_model_id = Column(Integer, ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True)
    connection_id = Column(Integer, ForeignKey("connections.id", ondelete="SET NULL"), nullable=True, index=True)
    provider_type = Column(String(64), nullable=False, default="openrouter")
    adapter_key = Column(String(64), nullable=False, default="openrouter")
    adapter_version = Column(String(64), nullable=True)
    operation = Column(String(32), nullable=False, default="generation")  # generation | img2vid
    status = Column(String(32), nullable=False, default="queued", index=True)
    prompt = Column(Text, nullable=False, default="")
    params_json = Column(Text, nullable=True)
    provider_job_id = Column(String(255), nullable=True, index=True)
    provider_polling_url = Column(Text, nullable=True)
    budget_reservation_id = Column(String(64), nullable=True)
    idempotency_key = Column(String(160), nullable=True, index=True)
    media_asset_id = Column(Integer, ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    persist = Column(Integer, nullable=False, default=1)  # 1=true, 0=false (SQLite-friendly)
    reference_image = Column(Text, nullable=True)
    reference_storage_path = Column(Text, nullable=True)
    reference_image_mime = Column(String(128), nullable=True)
    capability_snapshot_json = Column(Text, nullable=True)
    provider_status_raw = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    next_action_at = Column(DateTime, nullable=True, index=True)
    lease_owner = Column(String(128), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    ephemeral_storage_path = Column(Text, nullable=True)
    ephemeral_expires_at = Column(DateTime, nullable=True)
    ephemeral_consumed_at = Column(DateTime, nullable=True)
    source_ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
