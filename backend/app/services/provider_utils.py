"""Provider-facing helpers shared by the chat proxy, billing and helper-LLM paths.

Phase 4.1 moved these out of ``proxy_service`` so that ``chat_title_service``,
``image_prompt_service``, ``image_billing_service``, ``chat_tools_service`` and
the new ``provider_stream`` / ``turn_settlement`` modules can import them
without depending on the 2k-line proxy module (and without the lazy imports
that used to hide the cycle). Pure functions and small coroutines only: no
sessions, no request state.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.models.model_catalog import AIModel
from app.services.failure_details import failure_message
from app.services.llm_providers import (
    litellm_model_for_provider,
    normalize_model_id,
    resolve_litellm_provider,
)
from app.services.usage_accounting_service import NormalizedUsage, PendingUsageEvent, quote_usage

logger = logging.getLogger(__name__)


def apply_litellm_provider_kwargs(kwargs: dict, provider_type: str | None, model_id: str) -> str:
    litellm_model = litellm_model_for_provider(normalize_model_id(model_id), provider_type)
    kwargs["model"] = litellm_model
    llm_provider = resolve_litellm_provider(provider_type)
    if llm_provider:
        kwargs["custom_llm_provider"] = llm_provider
    return litellm_model


def extract_prompt_text(messages: list) -> str:
    parts = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)


_STREAM_BODY_READ_ERROR_MARKERS = (
    "Attempted to access streaming response content, without having called read()",
    "without having called read()",
)


def message_has_stream_body_read_error(msg: str) -> bool:
    return any(marker in msg for marker in _STREAM_BODY_READ_ERROR_MARKERS)


def is_stream_body_read_error(exc: Exception) -> bool:
    return message_has_stream_body_read_error(str(exc))


def should_retry_non_stream(_provider: str, exc: Exception) -> bool:
    return is_stream_body_read_error(exc)


def format_provider_error(exc: Exception, provider: str) -> str:
    """Text for the SSE error frame and the request log — never empty.

    ``str(exc)`` is blank for every httpx timeout and a bare ConnectError, so
    this used to hand the client an error frame with no message and store an
    empty ``error_message`` against the turn.
    """
    msg = str(exc).strip()
    if provider != "openrouter":
        return msg or failure_message(exc)
    for attr in ("message", "body", "text"):
        val = getattr(exc, attr, None)
        if isinstance(val, str) and val.strip() and not message_has_stream_body_read_error(val):
            return val.strip()
    if is_stream_body_read_error(exc):
        return "OpenRouter request failed. Check model availability, context size, and API key."
    return msg or failure_message(exc)


def cached_tokens_from_usage(usage) -> int:
    if not usage:
        return 0
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            cached = details.get("cached_tokens") or 0
        else:
            cached = getattr(details, "cached_tokens", None) or 0
        for key in (
            "cache_read_input_tokens",
            "prompt_cache_hit_tokens",
            "cached_tokens",
        ):
            if usage.get(key):
                cached = cached or usage.get(key) or 0
        return int(cached or 0)
    details = getattr(usage, "prompt_tokens_details", None)
    cached = 0
    if details:
        if isinstance(details, dict):
            cached = int(details.get("cached_tokens") or 0)
        else:
            cached = int(getattr(details, "cached_tokens", None) or 0)
    for key in ("cache_read_input_tokens", "prompt_cache_hit_tokens", "cached_tokens"):
        val = getattr(usage, key, None)
        if val:
            cached = int(val)
            break
    return cached


def usage_from_usage_obj(usage) -> tuple[int, int, int]:
    if not usage:
        return 0, 0, 0
    if isinstance(usage, dict):
        pt = int(usage.get("prompt_tokens") or 0)
        ct = int(usage.get("completion_tokens") or 0)
        return pt, ct, cached_tokens_from_usage(usage)
    pt = int(getattr(usage, "prompt_tokens", 0) or 0)
    ct = int(getattr(usage, "completion_tokens", 0) or 0)
    return pt, ct, cached_tokens_from_usage(usage)


def usage_from_chunk(chunk) -> tuple[int, int, int]:
    pt, ct, cache = usage_from_usage_obj(getattr(chunk, "usage", None))
    if pt or ct or cache:
        return pt, ct, cache
    if hasattr(chunk, "model_dump"):
        try:
            data = chunk.model_dump()
            if isinstance(data, dict):
                return usage_from_usage_obj(data.get("usage"))
        except Exception:  # noqa: BLE001 -- best-effort side effect, failure intentionally ignored (Phase 4: log at DEBUG)
            pass
    return 0, 0, 0


def merge_stream_usage(
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    pt: int,
    ct: int,
    cache: int,
) -> tuple[int, int, int]:
    if pt:
        prompt_tokens = pt
    if ct:
        completion_tokens = ct
    if cache:
        cached_tokens = cache
    return prompt_tokens, completion_tokens, cached_tokens


def usage_from_stream_wrapper(stream) -> tuple[int, int, int]:
    """Read final usage LiteLLM may attach after the stream completes."""
    for attr in ("_last_returned_hidden_params", "_hidden_params", "hidden_params"):
        params = getattr(stream, attr, None)
        if isinstance(params, dict) and params.get("usage"):
            return usage_from_usage_obj(params["usage"])
    return 0, 0, 0


def usage_from_response(response) -> tuple[int, int, int]:
    return usage_from_usage_obj(getattr(response, "usage", None))


def sse_delta_chunk(content: str) -> bytes:
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload)}\n\n".encode()


def sse_error_frame(message: str, *, error_type: str = "provider_error") -> bytes:
    """One SSE ``data:`` frame carrying an error in the OpenAI wire shape.

    ``{"error": {"message": ..., "type": ..., "code": null}}`` is what the OpenAI
    SDKs (and our own ChatPanel) understand; a bare string under ``error`` was
    the pre-Phase-3 form and is still accepted by the frontend.
    """
    payload = {"error": {"message": message, "type": error_type, "code": None}}
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def serialize_stream_chunk(chunk) -> str:
    try:
        return chunk.model_dump_json()
    except Exception:  # noqa: BLE001 -- boundary with an external dependency; degraded result is returned
        if hasattr(chunk, "model_dump"):
            return json.dumps(chunk.model_dump(), default=str)
        return json.dumps(chunk, default=str)


def usage_event_model_id(event: PendingUsageEvent | None) -> str | None:
    if event is None:
        return None

    def _from_raw(value) -> str | None:
        if not isinstance(value, dict):
            return None
        model_value = value.get("model")
        if model_value:
            return str(model_value)
        for key in ("primary", "fallback"):
            nested = _from_raw(value.get(key))
            if nested:
                return nested
        return None

    value = _from_raw(event.usage.raw_usage)
    if value and value.startswith("openrouter/"):
        return value.removeprefix("openrouter/")
    return value


def extract_non_stream_content(response) -> tuple[str, tuple[int, int, int]]:
    content = ""
    if response.choices:
        message = response.choices[0].message
        content = getattr(message, "content", None) or ""
    return content, usage_from_response(response)


def usable_cost_per_1k(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    return rate if rate >= 0 else None


def sanitize_cost_usd(cost: float | None) -> float:
    try:
        value = float(cost or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if value >= 0 else 0.0


def compute_token_cost_usd(
    ai_model: AIModel,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    model_id: str,
    messages,
    completion_text: str,
    provider_type: str | None = None,
) -> float:
    usage = NormalizedUsage(
        prompt_tokens=max(0, int(prompt_tokens or 0)),
        completion_tokens=max(0, int(completion_tokens or 0)),
    )
    quote = quote_usage(
        usage,
        ai_model=ai_model,
        provider_type=provider_type or getattr(ai_model, "provider_type", None),
        service_type="llm",
        model_id=model_id,
        prompt=messages,
        completion=completion_text,
    )
    return sanitize_cost_usd(quote.final_cost_usd)


async def close_upstream_stream(response) -> None:
    """Best-effort close of a LiteLLM stream wrapper and its underlying iterator."""
    seen: set[int] = set()
    for target in (response, getattr(response, "completion_stream", None)):
        if target is None or id(target) in seen:
            continue
        seen.add(id(target))
        aclose = getattr(target, "aclose", None)
        if aclose is None:
            continue
        try:
            result = aclose()
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.debug("Ignoring error while closing upstream stream", exc_info=True)


# Underscored names are what the rest of the code base imported before Phase 4.1.
_apply_litellm_provider_kwargs = apply_litellm_provider_kwargs
_extract_prompt_text = extract_prompt_text
_message_has_stream_body_read_error = message_has_stream_body_read_error
_is_stream_body_read_error = is_stream_body_read_error
_should_retry_non_stream = should_retry_non_stream
_format_provider_error = format_provider_error
_cached_tokens_from_usage = cached_tokens_from_usage
_usage_from_usage_obj = usage_from_usage_obj
_usage_from_chunk = usage_from_chunk
_merge_stream_usage = merge_stream_usage
_usage_from_stream_wrapper = usage_from_stream_wrapper
_usage_from_response = usage_from_response
_sse_delta_chunk = sse_delta_chunk
_sse_error_frame = sse_error_frame
_serialize_stream_chunk = serialize_stream_chunk
_usage_event_model_id = usage_event_model_id
_extract_non_stream_content = extract_non_stream_content
_usable_cost_per_1k = usable_cost_per_1k
_sanitize_cost_usd = sanitize_cost_usd
_compute_token_cost_usd = compute_token_cost_usd
_close_upstream_stream = close_upstream_stream
