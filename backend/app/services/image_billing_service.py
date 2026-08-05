"""API Logs + budget accounting for /api/images/generate."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import CHAT_CLIENT_APP
from app.core.language_detect import detect_prompt_language
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.proxy_service import (
    _compute_token_cost_usd,
    _usage_from_response,
    _usage_from_usage_obj,
    log_usage,
)


@dataclass
class ImageBillingCapture:
    """Mutable billing state filled during image generation."""

    model_id: str = ""
    ai_model: AIModel | None = None
    provider_type: str | None = None
    usage_source: dict | object | None = None


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
    source_ip: str | None = None,
    operation: str = "generation",
    budget_reservation_id: str | None = None,
) -> None:
    """Write RequestLog row and apply budget/key usage (same path as chat completions)."""
    model_id = (capture.model_id or "").strip() or "unknown"
    prompt_tokens, completion_tokens, cached_tokens = usage_from_provider_payload(capture.usage_source)
    total_cost = compute_image_cost_usd(
        capture.ai_model,
        model_id=model_id,
        provider_type=capture.provider_type,
        prompt=prompt,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    op = (operation or "generation").strip().lower()
    client_app = f"{CHAT_CLIENT_APP} (image:{op})"
    await log_usage(
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
        client_app=client_app,
        budget_reservation_id=budget_reservation_id,
    )
