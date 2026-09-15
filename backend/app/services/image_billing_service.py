"""API Logs + budget accounting for /api/images/generate."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import CHAT_CLIENT_APP
from app.core.language_detect import detect_prompt_language
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.provider_utils import (
    _compute_token_cost_usd,
    _usage_from_response,
    _usage_from_usage_obj,
)
from app.services.usage_logging_service import log_usage
from app.services.usage_accounting_service import (
    PendingUsageEvent,
    capture_usage_event,
)


@dataclass
class ImageUsageSource:
    payload: dict | object | None
    model_id: str
    ai_model: AIModel | None
    provider_type: str | None
    attempt_index: int
    success: bool
    quantity: int | None
    error_message: str | None
    started_at: datetime.datetime
    completed_at: datetime.datetime


@dataclass
class ImageBillingCapture:
    """Mutable billing state filled during image generation."""

    model_id: str = ""
    ai_model: AIModel | None = None
    provider_type: str | None = None
    usage_source: dict | object | None = None
    usage_sources: list[ImageUsageSource] = field(default_factory=list)

    def add_usage(
        self,
        payload: dict | object | None,
        *,
        started_at: datetime.datetime | None = None,
        success: bool = True,
        quantity: int | None = None,
        error_message: str | None = None,
    ) -> None:
        if payload is None:
            if not success:
                self.usage_sources.append(
                    ImageUsageSource(
                        payload=None,
                        model_id=(self.model_id or "").strip() or "unknown",
                        ai_model=self.ai_model,
                        provider_type=self.provider_type,
                        attempt_index=len(self.usage_sources),
                        success=False,
                        quantity=None,
                        error_message=(error_message or "")[:2000] or None,
                        started_at=started_at or datetime.datetime.utcnow(),
                        completed_at=datetime.datetime.utcnow(),
                    )
                )
            return
        payload_id = payload.get("id") if isinstance(payload, dict) else getattr(payload, "id", None)
        for existing in self.usage_sources:
            existing_id = (
                existing.payload.get("id")
                if isinstance(existing.payload, dict)
                else getattr(existing.payload, "id", None)
            )
            if payload is existing.payload or (payload_id is not None and existing_id == payload_id):
                existing.success = existing.success or success
                if quantity is not None:
                    existing.quantity = quantity
                if error_message and not existing.error_message:
                    existing.error_message = error_message[:2000]
                return
        self.usage_source = payload
        self.usage_sources.append(
            ImageUsageSource(
                payload=payload,
                model_id=(self.model_id or "").strip() or "unknown",
                ai_model=self.ai_model,
                provider_type=self.provider_type,
                attempt_index=len(self.usage_sources),
                success=success,
                quantity=quantity,
                error_message=(error_message or "")[:2000] or None,
                started_at=started_at or datetime.datetime.utcnow(),
                completed_at=datetime.datetime.utcnow(),
            )
        )


def usage_from_provider_payload(payload: dict | object | None) -> tuple[int, int, int]:
    """Extract prompt/completion/cached token counts from provider JSON or LiteLLM objects."""
    if payload is None:
        return 0, 0, 0
    if isinstance(payload, dict):
        return _usage_from_usage_obj(payload.get("usage"))
    return _usage_from_response(payload)


def compute_image_cost_usd(
    ai_model: AIModel | None,
    *,
    model_id: str,
    provider_type: str | None,
    prompt: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    if ai_model is None:
        stub = SimpleNamespace(
            input_cost_per_1k=None,
            output_cost_per_1k=None,
            provider_type=provider_type,
        )
        return _compute_token_cost_usd(
            stub,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model_id=model_id,
            messages=[{"role": "user", "content": prompt}],
            completion_text="",
            provider_type=provider_type,
        )
    return _compute_token_cost_usd(
        ai_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model_id=model_id,
        messages=[{"role": "user", "content": prompt}],
        completion_text="",
        provider_type=provider_type or ai_model.provider_type,
    )


async def log_image_usage(
    db: AsyncSession,
    *,
    user: User,
    capture: ImageBillingCapture,
    prompt: str,
    response_time_ms: float,
    success: bool,
    error_message: str | None = None,
    error_code: str | None = None,
    http_status: int | None = None,
    source_ip: str | None = None,
    operation: str = "generation",
    budget_reservation_id: str | None = None,
    quantity: int = 1,
    project_id: str | None = None,
) -> int | None:
    """Write RequestLog row and apply budget/key usage (same path as chat completions)."""
    model_id = (capture.model_id or "").strip() or "unknown"
    op = (operation or "generation").strip().lower()
    captured_sources = list(capture.usage_sources)
    if not captured_sources and capture.usage_source is not None:
        captured_sources.append(
            ImageUsageSource(
                payload=capture.usage_source,
                model_id=model_id,
                ai_model=capture.ai_model,
                provider_type=capture.provider_type,
                attempt_index=0,
                success=success,
                quantity=max(1, int(quantity or 1)) if success else None,
                error_message=error_message,
                started_at=datetime.datetime.utcnow(),
                completed_at=datetime.datetime.utcnow(),
            )
        )

    usage_events: list[PendingUsageEvent] = []
    for source in captured_sources:
        pt, ct, cache = usage_from_provider_payload(source.payload)
        usage_events.append(
            capture_usage_event(
                source.payload,
                ai_model=source.ai_model,
                provider_type=source.provider_type,
                service_type="image",
                operation_name=f"image:{op}",
                model_id=source.model_id,
                attempt_index=source.attempt_index,
                status="succeeded" if source.success else "failed",
                started_at=source.started_at,
                completed_at=source.completed_at,
                prompt_tokens=pt,
                completion_tokens=ct,
                cached_tokens=cache,
                quantity=source.quantity,
                unit="image" if source.quantity is not None else None,
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
                service_type="image",
                operation_name=f"image:{op}",
                model_id=model_id,
                status="succeeded" if success else "failed",
                quantity=max(1, int(quantity or 1)) if success else None,
                unit="image" if success else None,
                prompt=prompt,
                error_message=error_message,
            )
        )

    prompt_tokens = sum(event.usage.prompt_tokens for event in usage_events)
    completion_tokens = sum(event.usage.completion_tokens for event in usage_events)
    cached_tokens = sum(event.usage.cached_tokens for event in usage_events)
    total_cost = sum(
        float(event.quote.final_cost_usd) for event in usage_events if event.quote.final_cost_usd is not None
    )
    client_app = f"{CHAT_CLIENT_APP} (image:{op})"
    return await log_usage(
        db,
        user_id=user.id,
        username=user.username,
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
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
        usage_events=usage_events,
        operation_type="image",
        project_id=project_id,
    )
