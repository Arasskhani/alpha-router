"""OpenRouter implementation of the provider-neutral speech contract.

OpenRouter exposes ``POST /api/v1/audio/speech`` (OpenAI-compatible) which
returns the synthesized audio as a binary stream.

Documented formats for this endpoint are ``mp3`` and ``pcm`` only.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.openrouter_image_service import (
    build_openrouter_headers,
    get_openrouter_http_client,
)
from app.services.speech_providers.contracts import (
    NormalizedSpeechRequest,
    SpeechGenerationResult,
    SpeechProviderError,
)
from app.services.storage_service import audio_output_limit

_FORMAT_TO_MIME: dict[str, str] = {
    "mp3": "audio/mpeg",
    "pcm": "audio/pcm",
}


def normalize_openrouter_base(base_url: str | None) -> str:
    base = (base_url or "https://openrouter.ai/api/v1").strip().rstrip("/")
    if not base:
        return "https://openrouter.ai/api/v1"
    low = base.lower()
    # Admins often save https://openrouter.ai; force API root to avoid HTML pages.
    if "openrouter.ai" in low and "/api/" not in low:
        return "https://openrouter.ai/api/v1"
    return base


def _audio_base(base_url: str | None) -> str:
    return f"{normalize_openrouter_base(base_url)}/audio/speech"


def _normalize_format(value: str | None) -> str:
    raw = (value or "mp3").strip().lower()
    return raw if raw in _FORMAT_TO_MIME else "mp3"


def _mime_for_format(fmt: str) -> str:
    return _FORMAT_TO_MIME.get(fmt, "audio/mpeg")


def _provider_error_detail(response: Any) -> str:
    text = (getattr(response, "text", None) or "")[:800]
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return text or "Speech provider request )
        return text or "Speech provider request failed"
    if not isinstance(payload, dict):
        return text or "Speech provider request failed"
    err = payload.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("msg") or err.get("code")
        if msg:
            return str(msg)[:500]
    if isinstance(err, str) and err.strip():
        return err.strip()[:500]
    msg = payload.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()[:500]
    return text or "Speech provider request failed"


class OpenRouterSpeechAdapter:
    provider_type = "openrouter"
    adapter_version = "openrouter-speech-v1"

    def supported_formats(self) -> tuple[str, ...]:
        # Chat TTS surface is mp3-only; pcm remains available for internal/API use.
        return ("mp3",)

    async def generate(  # noqa: C901 -- Phase 4 split; complexity must not grow
        self,
        *,
        api_key: str,
        base_url: str | None,
        request: NormalizedSpeechRequest,
    ) -> SpeechGenerationResult:
        fmt = _normalize_format(request.response_format)
        payload: dict[str, Any] = {
            "model": (request.model_id or "").strip(),
            "input": request.text,
            "response_format": fmt,
        }
        voice = (request.voice or "").strip()
        if voice:
            payload["voice"] = voice
        if request.speed is not None:
            try:
                speed = float(request.speed)
                if 0.25 <= speed <= 4.0:
                    payload["speed"] = speed
            except (TypeError, ValueError):
                pass

        headers = build_openrouter_headers(api_key)
        # Prefer binary audio; avoid forcing a specific audio MIME which some
        # upstream providers reject with 400.
        headers["Accept"] = "application/octet-stream, audio/*, */*"

        client = get_openrouter_http_client()
        limit = audio_output_limit()
        try:
            response = await client.post(
                _audio_base(base_url),
                json=payload,
                headers=headers,
                timeout=120.0,
            )
        except Exception as exc:
            raise SpeechProviderError(
                f"Speech provider request failed: {exc}",
                status_code=502,
            ) from exc

        if response.status_code >= 400:
            detail = _provider_error_detail(response)
            # OpenRouter often wraps upstream failures as "Provider returned NNN".
            status = 400 if response.status_code in {400, 404, 422} else 502
            if response.status_code == 402:
                status = 402
            elif response.status_code == 429:
                status = 429
            elif response.status_code == 401:
                status = 401
            raise SpeechProviderError(
                f"OpenRouter speech generation failed ({response.status_code}): {detail}",
                status_code=status,
            )

        blob = response.content
        if not blob:
            raise SpeechProviderError(
                "OpenRouter returned an empty audio response",
                status_code=502,
            )
        # Guard against JSON error bodies returned with a 200 status.
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type.startswith("application/json") or (len(blob) < 512 and blob.lstrip().startswith(b"{")):
            try:
                parsed = json.loads(blob.decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001 -- falls back to a safe default value
                parsed = None
            if isinstance(parsed, dict) and (parsed.get("error") or parsed.get("message")):
                detail = "Speech provider returned an error payload"
                err = parsed.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("message") or err.get("msg") or detail)[:500]
                elif isinstance(err, str) and err.strip():
                    detail = err.strip()[:500]
                elif isinstance(parsed.get("message"), str):
                    detail = str(parsed["message"]).strip()[:500]
                raise SpeechProviderError(detail, status_code=502)
        if len(blob) > limit:
            raise SpeechProviderError(
                "Generated audio exceeds the allowed output limit",
                status_code=413,
            )

        mime = content_type if content_type.startswith("audio/") else _mime_for_format(fmt)

        upstream_request_id = (
            response.headers.get("x-generation-id")
            or response.headers.get("x-request-id")
            or response.headers.get("request-id")
        )

        raw_usage: dict[str, Any] = {}
        usage_header = response.headers.get("x-usage") or response.headers.get("usage")
        if usage_header:
            try:
                parsed = json.loads(usage_header)
                if isinstance(parsed, dict):
                    raw_usage = parsed
            except (ValueError, TypeError):
                pass

        characters = raw_usage.get("characters") or raw_usage.get("character_count")
        try:
            characters = int(characters) if characters is not None else len(request.text)
        except (TypeError, ValueError):
            characters = len(request.text)

        duration_seconds = raw_usage.get("duration_seconds") or raw_usage.get("duration")
        try:
            duration_seconds = float(duration_seconds) if duration_seconds is not None else None
        except (TypeError, ValueError):
            duration_seconds = None

        return SpeechGenerationResult(
            audio_blob=blob,
            mime=mime,
            format=fmt,
            duration_seconds=duration_seconds,
            characters=characters,
            upstream_request_id=upstream_request_id,
            raw_usage=raw_usage,
        )
