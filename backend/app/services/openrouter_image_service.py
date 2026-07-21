"""Fast OpenRouter image generation helpers (connection reuse + routing)."""

from __future__ import annotations

import asyncio
import re

import httpcore
import httpx

OPENROUTER_CONNECT_TIMEOUT = 15.0
# GPT-5.4 Image and similar OpenRouter image models often need 130–150s; keep headroom.
OPENROUTER_READ_TIMEOUT = 180.0
OPENROUTER_FALLBACK_TIMEOUT = 180.0
# Gemini Pro Image often drops mid-flight; give each strategy several reconnects.
OPENROUTER_IMAGE_MAX_ATTEMPTS = 5
OPENROUTER_DISCONNECT_BACKOFF_SEC = (1.0, 2.0, 4.0, 6.0)
# Backoff between chat/completions retries when OpenRouter returns HTTP 200 with no image.
OPENROUTER_EMPTY_IMAGE_RETRY_DELAYS_SEC = (1.5, 3.0, 5.0, 7.0)
# Cap completion budget so providers do not advertise 32k tokens (seen causing 402 / drops).
OPENROUTER_IMAGE_MAX_TOKENS = 4096

_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.ConnectError,
    httpx.WriteError,
    httpx.PoolTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.ConnectTimeout,
    httpx.TimeoutException,
    httpcore.RemoteProtocolError,
    httpcore.ReadError,
    httpcore.ConnectError,
    httpcore.WriteError,
)

_shared_client: httpx.AsyncClient | None = None


def is_retryable_openrouter_transport_error(exc: BaseException) -> bool:
    """True for disconnects / timeouts that should try another connection or strategy."""
    if isinstance(exc, _RETRYABLE_EXC):
        return True
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "disconnected",
            "connection reset",
            "connection closed",
            "server disconnected",
            "timed out",
            "timeout",
        )
    )


def get_openrouter_http_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        # Keepalive=0 avoids reusing half-closed sockets after long Gemini image waits.
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(OPENROUTER_READ_TIMEOUT, connect=OPENROUTER_CONNECT_TIMEOUT),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=0),
            follow_redirects=True,
            http2=False,
        )
    return _shared_client


async def close_openrouter_http_client() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


def _is_gemini_image_model(model_id: str) -> bool:
    low = (model_id or "").lower()
    return "gemini" in low and "image" in low


def is_openai_gpt_image_model(model_id: str) -> bool:
    low = (model_id or "").lower()
    return "gpt" in low and "image" in low


def is_openrouter_auto_model(model_id: str) -> bool:
    low = (model_id or "").strip().lower()
    return low in ("openrouter/auto", "auto") or low.endswith("/auto")


def openrouter_image_modalities(model_id: str) -> list[str]:
    """Modalities for OpenRouter chat/completions image generation."""
    if is_openrouter_auto_model(model_id):
        return ["image", "text"]
    low = (model_id or "").lower()
    image_only_hints = (
        "flux",
        "sourceful",
        "riverflow",
        "dall-e",
        "dalle",
        "stable-diffusion",
        "sdxl",
    )
    if any(h in low for h in image_only_hints):
        return ["image"]
    if is_openai_gpt_image_model(model_id):
        return ["image"]
    return ["image", "text"]


def prefer_openrouter_images_generations(model_id: str) -> bool:
    """Prefer /images/generations over chat/completions for these models."""
    low = (model_id or "").lower()
    if is_openai_gpt_image_model(model_id):
        return True
    return any(
        h in low
        for h in (
            "flux",
            "sourceful",
            "riverflow",
            "dall-e",
            "dalle",
            "stable-diffusion",
            "sdxl",
        )
    )


def _has_routing_suffix(model_id: str) -> bool:
    low = (model_id or "").lower()
    return any(s in low for s in (":nitro", ":floor", ":free", ":extended"))


def optimize_openrouter_image_model(model_id: str, *, chat_completions: bool = False) -> str:
    """
    Optionally append OpenRouter :nitro routing for diffusion-style /images/generations.

    Chat-completions image models must keep the raw model id; :nitro can route to
    providers that drop long-running multimodal image requests.
    """
    raw = (model_id or "").strip()
    if not raw or _has_routing_suffix(raw) or chat_completions:
        return raw
    low = raw.lower()
    if any(
        h in low
        for h in (
            "flux",
            "dall-e",
            "dalle",
            "stable-diffusion",
            "sdxl",
        )
    ):
        return f"{raw}:nitro"
    return raw


def default_openrouter_image_provider_sort(model_id: str) -> str | None:
    """Route multimodal image models for stability; omit sort for diffusion-style ids.

    Gemini Pro Image is more reliable without latency-sorting (fastest hops often
    drop long image responses). Flash-tier Gemini still prefers latency.
    """
    low = (model_id or "").lower()
    if "gemini" in low and "pro" in low and "image" in low:
        return None
    if _is_gemini_image_model(model_id) or is_openai_gpt_image_model(model_id):
        return "latency"
    if any(h in low for h in ("flux", "dall-e", "dalle", "stable-diffusion", "sdxl")):
        return None
    return "latency"


def is_transient_empty_openrouter_image_response(
    data: dict | None,
    *,
    collected: list | None,
) -> bool:
    """
    True when OpenRouter returned HTTP 200 but no usable image payload.

    Empty shells, text-only replies, and unparseable ``images`` fields are all
    treated as retryable — Gemini/OpenRouter often flake to a text acknowledgement
    on one provider route and succeed on the next strategy.
    """
    del data  # shape inspected by callers for errors; retry decision is payload-based
    return not bool(collected)


def build_openrouter_headers(api_key: str, *, referer: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if referer:
        headers["HTTP-Referer"] = referer
        headers["X-Title"] = "nitro"
    return headers


async def post_openrouter_json(
    url: str,
    *,
    headers: dict[str, str],
    json_payload: dict,
    read_timeout: float | None = None,
    max_attempts: int = OPENROUTER_IMAGE_MAX_ATTEMPTS,
) -> httpx.Response:
    """POST JSON to OpenRouter with retries on transient disconnects."""
    last_exc: Exception | None = None
    timeout = httpx.Timeout(read_timeout or OPENROUTER_READ_TIMEOUT, connect=OPENROUTER_CONNECT_TIMEOUT)
    attempts = max(1, int(max_attempts))
    req_headers = dict(headers)
    # Prefer a fresh TCP connection for large multimodal responses.
    req_headers.setdefault("Connection", "close")

    for attempt in range(attempts):
        client = get_openrouter_http_client()
        try:
            return await client.post(url, headers=req_headers, json=json_payload, timeout=timeout)
        except Exception as exc:
            if not is_retryable_openrouter_transport_error(exc):
                raise
            last_exc = exc
            await close_openrouter_http_client()
            if attempt + 1 >= attempts:
                break
            delay_idx = min(attempt, len(OPENROUTER_DISCONNECT_BACKOFF_SEC) - 1)
            await asyncio.sleep(OPENROUTER_DISCONNECT_BACKOFF_SEC[delay_idx])

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("OpenRouter request failed")


def _gemini_image_size_tier(size: str) -> str:
    """Infer OpenRouter image_size tier from requested WxH dimensions."""
    normalized = (size or "").strip().lower()
    match = re.fullmatch(r"(\d+)x(\d+)", normalized)
    if not match:
        return "1K"
    w = int(match.group(1))
    h = int(match.group(2))
    max_dim = max(w, h)
    if max_dim >= 2048:
        return "4K"
    if max_dim >= 1536:
        return "2K"
    return "1K"


def max_image_size_tier_for_model(model_id: str) -> str:
    """Highest OpenRouter image_size tier likely supported by this model."""
    if not _is_gemini_image_model(model_id):
        return "1K"
    low = (model_id or "").lower()
    if "lite" in low:
        return "1K"
    if "3-pro-image" in low or "pro-image-preview" in low:
        return "1K"
    if "preview" in low and "3.1" not in low:
        return "1K"
    if "3.1-flash-image" in low or "nanobanana" in low:
        return "4K"
    if "2.5-flash-image" in low:
        return "4K"
    return "2K"


_TIER_RANK = {"1K": 1, "2K": 2, "4K": 3}


def clamp_image_size_tier(tier: str | None, model_id: str) -> str | None:
    """Clamp a requested tier to what the model likely supports."""
    if not tier:
        return None
    normalized = str(tier).strip().upper()
    if normalized not in _TIER_RANK:
        return None
    cap = max_image_size_tier_for_model(model_id)
    return normalized if _TIER_RANK[normalized] <= _TIER_RANK[cap] else cap


def gemini_image_size_for_model(model_id: str, size: str) -> str:
    """Pick a safe OpenRouter image_size tier for this model and dimensions."""
    return clamp_image_size_tier(_gemini_image_size_tier(size), model_id) or "1K"


def build_fast_openrouter_payload(
    *,
    model_id: str,
    prompt: str,
    size: str,
    modalities: list[str],
    aspect_ratio: str,
    reference_image: str | None = None,
    allow_fallbacks: bool = True,
    image_size_tier: str | None = None,
    provider_sort: str | None = None,
    apply_default_provider_sort: bool = True,
) -> dict:
    model = optimize_openrouter_image_model(model_id, chat_completions=True)
    image_config: dict[str, str] = {"aspect_ratio": aspect_ratio}
    if _is_gemini_image_model(model_id):
        raw_tier = image_size_tier or _gemini_image_size_tier(size)
        image_config["image_size"] = clamp_image_size_tier(raw_tier, model_id) or "1K"

    ref = (reference_image or "").strip()
    if ref:
        content: list[dict] | str = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": ref}},
        ]
    else:
        content = prompt

    if provider_sort is None and apply_default_provider_sort:
        provider_sort = default_openrouter_image_provider_sort(model_id)

    provider: dict[str, object] = {"allow_fallbacks": allow_fallbacks}
    if provider_sort:
        provider["sort"] = provider_sort

    payload: dict = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": modalities,
        "stream": False,
        "image_config": image_config,
        "provider": provider,
    }
    if _is_gemini_image_model(model_id) or is_openai_gpt_image_model(model_id):
        payload["max_tokens"] = OPENROUTER_IMAGE_MAX_TOKENS
    return payload
