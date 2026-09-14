"""OpenRouter speech-to-text, which is not an OpenAI-compatible endpoint.

OpenRouter exposes ``POST {base}/audio/transcriptions``, but unlike OpenAI it
takes a **JSON body with base64 audio** rather than a ``multipart/form-data``
file upload:

    {"model": "...", "input_audio": {"data": "<base64>", "format": "webm"}}

LiteLLM only knows the OpenAI multipart shape, so routing an OpenRouter model
through it fails at the provider no matter how the model string is spelled.
This adapter talks to OpenRouter directly, in the same style as the existing
image and video adapters, and reuses their pooled client and retry helper.

A nice side effect: OpenRouter reports ``usage.seconds`` (real audio duration)
and ``usage.cost`` (exact USD), so billing uses provider-reported numbers
instead of a size estimate.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from typing import Any

from app.services.openrouter_image_service import (
    build_openrouter_headers,
    post_openrouter_json,
)

#: Formats the OpenRouter transcription endpoint documents.
_SUPPORTED_FORMATS = {"wav", "mp3", "flac", "m4a", "ogg", "webm", "aac", "mp4", "mpeg", "mpga"}
_DEFAULT_FORMAT = "webm"

#: Transcription is a single short request; the image adapter's 180s read
#: timeout and 5 attempts are tuned for slow image generation, not this.
_READ_TIMEOUT = 90.0
_MAX_ATTEMPTS = 2


class OpenRouterTranscriptionError(RuntimeError):
    """Raised with a provider-attributed message when transcription fails."""


@dataclass(slots=True)
class OpenRouterTranscriptionResult:
    """Shaped so `capture_usage_event` reads it like any other provider response.

    ``usage`` deliberately carries ``duration_seconds`` and ``cost``: the
    accounting layer looks for the former to derive a per-second quantity, and
    treats the latter as provider-exact because ``openrouter`` is in
    ``_PROVIDER_REPORTED_USAGE_COST``.
    """

    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    id: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        value = self.usage.get("duration_seconds")
        try:
            return float(value) if value is not None and float(value) > 0 else None
        except (TypeError, ValueError):
            return None


def audio_format_for(filename: str, mime_type: str) -> str:
    """Best-effort container name for the ``input_audio.format`` field."""
    name = (filename or "").strip().lower()
    if "." in name:
        ext = name.rsplit(".", 1)[-1].strip()
        if ext in _SUPPORTED_FORMATS:
            return ext
    mime = (mime_type or "").split(";")[0].strip().lower()
    subtype = mime.rsplit("/", 1)[-1] if "/" in mime else ""
    if subtype == "mpeg":
        return "mp3"
    if subtype == "x-wav":
        return "wav"
    if subtype in _SUPPORTED_FORMATS:
        return subtype
    return _DEFAULT_FORMAT


def transcription_url(base_url: str | None) -> str:
    base = (base_url or "https://openrouter.ai/api/v1").strip().rstrip("/")
    if "openrouter.ai" in base.lower() and "/api/" not in base.lower():
        base = "https://openrouter.ai/api/v1"
    return f"{base}/audio/transcriptions"


def _normalize_usage(raw: Any) -> dict[str, Any]:
    """Map OpenRouter's usage block onto the keys the accounting layer reads."""
    if not isinstance(raw, dict):
        return {}
    usage: dict[str, Any] = dict(raw)
    seconds = raw.get("seconds")
    if seconds is not None and "duration_seconds" not in usage:
        usage["duration_seconds"] = seconds
    return usage


def _error_message(status_code: int, body: str) -> str:
    snippet = (body or "").strip()
    if len(snippet) > 400:
        snippet = snippet[:400] + "…"
    return (
        f"OpenRouter transcription failed ({status_code}): {snippet}"
        if snippet
        else (f"OpenRouter transcription failed ({status_code}).")
    )


async def transcribe_with_openrouter(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    language: str | None = None,
    referer: str | None = None,
) -> OpenRouterTranscriptionResult:
    """Transcribe audio through OpenRouter's JSON transcription endpoint."""
    if not api_key:
        raise OpenRouterTranscriptionError("OpenRouter connection has no API key.")
    if not audio_bytes:
        raise OpenRouterTranscriptionError("Empty audio file.")

    # base64 of a 25 MB recording is ~100 ms of pure CPU; keep it off the loop.
    encoded = await asyncio.to_thread(lambda: base64.b64encode(audio_bytes).decode("ascii"))
    payload: dict[str, Any] = {
        "model": model,
        "input_audio": {
            "data": encoded,
            "format": audio_format_for(filename, mime_type),
        },
    }
    # Omitted entirely when unknown so OpenRouter auto-detects the language.
    if language:
        payload["language"] = language

    response = await post_openrouter_json(
        transcription_url(base_url),
        headers=build_openrouter_headers(api_key, referer=referer),
        json_payload=payload,
        read_timeout=_READ_TIMEOUT,
        max_attempts=_MAX_ATTEMPTS,
    )
    if response.status_code >= 400:
        raise OpenRouterTranscriptionError(_error_message(response.status_code, response.text))

    try:
        data = response.json()
    except ValueError as exc:
        raise OpenRouterTranscriptionError("OpenRouter returned a non-JSON transcription response.") from exc
    if not isinstance(data, dict):
        raise OpenRouterTranscriptionError("OpenRouter returned an unexpected transcription response.")

    text = str(data.get("text") or "").strip()
    if not text:
        # Distinguish "nothing was said" from a transport problem: this is a
        # successful call that simply found no speech.
        raise OpenRouterTranscriptionError("No speech detected. Try speaking closer to the microphone.")

    return OpenRouterTranscriptionResult(
        text=text,
        usage=_normalize_usage(data.get("usage")),
        id=str(data.get("id")) if data.get("id") else None,
    )
