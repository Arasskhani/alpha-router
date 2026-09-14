"""Provider-agnostic usage capture, cost quoting, ledger, and reconciliation."""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import litellm
from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import AlphaRouterApiKey
from app.models.cost_accounting import (
    CostLineItem,
    LedgerEntry,
    PricingSnapshot,
    ReconciliationRun,
    UsageEvent,
    UsageOperation,
)
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.llm_providers import litellm_model_for_provider, resolve_litellm_provider

COST_SOURCE_PROVIDER = "provider_response"
COST_SOURCE_RECONCILED = "provider_reconciliation"
COST_SOURCE_CATALOG = "provider_catalog"
COST_SOURCE_CONFIGURED = "configured_rate"
COST_SOURCE_LITELLM = "litellm"
COST_SOURCE_LEGACY = "legacy"
COST_SOURCE_UNKNOWN = "unknown"
COST_SOURCE_UNPRICED = "unpriced"

CONFIDENCE_EXACT = "exact"
CONFIDENCE_RECONCILED = "reconciled"
CONFIDENCE_CALCULATED = "calculated"
CONFIDENCE_ESTIMATED = "estimated"
CONFIDENCE_UNKNOWN = "unknown"

ENTRY_DEBIT = "debit"
ENTRY_ADJUSTMENT = "adjustment"

STATUS_PENDING = "pending"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_PARTIAL = "partial"

SUBJECT_USER = "user"
SUBJECT_ALPHA_ROUTER_KEY = "alpha_router_key"

# These providers expose the charge in their normalized response usage. For
# other providers, LiteLLM may populate ``usage.cost`` itself; that must remain
# an estimate rather than being presented as a provider invoice amount.
_PROVIDER_REPORTED_USAGE_COST = {
    "openrouter",
    "litellm_proxy",
}


@dataclass(slots=True)
class NormalizedUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    web_search_requests: int = 0
    metered_quantity: float | None = None
    metered_unit: str | None = None
    provider_cost_usd: float | None = None
    litellm_cost_usd: float | None = None
    upstream_request_id: str | None = None
    raw_usage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LineItemQuote:
    category: str
    quantity: float
    unit: str
    unit_price_usd: float | None
    cost_usd: float | None
    pricing_source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CostQuote:
    provider_cost_usd: float | None
    calculated_cost_usd: float | None
    final_cost_usd: float | None
    cost_source: str
    cost_confidence: str
    line_items: list[LineItemQuote] = field(default_factory=list)
    pricing_payload: dict[str, Any] | None = None
    pricing_source: str | None = None


@dataclass(slots=True)
class PendingUsageEvent:
    provider_type: str
    service_type: str
    operation_name: str
    model_id: str | None
    connection_id: int | None
    attempt_index: int
    status: str
    usage: NormalizedUsage
    quote: CostQuote
    started_at: datetime.datetime
    completed_at: datetime.datetime
    idempotency_key: str
    quantity: float | None = None
    unit: str | None = None
    error_message: str | None = None
    pricing_snapshot_id: int | None = None


@dataclass(slots=True)
class HoldQuote:
    """Pre-flight reservation amount derived from the same quote path as settlement."""

    hold_usd: float
    quoted_usd: float | None
    cost_source: str
    priced: bool


@dataclass(slots=True)
class AccountingSummary:
    operation_id: str
    total_cost_usd: float
    provider_cost_usd: float | None
    calculated_cost_usd: float | None
    cost_source: str
    cost_confidence: str
    unpriced_event_count: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    created: bool = True


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _signed_float(value: Any) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _dictish(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                dumped = method()
            except Exception:
                continue
            if isinstance(dumped, dict):
                return dumped
    return {}


def _value(container: Any, key: str, default: Any = None) -> Any:
    if isinstance(container, dict):
        return container.get(key, default)
    return getattr(container, key, default)


def _first_present(container: Any, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if isinstance(container, dict):
            if key in container and container[key] is not None:
                return container[key]
        else:
            value = getattr(container, key, None)
            if value is not None:
                return value
    return None


def _hidden_params(response: Any) -> dict[str, Any]:
    for attr in (
        "_last_returned_hidden_params",
        "_hidden_params",
        "hidden_params",
    ):
        params = _value(response, attr)
        if isinstance(params, dict):
            return params
    return {}


def _usage_object(response: Any) -> Any:
    direct = _value(response, "usage")
    if direct is not None:
        return direct
    hidden = _hidden_params(response)
    if hidden.get("usage") is not None:
        return hidden["usage"]
    if isinstance(response, dict):
        result = response.get("result")
        if isinstance(result, dict):
            if result.get("usage") is not None:
                return result["usage"]
            result_meta = result.get("_meta")
            if isinstance(result_meta, dict) and result_meta.get("usage") is not None:
                return result_meta["usage"]
        # Some adapters pass the usage object itself rather than a full response.
        usage_keys = {
            "prompt_tokens",
            "completion_tokens",
            "input_tokens",
            "output_tokens",
            "cost",
        }
        if usage_keys.intersection(response):
            return response
    return None


def _details(usage: Any, *names: str) -> Any:
    for name in names:
        value = _value(usage, name)
        if value is not None:
            return value
    return {}


def extract_normalized_usage(
    response: Any,
    *,
    provider_type: str | None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cached_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    reasoning_tokens: int | None = None,
) -> NormalizedUsage:
    """Normalize usage/cost metadata without retaining prompts or completions."""

    provider = (provider_type or "unknown").strip().lower() or "unknown"
    usage = _usage_object(response)
    usage_dict = _dictish(usage)
    prompt_details = _details(usage, "prompt_tokens_details", "input_tokens_details")
    completion_details = _details(
        usage,
        "completion_tokens_details",
        "output_tokens_details",
    )
    prompt_details_dict = _dictish(prompt_details)
    completion_details_dict = _dictish(completion_details)

    extracted_prompt = _nonnegative_int(
        _first_present(usage, ("prompt_tokens", "input_tokens"))
    )
    extracted_completion = _nonnegative_int(
        _first_present(usage, ("completion_tokens", "output_tokens"))
    )
    extracted_cached = _nonnegative_int(
        _first_present(
            prompt_details,
            (
                "cached_tokens",
                "cache_read_input_tokens",
                "prompt_cache_hit_tokens",
            ),
        )
        or _first_present(
            usage,
            (
                "cached_tokens",
                "cache_read_input_tokens",
                "prompt_cache_hit_tokens",
            ),
        )
    )
    extracted_cache_write = _nonnegative_int(
        _first_present(
            prompt_details,
            (
                "cache_creation_tokens",
                "cache_creation_input_tokens",
                "cache_write_input_tokens",
            ),
        )
        or _first_present(
            usage,
            (
                "cache_creation_tokens",
                "cache_creation_input_tokens",
                "cache_write_input_tokens",
            ),
        )
    )
    extracted_reasoning = _nonnegative_int(
        _first_present(
            completion_details,
            ("reasoning_tokens",),
        )
        or _first_present(usage, ("reasoning_tokens",))
    )

    server_tool_use = _dictish(_value(usage, "server_tool_use"))
    extracted_searches = _nonnegative_int(
        _first_present(
            usage,
            ("web_search_requests", "search_requests"),
        )
        or prompt_details_dict.get("web_search_requests")
        or server_tool_use.get("web_search_requests")
    )
    metered_quantity = None
    metered_unit = None
    for keys, candidate_unit in (
        (("credits_used", "credits"), "credit"),
        (("duration_seconds", "audio_seconds"), "second"),
        (("characters", "character_count"), "character"),
        (("images", "image_count"), "image"),
        (("requests", "request_count"), "request"),
    ):
        raw_quantity = _first_present(usage, keys)
        parsed_quantity = _finite_float(raw_quantity)
        if parsed_quantity is not None:
            metered_quantity = parsed_quantity
            metered_unit = candidate_unit
            break

    provider_cost = None
    explicit_provider_cost = _first_present(
        usage,
        (
            "provider_cost",
            "billed_cost",
            "total_cost_usd",
        ),
    )
    if explicit_provider_cost is not None:
        provider_cost = _finite_float(explicit_provider_cost)
    elif provider in _PROVIDER_REPORTED_USAGE_COST:
        provider_cost = _finite_float(_value(usage, "cost"))

    hidden = _hidden_params(response)
    litellm_cost = _finite_float(hidden.get("response_cost"))
    if litellm_cost is None and provider not in _PROVIDER_REPORTED_USAGE_COST:
        litellm_cost = _finite_float(_value(usage, "cost"))

    upstream_id = _first_present(
        response,
        ("id", "request_id", "response_id"),
    )
    if not upstream_id:
        upstream_id = _first_present(
            hidden,
            (
                "provider_request_id",
                "response_id",
                "litellm_call_id",
            ),
        )

    raw_usage: dict[str, Any] = {
        "usage": usage_dict,
        "prompt_tokens_details": prompt_details_dict,
        "completion_tokens_details": completion_details_dict,
    }
    response_model = _first_present(response, ("model",))
    if response_model:
        raw_usage["model"] = str(response_model)
    if upstream_id:
        raw_usage["upstream_request_id"] = str(upstream_id)
    if litellm_cost is not None:
        raw_usage["litellm_response_cost"] = litellm_cost

    return NormalizedUsage(
        prompt_tokens=(
            _nonnegative_int(prompt_tokens)
            if prompt_tokens is not None
            else extracted_prompt
        ),
        completion_tokens=(
            _nonnegative_int(completion_tokens)
            if completion_tokens is not None
            else extracted_completion
        ),
        cached_tokens=(
            _nonnegative_int(cached_tokens)
            if cached_tokens is not None
            else extracted_cached
        ),
        cache_write_tokens=(
            _nonnegative_int(cache_write_tokens)
            if cache_write_tokens is not None
            else extracted_cache_write
        ),
        reasoning_tokens=(
            _nonnegative_int(reasoning_tokens)
            if reasoning_tokens is not None
            else extracted_reasoning
        ),
        web_search_requests=extracted_searches,
        metered_quantity=metered_quantity,
        metered_unit=metered_unit,
        provider_cost_usd=provider_cost,
        litellm_cost_usd=litellm_cost,
        upstream_request_id=str(upstream_id)[:255] if upstream_id else None,
        raw_usage=raw_usage,
    )


def _parse_pricing_raw(ai_model: AIModel | None) -> dict[str, Any]:
    pricing_raw = getattr(ai_model, "pricing_raw", None) if ai_model is not None else None
    if not pricing_raw:
        return {}
    try:
        payload = json.loads(pricing_raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _pricing_map(ai_model: AIModel | None) -> dict[str, Any]:
    raw = _parse_pricing_raw(ai_model)
    pricing = raw.get("pricing")
    if isinstance(pricing, list):
        pricing = pricing[0] if pricing else {}
    return pricing if isinstance(pricing, dict) else {}


def _rate(pricing: dict[str, Any], *keys: str) -> tuple[bool, float | None]:
    for key in keys:
        if key not in pricing:
            continue
        value = _finite_float(pricing.get(key))
        if value is not None:
            return True, value
    return False, None


def _speech_character_rate_usd(pricing: dict[str, Any]) -> tuple[bool, float | None]:
    """Resolve USD/character for TTS catalog rows.

    Dedicated keys (``speech``/``audio``/``tts``/``character``) win when present.
    OpenRouter's live TTS catalog stores the per-character rate in
    ``pricing.prompt`` instead — that fallback is only for speech quoting and
    must never be used as a token rate for chat/image.
    """
    present, rate = _rate(pricing, "speech", "audio", "tts", "character")
    if present:
        return present, rate
    return _rate(pricing, "prompt")


def _audio_second_rate_usd(pricing: dict[str, Any]) -> tuple[bool, float | None]:
    """Resolve USD/second for speech-to-text (transcription) catalog rows.

    Transcription is billed per second of audio, not per request. A catalog that
    publishes a per-minute figure is converted here so the line item is always
    per second, matching the unit the caller reports.

    Nothing is guessed: when none of these keys exist the quote falls through to
    the admin rate table, exactly as before.
    """
    present, rate = _rate(pricing, "transcription", "audio_second", "second")
    if present:
        return present, rate
    present, rate = _rate(pricing, "audio_minute", "minute")
    if present and rate is not None:
        return True, rate / 60.0
    return False, None


def _video_second_rate_usd(pricing: dict[str, Any]) -> tuple[bool, float | None]:
    """Resolve USD/second (or per-clip) for video catalog rows.

    OpenRouter video models expose ``pricing_skus.cents_per_second_output``
    (cents, not dollars). Convert to USD/second after dedicated USD keys.
    """
    present, rate = _rate(
        pricing,
        "video",
        "output_video",
        "generate",
        "clip",
        "second",
        "usd_per_second",
        "usd_per_second_output",
    )
    if present:
        return present, rate
    cents_present, cents_rate = _rate(
        pricing,
        "cents_per_second_output",
        "cents_per_second",
        "cents_per_second_video",
    )
    if cents_present and cents_rate is not None:
        return True, float(cents_rate) / 100.0
    return False, None


def _line_item(
    *,
    category: str,
    quantity: float,
    unit: str,
    unit_price_usd: float,
    pricing_source: str,
    metadata: dict[str, Any] | None = None,
) -> LineItemQuote:
    return LineItemQuote(
        category=category,
        quantity=float(quantity),
        unit=unit,
        unit_price_usd=float(unit_price_usd),
        cost_usd=max(0.0, float(quantity) * float(unit_price_usd)),
        pricing_source=pricing_source,
        metadata=metadata or {},
    )


def _catalog_quote(
    ai_model: AIModel | None,
    usage: NormalizedUsage,
    *,
    provider_type: str,
    service_type: str,
    quantity: float | None,
    unit: str | None,
) -> tuple[float | None, list[LineItemQuote], dict[str, Any] | None]:
    """Calculate from a provider catalog snapshot, preserving every component."""

    provider = (provider_type or "unknown").lower()
    pricing = _pricing_map(ai_model)
    raw_pricing = _parse_pricing_raw(ai_model)
    if service_type == "video":
        video_meta = raw_pricing.get("video_capabilities") or raw_pricing.get("video_generation")
        if isinstance(video_meta, dict):
            video_pricing = video_meta.get("pricing") or video_meta.get("pricing_skus")
            if isinstance(video_pricing, dict):
                pricing = {**pricing, **video_pricing}
    items: list[LineItemQuote] = []
    source = COST_SOURCE_CATALOG
    pricing_complete = True

    if pricing:
        prompt_present, prompt_rate = _rate(pricing, "prompt", "input")
        completion_present, completion_rate = _rate(pricing, "completion", "output")
        cache_read_present, cache_read_rate = _rate(
            pricing,
            "input_cache_read",
            "cache_read",
        )
        cache_write_present, cache_write_rate = _rate(
            pricing,
            "input_cache_write",
            "cache_write",
        )
        reasoning_present, reasoning_rate = _rate(
            pricing,
            "internal_reasoning",
            "reasoning",
        )
        request_present, request_rate = _rate(pricing, "request")
        image_present, image_rate = _rate(pricing, "image", "output_image")
        # Video/speech rate resolution is service-scoped so OpenRouter's
        # TTS ``prompt`` (USD/char) and video ``cents_per_second_*`` SKUs never
        # leak into chat/image catalog math.
        if service_type == "video":
            video_present, video_rate = _video_second_rate_usd(pricing)
        else:
            video_present, video_rate = _rate(
                pricing,
                "video",
                "output_video",
                "generate",
                "clip",
                "second",
            )
        search_present, search_rate = _rate(
            pricing,
            "web_search",
            "search",
        )
        audio_present, audio_rate = (
            _audio_second_rate_usd(pricing) if service_type == "audio" else (False, None)
        )
        if service_type == "speech":
            speech_present, speech_rate = _speech_character_rate_usd(pricing)
        else:
            speech_present, speech_rate = _rate(
                pricing,
                "speech",
                "audio",
                "tts",
                "character",
            )
        if usage.prompt_tokens and not prompt_present:
            pricing_complete = False
        if usage.completion_tokens and not completion_present:
            pricing_complete = False
        if usage.web_search_requests and not search_present:
            pricing_complete = False
        if (
            service_type == "image"
            and quantity
            and not (usage.prompt_tokens or usage.completion_tokens)
            and not image_present
            and not request_present
        ):
            pricing_complete = False
        if (
            service_type == "speech"
            and quantity
            and not speech_present
        ):
            pricing_complete = False
        if (
            service_type == "video"
            and quantity
            and not video_present
        ):
            pricing_complete = False
        if (
            service_type == "audio"
            and quantity
            and not audio_present
        ):
            pricing_complete = False

        if (
            service_type == "video"
            and video_present
            and video_rate is not None
            and quantity is not None
            and float(quantity) > 0
        ):
            items.append(
                _line_item(
                    category="video",
                    quantity=float(quantity),
                    unit=unit or "clip",
                    unit_price_usd=video_rate,
                    pricing_source=source,
                )
            )

        # Token line items apply to chat/llm (and residual token usage on some
        # media calls). Keep them outside the video-only block so catalog
        # quoting remains complete when provider cost is absent.
        #
        # For speech, OpenRouter's pricing.prompt is USD/character (consumed by
        # the speech line item above) — never reinterpret it as a token rate.
        if service_type != "speech" and prompt_present and prompt_rate is not None:
            separately_priced_cache = (
                (cache_read_present and cache_read_rate is not None)
                or (cache_write_present and cache_write_rate is not None)
            )
            standard_prompt_tokens = usage.prompt_tokens
            if separately_priced_cache:
                standard_prompt_tokens = max(
                    0,
                    standard_prompt_tokens
                    - usage.cached_tokens
                    - usage.cache_write_tokens,
                )
            if standard_prompt_tokens:
                items.append(
                    _line_item(
                        category="input_tokens",
                        quantity=standard_prompt_tokens,
                        unit="token",
                        unit_price_usd=prompt_rate,
                        pricing_source=source,
                    )
                )
            if separately_priced_cache and usage.cached_tokens:
                items.append(
                    _line_item(
                        category="cache_read_tokens",
                        quantity=usage.cached_tokens,
                        unit="token",
                        unit_price_usd=(
                            cache_read_rate
                            if cache_read_present and cache_read_rate is not None
                            else prompt_rate
                        ),
                        pricing_source=source,
                        metadata={"fallback_to_prompt_rate": not cache_read_present},
                    )
                )
            if separately_priced_cache and usage.cache_write_tokens:
                items.append(
                    _line_item(
                        category="cache_write_tokens",
                        quantity=usage.cache_write_tokens,
                        unit="token",
                        unit_price_usd=(
                            cache_write_rate
                            if cache_write_present and cache_write_rate is not None
                            else prompt_rate
                        ),
                        pricing_source=source,
                        metadata={"fallback_to_prompt_rate": not cache_write_present},
                    )
                )

        if service_type != "speech" and completion_present and completion_rate is not None:
            standard_completion_tokens = usage.completion_tokens
            if reasoning_present and reasoning_rate is not None:
                standard_completion_tokens = max(
                    0,
                    standard_completion_tokens - usage.reasoning_tokens,
                )
            if standard_completion_tokens:
                items.append(
                    _line_item(
                        category="output_tokens",
                        quantity=standard_completion_tokens,
                        unit="token",
                        unit_price_usd=completion_rate,
                        pricing_source=source,
                    )
                )
            if (
                reasoning_present
                and reasoning_rate is not None
                and usage.reasoning_tokens
            ):
                items.append(
                    _line_item(
                        category="reasoning_tokens",
                        quantity=usage.reasoning_tokens,
                        unit="token",
                        unit_price_usd=reasoning_rate,
                        pricing_source=source,
                    )
                )

        if request_present and request_rate is not None:
            items.append(
                _line_item(
                    category="request",
                    quantity=1,
                    unit="request",
                    unit_price_usd=request_rate,
                    pricing_source=source,
                )
            )
        if (
            service_type == "image"
            and image_present
            and image_rate is not None
            and quantity is not None
            and float(quantity) > 0
        ):
            items.append(
                _line_item(
                    category="image",
                    quantity=float(quantity),
                    unit=unit or "image",
                    unit_price_usd=image_rate,
                    pricing_source=source,
                )
            )
        if (
            service_type == "speech"
            and speech_present
            and speech_rate is not None
            and quantity is not None
            and float(quantity) > 0
        ):
            items.append(
                _line_item(
                    category="speech",
                    quantity=float(quantity),
                    unit=unit or "character",
                    unit_price_usd=speech_rate,
                    pricing_source=source,
                )
            )
        if (
            service_type == "audio"
            and audio_present
            and audio_rate is not None
            and quantity is not None
            and float(quantity) > 0
        ):
            items.append(
                _line_item(
                    category="audio",
                    quantity=float(quantity),
                    unit=unit or "second",
                    unit_price_usd=audio_rate,
                    pricing_source=source,
                )
            )
        if usage.web_search_requests and search_present and search_rate is not None:
            items.append(
                _line_item(
                    category="web_search",
                    quantity=usage.web_search_requests,
                    unit="request",
                    unit_price_usd=search_rate,
                    pricing_source=source,
                )
            )

    # Generic OpenAI-compatible catalogs often expose only the normalized
    # per-1K columns. They remain a provider-catalog calculation, not an exact
    # provider response charge.
    if not items and ai_model is not None:
        input_rate = _finite_float(getattr(ai_model, "input_cost_per_1k", None))
        output_rate = _finite_float(getattr(ai_model, "output_cost_per_1k", None))
        if usage.prompt_tokens and input_rate is None:
            pricing_complete = False
        if usage.completion_tokens and output_rate is None:
            pricing_complete = False
        if input_rate is not None and usage.prompt_tokens:
            items.append(
                _line_item(
                    category="input_tokens",
                    quantity=usage.prompt_tokens,
                    unit="token",
                    unit_price_usd=input_rate / 1000,
                    pricing_source=source,
                )
            )
        if output_rate is not None and usage.completion_tokens:
            items.append(
                _line_item(
                    category="output_tokens",
                    quantity=usage.completion_tokens,
                    unit="token",
                    unit_price_usd=output_rate / 1000,
                    pricing_source=source,
                )
            )
        # Zero-priced models still need an explicit calculated zero.
        if (
            not items
            and input_rate == 0
            and output_rate == 0
            and (usage.prompt_tokens or usage.completion_tokens)
        ):
            items.extend(
                [
                    _line_item(
                        category="input_tokens",
                        quantity=usage.prompt_tokens,
                        unit="token",
                        unit_price_usd=0,
                        pricing_source=source,
                    ),
                    _line_item(
                        category="output_tokens",
                        quantity=usage.completion_tokens,
                        unit="token",
                        unit_price_usd=0,
                        pricing_source=source,
                    ),
                ]
            )

    if not items:
        return None, [], None

    calculated = sum(float(item.cost_usd or 0) for item in items)
    pricing_payload = {
        "provider_type": provider,
        "model_id": getattr(ai_model, "external_id", None),
        "service_type": service_type,
        "normalized_input_cost_per_1k": getattr(
            ai_model,
            "input_cost_per_1k",
            None,
        ),
        "normalized_output_cost_per_1k": getattr(
            ai_model,
            "output_cost_per_1k",
            None,
        ),
        "provider_pricing": pricing,
        "provider_catalog": raw_pricing,
    }
    return (
        max(0.0, calculated) if pricing_complete else None,
        items,
        pricing_payload,
    )


def _litellm_estimate(
    *,
    provider_type: str,
    model_id: str | None,
    prompt: Any,
    completion: str,
) -> float | None:
    if not model_id:
        return None
    try:
        model = litellm_model_for_provider(model_id, provider_type)
        kwargs: dict[str, Any] = {
            "model": model,
            "prompt": str(prompt or ""),
            "completion": completion or "",
        }
        custom_provider = resolve_litellm_provider(provider_type)
        if custom_provider:
            kwargs["custom_llm_provider"] = custom_provider
        return _finite_float(litellm.completion_cost(**kwargs))
    except Exception:
        return None


def quote_usage(
    usage: NormalizedUsage,
    *,
    ai_model: AIModel | None,
    provider_type: str | None,
    service_type: str,
    model_id: str | None,
    quantity: float | None = None,
    unit: str | None = None,
    prompt: Any = None,
    completion: str = "",
) -> CostQuote:
    """Choose cost using provider → adapter catalog → LiteLLM → unknown."""

    provider = (provider_type or "unknown").strip().lower() or "unknown"
    calculated, items, pricing_payload = _catalog_quote(
        ai_model,
        usage,
        provider_type=provider,
        service_type=service_type,
        quantity=quantity,
        unit=unit,
    )
    if usage.provider_cost_usd is not None:
        return CostQuote(
            provider_cost_usd=usage.provider_cost_usd,
            calculated_cost_usd=calculated,
            final_cost_usd=usage.provider_cost_usd,
            cost_source=COST_SOURCE_PROVIDER,
            cost_confidence=CONFIDENCE_EXACT,
            line_items=items,
            pricing_payload=pricing_payload,
            pricing_source=COST_SOURCE_CATALOG if pricing_payload else None,
        )
    if calculated is not None:
        return CostQuote(
            provider_cost_usd=None,
            calculated_cost_usd=calculated,
            final_cost_usd=calculated,
            cost_source=COST_SOURCE_CATALOG,
            cost_confidence=CONFIDENCE_CALCULATED,
            line_items=items,
            pricing_payload=pricing_payload,
            pricing_source=COST_SOURCE_CATALOG,
        )

    litellm_cost = usage.litellm_cost_usd
    if litellm_cost is None:
        litellm_cost = _litellm_estimate(
            provider_type=provider,
            model_id=model_id,
            prompt=prompt,
            completion=completion,
        )
    if litellm_cost is not None:
        return CostQuote(
            provider_cost_usd=None,
            calculated_cost_usd=litellm_cost,
            final_cost_usd=litellm_cost,
            cost_source=COST_SOURCE_LITELLM,
            cost_confidence=CONFIDENCE_ESTIMATED,
            line_items=[
                LineItemQuote(
                    category=service_type,
                    quantity=float(quantity or 1),
                    unit=unit or "request",
                    unit_price_usd=litellm_cost / max(1.0, float(quantity or 1)),
                    cost_usd=litellm_cost,
                    pricing_source=COST_SOURCE_LITELLM,
                )
            ],
        )

    return CostQuote(
        provider_cost_usd=None,
        calculated_cost_usd=None,
        final_cost_usd=None,
        cost_source=COST_SOURCE_UNKNOWN,
        cost_confidence=CONFIDENCE_UNKNOWN,
    )


def capture_usage_event(
    response: Any,
    *,
    fallback_response: Any = None,
    ai_model: AIModel | None,
    provider_type: str | None,
    service_type: str,
    operation_name: str,
    model_id: str | None,
    attempt_index: int = 0,
    status: str = STATUS_SUCCEEDED,
    started_at: datetime.datetime | None = None,
    completed_at: datetime.datetime | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cached_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    reasoning_tokens: int | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    prompt: Any = None,
    completion: str = "",
    error_message: str | None = None,
    idempotency_key: str | None = None,
) -> PendingUsageEvent:
    usage = extract_normalized_usage(
        response,
        provider_type=provider_type,
    )
    if fallback_response is not None:
        fallback_usage = extract_normalized_usage(
            fallback_response,
            provider_type=provider_type,
        )
        usage = NormalizedUsage(
            prompt_tokens=usage.prompt_tokens or fallback_usage.prompt_tokens,
            completion_tokens=(
                usage.completion_tokens or fallback_usage.completion_tokens
            ),
            cached_tokens=usage.cached_tokens or fallback_usage.cached_tokens,
            cache_write_tokens=(
                usage.cache_write_tokens or fallback_usage.cache_write_tokens
            ),
            reasoning_tokens=(
                usage.reasoning_tokens or fallback_usage.reasoning_tokens
            ),
            web_search_requests=(
                usage.web_search_requests or fallback_usage.web_search_requests
            ),
            metered_quantity=(
                usage.metered_quantity
                if usage.metered_quantity is not None
                else fallback_usage.metered_quantity
            ),
            metered_unit=usage.metered_unit or fallback_usage.metered_unit,
            provider_cost_usd=(
                usage.provider_cost_usd
                if usage.provider_cost_usd is not None
                else fallback_usage.provider_cost_usd
            ),
            litellm_cost_usd=(
                usage.litellm_cost_usd
                if usage.litellm_cost_usd is not None
                else fallback_usage.litellm_cost_usd
            ),
            upstream_request_id=(
                usage.upstream_request_id
                or fallback_usage.upstream_request_id
            ),
            raw_usage={
                "primary": usage.raw_usage,
                "fallback": fallback_usage.raw_usage,
            },
        )
    if prompt_tokens is not None:
        usage.prompt_tokens = _nonnegative_int(prompt_tokens)
    if completion_tokens is not None:
        usage.completion_tokens = _nonnegative_int(completion_tokens)
    if cached_tokens is not None:
        usage.cached_tokens = _nonnegative_int(cached_tokens)
    if cache_write_tokens is not None:
        usage.cache_write_tokens = _nonnegative_int(cache_write_tokens)
    if reasoning_tokens is not None:
        usage.reasoning_tokens = _nonnegative_int(reasoning_tokens)
    effective_quantity = (
        usage.metered_quantity
        if usage.metered_quantity is not None
        else quantity
    )
    effective_unit = usage.metered_unit or unit
    observed_billing = bool(
        usage.prompt_tokens
        or usage.completion_tokens
        or usage.cached_tokens
        or usage.cache_write_tokens
        or usage.reasoning_tokens
        or usage.web_search_requests
        or usage.metered_quantity is not None
        or usage.provider_cost_usd is not None
        or usage.litellm_cost_usd is not None
    )
    if status.lower() in {"failed", "cancelled", "timeout"} and not observed_billing:
        quote = CostQuote(
            provider_cost_usd=None,
            calculated_cost_usd=None,
            final_cost_usd=None,
            cost_source=COST_SOURCE_UNKNOWN,
            cost_confidence=CONFIDENCE_UNKNOWN,
        )
    else:
        quote = quote_usage(
            usage,
            ai_model=ai_model,
            provider_type=provider_type,
            service_type=service_type,
            model_id=model_id,
            quantity=effective_quantity,
            unit=effective_unit,
            prompt=prompt,
            completion=completion,
        )
    return PendingUsageEvent(
        provider_type=(provider_type or "unknown").strip().lower() or "unknown",
        service_type=service_type,
        operation_name=operation_name,
        model_id=model_id,
        connection_id=getattr(ai_model, "connection_id", None),
        attempt_index=max(0, int(attempt_index)),
        status=status,
        usage=usage,
        quote=quote,
        started_at=started_at or _now(),
        completed_at=completed_at or _now(),
        idempotency_key=(
            str(idempotency_key)[:220]
            if idempotency_key
            else f"usage-event:{uuid.uuid4()}"
        ),
        quantity=effective_quantity,
        unit=effective_unit,
        error_message=(error_message or "")[:2000] or None,
    )


def legacy_usage_event(
    *,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    total_cost_usd: float,
    operation_name: str,
) -> PendingUsageEvent:
    usage = NormalizedUsage(
        prompt_tokens=_nonnegative_int(prompt_tokens),
        completion_tokens=_nonnegative_int(completion_tokens),
        cached_tokens=_nonnegative_int(cached_tokens),
    )
    cost = max(0.0, _signed_float(total_cost_usd))
    quote = CostQuote(
        provider_cost_usd=None,
        calculated_cost_usd=cost,
        final_cost_usd=cost,
        cost_source=COST_SOURCE_LEGACY,
        cost_confidence=CONFIDENCE_ESTIMATED,
        line_items=[
            LineItemQuote(
                category="legacy_request",
                quantity=1,
                unit="request",
                unit_price_usd=cost,
                cost_usd=cost,
                pricing_source=COST_SOURCE_LEGACY,
            )
        ],
    )
    now = _now()
    return PendingUsageEvent(
        provider_type="unknown",
        service_type="llm",
        operation_name=operation_name,
        model_id=model_id,
        connection_id=None,
        attempt_index=0,
        status=STATUS_SUCCEEDED,
        usage=usage,
        quote=quote,
        started_at=now,
        completed_at=now,
        idempotency_key=f"usage-event:{uuid.uuid4()}",
    )


def summarize_pending_events(events: list[PendingUsageEvent]) -> AccountingSummary:
    total = sum(
        float(event.quote.final_cost_usd)
        for event in events
        if event.quote.final_cost_usd is not None
    )
    provider_values = [
        float(event.quote.provider_cost_usd)
        for event in events
        if event.quote.provider_cost_usd is not None
    ]
    calculated_values = [
        float(event.quote.calculated_cost_usd)
        for event in events
        if event.quote.calculated_cost_usd is not None
    ]
    unpriced = sum(1 for event in events if event.quote.final_cost_usd is None)
    confidences = {event.quote.cost_confidence for event in events}
    sources = {event.quote.cost_source for event in events}
    if not events:
        confidence = CONFIDENCE_UNKNOWN
        source = COST_SOURCE_UNKNOWN
    elif len(confidences) == 1:
        confidence = next(iter(confidences))
        source = next(iter(sources)) if len(sources) == 1 else "mixed"
    elif unpriced:
        confidence = CONFIDENCE_UNKNOWN
        source = "mixed"
    else:
        confidence = CONFIDENCE_ESTIMATED
        source = "mixed"
    return AccountingSummary(
        operation_id="",
        total_cost_usd=max(0.0, total),
        provider_cost_usd=sum(provider_values) if provider_values else None,
        calculated_cost_usd=(
            sum(calculated_values) if calculated_values else None
        ),
        cost_source=source,
        cost_confidence=confidence,
        unpriced_event_count=unpriced,
        prompt_tokens=sum(event.usage.prompt_tokens for event in events),
        completion_tokens=sum(event.usage.completion_tokens for event in events),
        cached_tokens=sum(event.usage.cached_tokens for event in events),
    )


def _json_text(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _normalize_unit(unit: str | None) -> str:
    value = (unit or "").strip().lower().replace(" ", "_")
    aliases = {
        "credits": "credit",
        "requests": "request",
        "seconds": "second",
        "minutes": "minute",
        "characters": "character",
        "images": "image",
        "tokens": "token",
    }
    return aliases.get(value, value)


def _convert_metered_quantity(
    quantity: float,
    from_unit: str,
    to_unit: str,
) -> float | None:
    if from_unit == to_unit:
        return float(quantity)
    if from_unit == "second" and to_unit == "minute":
        return float(quantity) / 60.0
    if from_unit == "minute" and to_unit == "second":
        return float(quantity) * 60.0
    return None


async def _apply_configured_pricing(
    db: AsyncSession,
    event: PendingUsageEvent,
) -> None:
    """Apply an active admin/contract rate before falling back to LiteLLM."""

    if event.quote.cost_source not in {
        COST_SOURCE_UNKNOWN,
        COST_SOURCE_LITELLM,
        COST_SOURCE_CATALOG,
    }:
        return
    candidates = (
        await db.execute(
            select(PricingSnapshot)
            .where(
                PricingSnapshot.provider_type == event.provider_type,
                PricingSnapshot.service_type == event.service_type,
                PricingSnapshot.source.in_(("admin", "contract")),
                PricingSnapshot.effective_at <= event.started_at,
                (
                    PricingSnapshot.connection_id.is_(None)
                    | (PricingSnapshot.connection_id == event.connection_id)
                ),
                (
                    PricingSnapshot.expires_at.is_(None)
                    | (PricingSnapshot.expires_at > event.started_at)
                ),
            )
            .order_by(
                PricingSnapshot.effective_at.desc(),
                PricingSnapshot.id.desc(),
            )
        )
    ).scalars().all()
    event_unit = _normalize_unit(event.unit or event.usage.metered_unit)
    event_quantity = (
        event.quantity
        if event.quantity is not None
        else event.usage.metered_quantity
    )
    matching: list[
        tuple[PricingSnapshot, str, float, float]
    ] = []
    for candidate in candidates:
        if candidate.model_id and candidate.model_id != event.model_id:
            continue
        try:
            pricing = json.loads(candidate.pricing_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(pricing, dict):
            continue
        candidate_unit = _normalize_unit(pricing.get("unit"))
        candidate_price = _finite_float(pricing.get("unit_price_usd"))
        if not candidate_unit or candidate_price is None:
            continue
        candidate_quantity = event_quantity
        candidate_event_unit = event_unit
        if (
            candidate_quantity is None
            and candidate_unit == "request"
            and event.status.lower()
            not in {"failed", "cancelled", "timeout"}
        ):
            candidate_quantity = 1.0
            candidate_event_unit = "request"
        if candidate_quantity is None:
            continue
        if candidate_event_unit:
            candidate_quantity = _convert_metered_quantity(
                float(candidate_quantity),
                candidate_event_unit,
                candidate_unit,
            )
            if candidate_quantity is None:
                continue
        matching.append(
            (
                candidate,
                candidate_unit,
                candidate_price,
                float(candidate_quantity),
            )
        )
    if not matching:
        return
    snapshot, unit, unit_price, quantity = max(
        matching,
        key=lambda item: (
            item[0].connection_id is not None,
            item[0].model_id is not None,
            item[0].effective_at,
            item[0].id,
        ),
    )

    calculated = max(0.0, float(quantity) * unit_price)
    event.quantity = float(quantity)
    event.unit = unit
    event.pricing_snapshot_id = snapshot.id
    event.quote = CostQuote(
        provider_cost_usd=event.quote.provider_cost_usd,
        calculated_cost_usd=calculated,
        final_cost_usd=calculated,
        cost_source=COST_SOURCE_CONFIGURED,
        cost_confidence=CONFIDENCE_CALCULATED,
        line_items=[
            LineItemQuote(
                category=event.operation_name,
                quantity=float(quantity),
                unit=unit,
                unit_price_usd=unit_price,
                cost_usd=calculated,
                pricing_source=COST_SOURCE_CONFIGURED,
                metadata={"pricing_snapshot_id": snapshot.id},
            )
        ],
        pricing_payload=None,
        pricing_source=COST_SOURCE_CONFIGURED,
    )


async def configured_metered_cost(
    db: AsyncSession,
    *,
    provider_type: str,
    service_type: str,
    model_id: str | None,
    quantity: float,
    unit: str,
    connection_id: int | None = None,
) -> float | None:
    """Return the active configured cost for a known prospective quantity."""

    event = capture_usage_event(
        None,
        ai_model=None,
        provider_type=provider_type,
        service_type=service_type,
        operation_name="budget_hold",
        model_id=model_id,
        status=STATUS_SUCCEEDED,
        quantity=quantity,
        unit=unit,
    )
    event.connection_id = connection_id
    await _apply_configured_pricing(db, event)
    if event.quote.cost_source != COST_SOURCE_CONFIGURED:
        return None
    return event.quote.final_cost_usd


def _hold_buffer() -> float:
    from app.config import get_settings

    return max(1.0, min(2.0, float(get_settings().budget_hold_buffer or 1.10)))


def _unpriced_hold_usd() -> float:
    from app.config import get_settings

    settings = get_settings()
    maximum = max(0.01, min(100.0, float(settings.budget_max_hold_usd or 5.0)))
    fallback = max(0.0001, float(settings.budget_unpriced_hold_usd or 0.05))
    return round(min(maximum, fallback), 8)


def _priced_hold_usd(quoted_usd: float) -> float:
    return round(max(0.0001, float(quoted_usd) * _hold_buffer()), 8)


def catalog_hold_quote(
    *,
    ai_model: AIModel | None,
    provider_type: str | None,
    service_type: str,
    quantity: float | None = None,
    unit: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> float | None:
    """Catalog/normalized rate quote for a prospective hold. Does not call LiteLLM."""

    usage = NormalizedUsage(
        prompt_tokens=max(0, int(prompt_tokens or 0)),
        completion_tokens=max(0, int(completion_tokens or 0)),
        metered_quantity=quantity,
        metered_unit=unit,
    )
    calculated, items, _payload = _catalog_quote(
        ai_model,
        usage,
        provider_type=(provider_type or "unknown").strip().lower() or "unknown",
        service_type=(service_type or "unknown").strip().lower() or "unknown",
        quantity=quantity,
        unit=unit,
    )
    if calculated is not None:
        return max(0.0, float(calculated))
    if items:
        return max(0.0, sum(float(item.cost_usd or 0) for item in items))
    return None


async def quote_hold(
    db: AsyncSession,
    *,
    service_type: str,
    ai_model: AIModel | None = None,
    provider_type: str | None = None,
    model_id: str | None = None,
    connection_id: int | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> HoldQuote:
    """Quote a reservation using configured rates, then catalog; else unpriced fallback.

    Priced holds are ``quote * budget_hold_buffer`` and are not clamped to the
    unpriced maximum. Unpriced operations share one small global fallback.
    """

    service = (service_type or "unknown").strip().lower() or "unknown"
    if service in {"chat", "completion"}:
        service = "llm"
    provider = (provider_type or getattr(ai_model, "provider_type", None) or "unknown")
    provider = str(provider).strip().lower() or "unknown"
    resolved_model = (model_id or getattr(ai_model, "external_id", None) or None)
    resolved_model = str(resolved_model).strip() if resolved_model else None
    configured: float | None = None
    lookup_quantity = quantity
    lookup_unit = (unit or "").strip().lower() or None
    if lookup_quantity is None and (prompt_tokens or completion_tokens) and lookup_unit in {None, "token"}:
        lookup_quantity = float(max(0, int(prompt_tokens or 0)) + max(0, int(completion_tokens or 0)))
        lookup_unit = "token"
    if lookup_quantity is not None and lookup_unit:
        configured = await configured_metered_cost(
            db,
            provider_type=provider,
            service_type=service,
            model_id=resolved_model,
            connection_id=connection_id,
            quantity=float(lookup_quantity),
            unit=lookup_unit,
        )
    if configured is not None:
        return HoldQuote(
            hold_usd=_priced_hold_usd(float(configured)),
            quoted_usd=float(configured),
            cost_source=COST_SOURCE_CONFIGURED,
            priced=True,
        )
    catalog = catalog_hold_quote(
        ai_model=ai_model,
        provider_type=provider,
        service_type=service,
        quantity=quantity,
        unit=unit,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    if catalog is not None:
        return HoldQuote(
            hold_usd=_priced_hold_usd(catalog),
            quoted_usd=catalog,
            cost_source=COST_SOURCE_CATALOG,
            priced=True,
        )
    unpriced = _unpriced_hold_usd()
    return HoldQuote(
        hold_usd=unpriced,
        quoted_usd=None,
        cost_source=COST_SOURCE_UNPRICED,
        priced=False,
    )


async def _pricing_snapshot(
    db: AsyncSession,
    event: PendingUsageEvent,
) -> PricingSnapshot | None:
    payload = event.quote.pricing_payload
    if not payload:
        return None
    payload_text = _json_text(payload)
    fingerprint = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    existing = (
        await db.execute(
            select(PricingSnapshot).where(
                PricingSnapshot.fingerprint == fingerprint
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    row = PricingSnapshot(
        connection_id=event.connection_id,
        provider_type=event.provider_type,
        model_id=event.model_id,
        service_type=event.service_type,
        currency="USD",
        source=event.quote.pricing_source or COST_SOURCE_CATALOG,
        fingerprint=fingerprint,
        pricing_json=payload_text,
        effective_at=event.started_at,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return (
            await db.execute(
                select(PricingSnapshot).where(
                    PricingSnapshot.fingerprint == fingerprint
                )
            )
        ).scalar_one()
    return row


def _subject(
    user_id: int | None,
    alpha_router_api_key_id: int | None,
) -> tuple[str | None, int | None]:
    if alpha_router_api_key_id is not None:
        return SUBJECT_ALPHA_ROUTER_KEY, int(alpha_router_api_key_id)
    if user_id is not None:
        return SUBJECT_USER, int(user_id)
    return None, None


async def persist_usage_operation(
    db: AsyncSession,
    *,
    events: list[PendingUsageEvent],
    user_id: int | None,
    alpha_router_api_key_id: int | None,
    budget_reservation_id: str | None,
    request_log_id: int | None,
    operation_type: str,
    source: str,
    client_app: str | None,
    success: bool,
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AccountingSummary:
    """Persist immutable usage details and signed ledger debits."""

    for event in events:
        await _apply_configured_pricing(db, event)
    summary = summarize_pending_events(events)
    subject_type, subject_id = _subject(user_id, alpha_router_api_key_id)
    operation_key = (
        str(idempotency_key)[:200]
        if idempotency_key
        else (
            f"usage-operation:reservation:{budget_reservation_id}"
            if budget_reservation_id
            else f"usage-operation:{uuid.uuid4()}"
        )
    )
    existing = (
        await db.execute(
            select(UsageOperation).where(
                UsageOperation.idempotency_key == operation_key
            )
        )
    ).scalar_one_or_none()
    if existing:
        return AccountingSummary(
            operation_id=existing.id,
            total_cost_usd=float(existing.total_cost_usd or 0),
            provider_cost_usd=(
                float(existing.provider_cost_usd)
                if existing.provider_cost_usd is not None
                else None
            ),
            calculated_cost_usd=(
                float(existing.calculated_cost_usd)
                if existing.calculated_cost_usd is not None
                else None
            ),
            cost_source="existing",
            cost_confidence=CONFIDENCE_UNKNOWN,
            unpriced_event_count=int(existing.unpriced_event_count or 0),
            prompt_tokens=0,
            completion_tokens=0,
            cached_tokens=0,
            created=False,
        )

    operation = UsageOperation(
        id=str(uuid.uuid4()),
        subject_type=subject_type,
        subject_id=subject_id,
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        budget_reservation_id=budget_reservation_id,
        operation_type=operation_type[:32],
        source=source[:32],
        client_app=(client_app or "")[:128] or None,
        status=STATUS_SUCCEEDED if success else STATUS_FAILED,
        accounting_status=(
            "unpriced"
            if not events or summary.unpriced_event_count == len(events)
            else ("partial" if summary.unpriced_event_count else "priced")
        ),
        idempotency_key=operation_key,
        total_cost_usd=Decimal(str(summary.total_cost_usd)),
        provider_cost_usd=(
            Decimal(str(summary.provider_cost_usd))
            if summary.provider_cost_usd is not None
            else None
        ),
        calculated_cost_usd=(
            Decimal(str(summary.calculated_cost_usd))
            if summary.calculated_cost_usd is not None
            else None
        ),
        unpriced_event_count=summary.unpriced_event_count,
        metadata_json=_json_text(metadata) if metadata else None,
        started_at=min((event.started_at for event in events), default=_now()),
        completed_at=max((event.completed_at for event in events), default=_now()),
    )
    try:
        async with db.begin_nested():
            db.add(operation)
            await db.flush()
    except IntegrityError:
        existing = (
            await db.execute(
                select(UsageOperation).where(
                    UsageOperation.idempotency_key == operation_key
                )
            )
        ).scalar_one()
        return AccountingSummary(
            operation_id=existing.id,
            total_cost_usd=float(existing.total_cost_usd or 0),
            provider_cost_usd=(
                float(existing.provider_cost_usd)
                if existing.provider_cost_usd is not None
                else None
            ),
            calculated_cost_usd=(
                float(existing.calculated_cost_usd)
                if existing.calculated_cost_usd is not None
                else None
            ),
            cost_source="existing",
            cost_confidence=CONFIDENCE_UNKNOWN,
            unpriced_event_count=int(existing.unpriced_event_count or 0),
            prompt_tokens=0,
            completion_tokens=0,
            cached_tokens=0,
            created=False,
        )

    for pending in events:
        snapshot = (
            await db.get(PricingSnapshot, pending.pricing_snapshot_id)
            if pending.pricing_snapshot_id is not None
            else await _pricing_snapshot(db, pending)
        )
        usage_event = UsageEvent(
            id=str(uuid.uuid4()),
            operation_id=operation.id,
            connection_id=pending.connection_id,
            pricing_snapshot_id=snapshot.id if snapshot else None,
            provider_type=pending.provider_type,
            service_type=pending.service_type,
            operation_name=pending.operation_name[:64],
            model_id=(pending.model_id or "")[:512] or None,
            attempt_index=pending.attempt_index,
            upstream_request_id=pending.usage.upstream_request_id,
            idempotency_key=pending.idempotency_key,
            status=pending.status[:24],
            prompt_tokens=pending.usage.prompt_tokens,
            completion_tokens=pending.usage.completion_tokens,
            cached_tokens=pending.usage.cached_tokens,
            cache_write_tokens=pending.usage.cache_write_tokens,
            reasoning_tokens=pending.usage.reasoning_tokens,
            quantity=pending.quantity,
            unit=(pending.unit or "")[:32] or None,
            provider_cost_usd=(
                Decimal(str(pending.quote.provider_cost_usd))
                if pending.quote.provider_cost_usd is not None
                else None
            ),
            calculated_cost_usd=(
                Decimal(str(pending.quote.calculated_cost_usd))
                if pending.quote.calculated_cost_usd is not None
                else None
            ),
            final_cost_usd=(
                Decimal(str(pending.quote.final_cost_usd))
                if pending.quote.final_cost_usd is not None
                else None
            ),
            cost_source=pending.quote.cost_source,
            cost_confidence=pending.quote.cost_confidence,
            raw_usage_json=_json_text(pending.usage.raw_usage),
            error_message=pending.error_message,
            started_at=pending.started_at,
            completed_at=pending.completed_at,
        )
        db.add(usage_event)
        await db.flush()

        for item in pending.quote.line_items:
            db.add(
                CostLineItem(
                    usage_event_id=usage_event.id,
                    category=item.category[:64],
                    quantity=item.quantity,
                    unit=item.unit[:32],
                    unit_price_usd=(
                        Decimal(str(item.unit_price_usd))
                        if item.unit_price_usd is not None
                        else None
                    ),
                    cost_usd=(
                        Decimal(str(item.cost_usd))
                        if item.cost_usd is not None
                        else None
                    ),
                    pricing_source=item.pricing_source[:32],
                    metadata_json=(
                        _json_text(item.metadata) if item.metadata else None
                    ),
                )
            )

        if pending.quote.final_cost_usd is not None:
            db.add(
                LedgerEntry(
                    id=str(uuid.uuid4()),
                    operation_id=operation.id,
                    usage_event_id=usage_event.id,
                    request_log_id=request_log_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    entry_type=ENTRY_DEBIT,
                    amount_usd=Decimal(str(pending.quote.final_cost_usd)),
                    cost_source=pending.quote.cost_source,
                    cost_confidence=pending.quote.cost_confidence,
                    idempotency_key=f"ledger:{pending.idempotency_key}:debit"[:240],
                    description=(
                        f"{pending.service_type}:{pending.operation_name}"
                    )[:255],
                    effective_at=pending.completed_at,
                )
            )

    await db.flush()
    summary.operation_id = operation.id
    return summary


async def create_configured_pricing_snapshot(
    db: AsyncSession,
    *,
    provider_type: str,
    service_type: str,
    unit: str,
    unit_price_usd: float,
    model_id: str | None = None,
    connection_id: int | None = None,
    source: str = "admin",
    effective_at: datetime.datetime | None = None,
    expires_at: datetime.datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> PricingSnapshot:
    """Version an explicit contract/admin rate for non-token services."""

    provider = (provider_type or "").strip().lower()
    service = (service_type or "").strip().lower()
    normalized_unit = _normalize_unit(unit)
    price = _finite_float(unit_price_usd)
    if not provider or not service or not normalized_unit or price is None:
        raise ValueError("provider_type, service_type, unit and non-negative price are required")
    effective = effective_at or _now()
    if expires_at is not None and expires_at <= effective:
        raise ValueError("expires_at must be later than effective_at")
    source_name = "contract" if source == "contract" else "admin"
    model = (model_id or "").strip() or None
    scope_text = _json_text(
        {
            "provider_type": provider,
            "service_type": service,
            "connection_id": connection_id,
            "model_id": model,
        }
    )
    active_scope_key = hashlib.sha256(scope_text.encode("utf-8")).hexdigest()

    active_query = select(PricingSnapshot).where(
        PricingSnapshot.active_scope_key == active_scope_key
    )
    active_rows = (await db.execute(active_query.with_for_update())).scalars().all()

    payload = {
        "provider_type": provider,
        "service_type": service,
        "connection_id": connection_id,
        "model_id": model,
        "unit": normalized_unit,
        "unit_price_usd": price,
        "source": source_name,
        "metadata": metadata or {},
        "effective_at": effective.isoformat(),
    }
    payload_text = _json_text(payload)
    fingerprint = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    row = PricingSnapshot(
        connection_id=connection_id,
        provider_type=provider,
        model_id=model,
        service_type=service,
        currency="USD",
        source=source_name,
        fingerprint=fingerprint,
        active_scope_key=active_scope_key if expires_at is None else None,
        pricing_json=payload_text,
        effective_at=effective,
        expires_at=expires_at,
    )
    try:
        async with db.begin_nested():
            for active_row in active_rows:
                active_row.expires_at = effective
                active_row.active_scope_key = None
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        raise ValueError(
            "A configured rate for this provider scope was updated concurrently; retry"
        ) from exc
    return row


async def create_reconciliation_run(
    db: AsyncSession,
    *,
    provider_type: str,
    source: str,
    connection_id: int | None = None,
    period_start: datetime.datetime | None = None,
    period_end: datetime.datetime | None = None,
    raw_summary: dict[str, Any] | None = None,
) -> ReconciliationRun:
    row = ReconciliationRun(
        id=str(uuid.uuid4()),
        connection_id=connection_id,
        provider_type=(provider_type or "unknown")[:64],
        source=(source or "manual")[:32],
        status="running",
        period_start=period_start,
        period_end=period_end,
        raw_summary_json=_json_text(raw_summary) if raw_summary else None,
    )
    db.add(row)
    await db.flush()
    return row


async def _apply_subject_delta(
    db: AsyncSession,
    *,
    subject_type: str | None,
    subject_id: int | None,
    delta_usd: float,
    occurred_at: datetime.datetime | None = None,
) -> None:
    if subject_type is None or subject_id is None or delta_usd == 0:
        return

    def clamped(column):
        next_value = func.coalesce(column, 0.0) + delta_usd
        return case((next_value < 0, 0.0), else_=next_value)

    if subject_type == SUBJECT_USER:
        statement = update(User).where(User.id == subject_id)
        if occurred_at is not None:
            statement = statement.where(
                User.budget_period_start.is_(None)
                | (User.budget_period_start <= occurred_at)
            )
        await db.execute(
            statement.values(
                budget_used_usd=clamped(User.budget_used_usd)
            ).execution_options(synchronize_session="fetch")
        )
    elif subject_type == SUBJECT_ALPHA_ROUTER_KEY:
        period_is_current = (
            True
            if occurred_at is None
            else (
                AlphaRouterApiKey.period_started_at.is_(None)
                | (AlphaRouterApiKey.period_started_at <= occurred_at)
            )
        )
        period_value = (
            clamped(AlphaRouterApiKey.period_used_usd)
            if period_is_current is True
            else case(
                (
                    period_is_current,
                    clamped(AlphaRouterApiKey.period_used_usd),
                ),
                else_=AlphaRouterApiKey.period_used_usd,
            )
        )
        await db.execute(
            update(AlphaRouterApiKey)
            .where(AlphaRouterApiKey.id == subject_id)
            .values(
                period_used_usd=period_value,
                total_used_usd=clamped(AlphaRouterApiKey.total_used_usd),
            )
            .execution_options(synchronize_session="fetch")
        )


async def reconcile_usage_event(
    db: AsyncSession,
    *,
    event_id: str,
    actual_cost_usd: float,
    reconciliation_run_id: str,
) -> float:
    """Apply an idempotent provider-reported correction and return its delta."""

    event = (
        await db.execute(
            select(UsageEvent)
            .where(UsageEvent.id == event_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    run = (
        await db.execute(
            select(ReconciliationRun)
            .where(ReconciliationRun.id == reconciliation_run_id)
            .with_for_update()
        )
    ).scalar_one()
    operation = (
        await db.execute(
            select(UsageOperation)
            .where(UsageOperation.id == event.operation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    idempotency_key = f"ledger:reconcile:{run.id}:{event.id}"[:240]
    existing = (
        await db.execute(
            select(LedgerEntry).where(
                LedgerEntry.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing:
        return float(existing.amount_usd or 0)

    actual = max(0.0, _signed_float(actual_cost_usd))
    previous = (
        float(event.final_cost_usd)
        if event.final_cost_usd is not None
        else 0.0
    )
    delta = actual - previous
    now = _now()

    event.provider_cost_usd = Decimal(str(actual))
    event.final_cost_usd = Decimal(str(actual))
    event.cost_source = COST_SOURCE_RECONCILED
    event.cost_confidence = CONFIDENCE_RECONCILED
    event.reconciliation_run_id = run.id
    event.reconciled_at = now

    log_row = (
        await db.execute(
            select(RequestLog).where(
                RequestLog.usage_operation_id == operation.id
            )
        )
    ).scalar_one_or_none()
    db.add(
        LedgerEntry(
            id=str(uuid.uuid4()),
            operation_id=operation.id,
            usage_event_id=event.id,
            request_log_id=log_row.id if log_row else None,
            reconciliation_run_id=run.id,
            subject_type=operation.subject_type,
            subject_id=operation.subject_id,
            entry_type=ENTRY_ADJUSTMENT,
            amount_usd=Decimal(str(delta)),
            cost_source=COST_SOURCE_RECONCILED,
            cost_confidence=CONFIDENCE_RECONCILED,
            idempotency_key=idempotency_key,
            description="Provider reconciliation adjustment",
            effective_at=event.completed_at or event.started_at or now,
        )
    )
    await _apply_subject_delta(
        db,
        subject_type=operation.subject_type,
        subject_id=operation.subject_id,
        delta_usd=delta,
        occurred_at=event.completed_at or event.started_at,
    )

    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageEvent.final_cost_usd), 0),
                func.sum(UsageEvent.provider_cost_usd),
                func.sum(UsageEvent.calculated_cost_usd),
            ).where(UsageEvent.operation_id == operation.id)
        )
    ).one()
    cost_states = (
        await db.execute(
            select(
                UsageEvent.cost_source,
                UsageEvent.cost_confidence,
                UsageEvent.final_cost_usd,
            ).where(UsageEvent.operation_id == operation.id)
        )
    ).all()
    unpriced_count = sum(1 for _, _, final in cost_states if final is None)
    sources = {source or COST_SOURCE_UNKNOWN for source, _, _ in cost_states}
    confidences = {
        confidence or CONFIDENCE_UNKNOWN
        for _, confidence, _ in cost_states
    }
    aggregate_source = (
        next(iter(sources)) if len(sources) == 1 else "mixed"
    )
    if unpriced_count:
        aggregate_confidence = CONFIDENCE_UNKNOWN
    elif len(confidences) == 1:
        aggregate_confidence = next(iter(confidences))
    else:
        aggregate_confidence = CONFIDENCE_ESTIMATED
    operation.total_cost_usd = totals[0]
    operation.provider_cost_usd = totals[1]
    operation.calculated_cost_usd = totals[2]
    operation.unpriced_event_count = unpriced_count
    operation.reconciled_at = now
    operation.accounting_status = (
        "unpriced"
        if not cost_states or unpriced_count == len(cost_states)
        else ("partial" if unpriced_count else "priced")
    )

    if log_row:
        log_row.total_cost_usd = float(operation.total_cost_usd or 0)
        log_row.provider_cost_usd = (
            float(operation.provider_cost_usd)
            if operation.provider_cost_usd is not None
            else None
        )
        log_row.calculated_cost_usd = (
            float(operation.calculated_cost_usd)
            if operation.calculated_cost_usd is not None
            else None
        )
        log_row.cost_source = aggregate_source
        log_row.cost_confidence = aggregate_confidence
        log_row.has_unpriced_usage = bool(operation.unpriced_event_count)
        log_row.reconciled_at = now

    run.expected_cost_usd = Decimal(
        str(float(run.expected_cost_usd or 0) + previous)
    )
    run.reported_cost_usd = Decimal(
        str(float(run.reported_cost_usd or 0) + actual)
    )
    run.adjustment_usd = Decimal(
        str(float(run.adjustment_usd or 0) + delta)
    )
    run.matched_event_count = int(run.matched_event_count or 0) + 1
    await db.flush()
    return delta


async def finish_reconciliation_run(
    db: AsyncSession,
    run: ReconciliationRun,
    *,
    error_message: str | None = None,
    unmatched_event_count: int = 0,
) -> None:
    run.status = "failed" if error_message else "completed"
    run.error_message = (error_message or "")[:2000] or None
    run.unmatched_event_count = max(0, int(unmatched_event_count))
    run.completed_at = _now()
    await db.flush()
