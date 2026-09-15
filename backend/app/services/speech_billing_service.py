"""API Logs + budget accounting for /api/speech/generate."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import CHAT_CLIENT_APP
from app.core.language_detect import detect_prompt_language
from app.models.model_catalog import AIModel
from app.services.usage_logging_service import log_usage
from app.services.usage_accounting_service import capture_usage_event


@dataclass
class SpeechBillingCapture:
    """Mutable billing state filled during speech generation."""

    model_id: str = ""
    ai_model_id: int | None = None
    connection_id: int | None = None
    provider_type: str | None = None
    characters: int | None = None
    duration_seconds: float | None = None
    upstream_request_id: str | None = None
    raw_usage: dict = field(default_factory=dict)


async def log_speech_usage(
    db: AsyncSession,
    *,
    user_id: int,
    username: str,
    capture: SpeechBillingCapture,
    prompt: str,
    response_time_ms: float,
    success: bool,
    error_message: str | None = None,
    error_code: str | None = None,
    http_status: int | None = None,
    source_ip: str | None = None,
    budget_reservation_id: str | None = None,
) -> int | None:
    """Write RequestLog row and apply budget/key usage (same path as chat completions)."""
    model_id = (capture.model_id or "").strip() or "unknown"
    characters = capture.characters if capture.characters is not None else len(prompt)

    # Re-load the catalog row in this session so settlement never touches a
    # detached/expired ORM instance from the request session.
    ai_model: AIModel | None = None
    if capture.ai_model_id is not None:
        ai_model = await db.get(AIModel, capture.ai_model_id)

    usage_event = capture_usage_event(
        capture.raw_usage or None,
        ai_model=ai_model,
        provider_type=capture.provider_type,
        service_type="speech",
        operation_name="speech:text_to_speech",
        model_id=model_id,
        attempt_index=0,
        status="succeeded" if success else "failed",
        started_at=datetime.datetime.utcnow(),
        completed_at=datetime.datetime.utcnow(),
        quantity=float(characters) if success else None,
        unit="character" if success else None,
        prompt=prompt,
        error_message=error_message,
    )
    if capture.connection_id is not None and usage_event.connection_id is None:
        usage_event.connection_id = capture.connection_id

    total_cost = float(usage_event.quote.final_cost_usd) if usage_event.quote.final_cost_usd is not None else 0.0
    client_app = f"{CHAT_CLIENT_APP} (speech:text_to_speech)"
    return await log_usage(
        db,
        user_id=user_id,
        username=username,
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
        error_code=error_code,
        http_status=http_status,
        client_app=client_app,
        budget_reservation_id=budget_reservation_id,
        usage_events=[usage_event],
        operation_type="speech",
    )
