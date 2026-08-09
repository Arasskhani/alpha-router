"""API Logs + budget accounting for /api/videos/generate."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import CHAT_CLIENT_APP
from app.core.language_detect import detect_prompt_language
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.proxy_service import log_usage
from app.services.usage_accounting_service import PendingUsageEvent, capture_usage_event


@dataclass
class VideoUsageSource:
    payload: dict | object | None
    model_id: str
    ai_model: AIModel | None
    provider_type: str | None
    attempt_index: int
    success: bool
    quantity: float | None
    unit: str | None
    error_message: str | None
    started_at: datetime.datetime
    completed_at: datetime.datetime


@dataclass
class VideoBillingCapture:
    """Mutable billing state filled during video generation."""

    model_id: str = ""
    ai_model: AIModel | None = None
    provider_type: str | None = None
    usage_sources: list[VideoUsageSource] = field(default_factory=list)

    def add_usage(
        self,
        payload: dict | object | None,
        *,
        started_at: datetime.datetime | None = None,
        success: bool = True,
        quantity: float | None = None,
        unit: str | None = "clip",
        error_message: str | None = None,
    ) -> None:
        self.usage_sources.append(
            VideoUsageSource(
                payload=payload,
                model_id=(self.model_id or "").strip() or "unknown",
                ai_model=self.ai_model,
                provider_type=self.provider_type,
                attempt_index=len(self.usage_sources),
                success=success,
                quantity=quantity,
                unit=unit,
                error_message=(error_message or "")[:2000] or None,
                started_at=started_at or datetime.datetime.utcnow(),
                completed_at=datetime.datetime.utcnow(),
            )
        )


async def log_video_usage(
    db: AsyncSession,
    *,
    user: User,
    capture: VideoBillingCapture,
    prompt: str,
    response_time_ms: float,
    success: bool,
    error_message: str | None = None,
    source_ip: str | None = None,
    operation: str = "generation",
    budget_reservation_id: str | None = None,
    duration_seconds: int | None = None,
    job_id: str | None = None,
) -> None:
    """Write RequestLog row and settle budget (same path as image/chat)."""
    model_id = (capture.model_id or "").strip() or "unknown"
    op = (operation or "generation").strip().lower()
    if op == "img2vid":
        op_name = "video:img2vid"
    else:
        op_name = f"video:{op}"

    captured_sources = list(capture.usage_sources)
    usage_events: list[PendingUsageEvent] = []
    for source in captured_sources:
        qty = source.quantity
        unit = source.unit
        if qty is None and success and duration_seconds:
            qty = float(duration_seconds)
            unit = "second"
        elif qty is None and success:
            qty = 1.0
            unit = "clip"
        usage_events.append(
            capture_usage_event(
                source.payload,
                ai_model=source.ai_model,
                provider_type=source.provider_type,
                service_type="video",
                operation_name=op_name,
                model_id=source.model_id,
                attempt_index=source.attempt_index,
                status="succeeded" if source.success else "failed",
                started_at=source.started_at,
                completed_at=source.completed_at,
                quantity=qty,
                unit=unit,
                prompt=prompt,
                error_message=source.error_message,
            )
        )
    if not usage_events:
        usage_events.append(
            capture_usage_event(
                None,
                ai_model=capture.ai_model,
                provider_type=capture.provider_type,
                service_type="video",
                operation_name=op_name,
                model_id=model_id,
                status="succeeded" if success else "failed",
                quantity=(float(duration_seconds) if success and duration_seconds else (1.0 if success else None)),
                unit=("second" if success and duration_seconds else ("clip" if success else None)),
                prompt=prompt,
                error_message=error_message,
            )
        )

    total_cost = sum(
        float(event.quote.final_cost_usd)
        for event in usage_events
        if event.quote.final_cost_usd is not None
    )
    client_app = f"{CHAT_CLIENT_APP} (video:{op})"
    await log_usage(
        db,
        user_id=user.id,
        username=user.username,
        model_id=model_id,
        prompt_tokens=0,
        completion_tokens=0,
        cached_tokens=0,
        total_cost_usd=total_cost,
        response_time_ms=response_time_ms,
        prompt_language=detect_prompt_language(prompt),
        source_ip=source_ip,
        source="alpha_router_chat",
        success=success,
        error_message=error_message,
        client_app=client_app,
        budget_reservation_id=budget_reservation_id,
        usage_events=usage_events,
        operation_type="video",
        operation_idempotency_key=f"video:{job_id}" if job_id else None,
    )
