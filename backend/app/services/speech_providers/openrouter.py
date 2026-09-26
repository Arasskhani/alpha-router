"""OpenRouter implementation of the provider-neutral speech contract.

OpenRouter exposes ``POST /api/v1/audio/speech`` (OpenAI-compatible) which
returns the synthesized audio as a binary stream.

Wire formats: the endpoint documents ``mp3`` and ``pcm``, but a model may accept
only one of them. Gemini TTS answers only in ``pcm`` and refuses ``mp3`` with a
400 ("Gemini TTS only supports response_format="pcm""). So the format sent is
negotiated per model rather than fixed:

* the caller's preference goes first (``mp3``: small and playable as it is),
  unless the model is known or has been seen to need another;
* a 400 that complains about the format is retried once in the format the
  message names, or else the other one, and the format that worked is
  remembered for that model;
* whatever comes back goes through :func:`playable_audio`, so raw ``pcm`` is
  delivered as WAV, and the reported format and MIME type always match the
  bytes stored.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Any

from app.config import get_settings
from app.core.constants import normalize_openrouter_base_url
from app.services.openrouter_image_service import (
    build_openrouter_headers,
    get_openrouter_http_client,
)
from app.services.speech_providers.audio_container import playable_audio
from app.services.speech_providers.contracts import (
    NormalizedSpeechRequest,
    SpeechGenerationResult,
    SpeechProviderError,
)
from app.services.storage_service import audio_output_limit

# What the endpoint accepts in ``response_format``, in order of preference.
WIRE_FORMATS: tuple[str, ...] = ("mp3", "pcm")

# Models known to accept one wire format only; anything else is learned.
_KNOWN_WIRE_FORMATS: tuple[tuple[re.Pattern[str], str], ...] = ((re.compile(r"^google/gemini[^/]*tts"), "pcm"),)

# Model -> the wire format it last worked with, when that is not the preference.
_LEARNED_WIRE_FORMATS: OrderedDict[str, str] = OrderedDict()
_LEARNED_LIMIT = 512

# "response_format", "response format", "output format": a refusal about the format.
_FORMAT_COMPLAINT = re.compile(r"response[_\s-]?format|\bformat\b", re.IGNORECASE)


normalize_openrouter_base = normalize_openrouter_base_url


def _audio_base(base_url: str | None) -> str:
    return f"{normalize_openrouter_base(base_url)}/audio/speech"


def _normalize_format(value: str | None) -> str:
    raw = (value or "mp3").strip().lower()
    return raw if raw in WIRE_FORMATS else "mp3"


def _model_key(base_url: str | None, model_id: str) -> str:
    return f"{normalize_openrouter_base(base_url)}|{model_id.strip().lower()}"


def wire_format_order(*, base_url: str | None, model_id: str, preferred: str | None) -> list[str]:
    """The wire formats to try for ``model_id``, the likeliest to be accepted first."""
    first = _normalize_format(preferred)
    learned = _LEARNED_WIRE_FORMATS.get(_model_key(base_url, model_id))
    model = model_id.strip().lower()
    known = next((fmt for pattern, fmt in _KNOWN_WIRE_FORMATS if pattern.search(model)), None)
    order = [fmt for fmt in (learned, known, first) if fmt]
    order += [fmt for fmt in WIRE_FORMATS if fmt not in order]
    return list(dict.fromkeys(order))


def _remember_wire_format(*, base_url: str | None, model_id: str, preferred: str, used: str) -> None:
    key = _model_key(base_url, model_id)
    if used == preferred:
        _LEARNED_WIRE_FORMATS.pop(key, None)
        return
    _LEARNED_WIRE_FORMATS[key] = used
    _LEARNED_WIRE_FORMATS.move_to_end(key)
    while len(_LEARNED_WIRE_FORMATS) > _LEARNED_LIMIT:
        _LEARNED_WIRE_FORMATS.popitem(last=False)


def _format_refused(status_code: int, detail: str) -> bool:
    return status_code in {400, 415, 422} and bool(_FORMAT_COMPLAINT.search(detail or ""))


def _next_wire_format(detail: str, remaining: list[str]) -> str | None:
    """The format a refusal names ("only supports response_format="pcm""), else the next untried one."""
    lowered = (detail or "").lower()
    named = sorted(
        (fmt for fmt in remaining if re.search(rf"\b{fmt}\b", lowered)),
        key=lambda fmt: lowered.index(fmt),
    )
    candidates = named or remaining
    return candidates[0] if candidates else None


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


def _status_error(status_code: int, detail: str) -> SpeechProviderError:
    # OpenRouter often wraps upstream failures as "Provider returned NNN".
    status = 400 if status_code in {400, 404, 415, 422} else 502
    if status_code in {401, 402, 429}:
        status = status_code
    return SpeechProviderError(
        f"OpenRouter speech generation failed ({status_code}): {detail}",
        status_code=status,
    )


def _json_error_detail(blob: bytes, content_type: str) -> str | None:
    """The message of a JSON error body sent with a 200 status, if that is what came back."""
    if not (content_type.startswith("application/json") or (len(blob) < 512 and blob.lstrip().startswith(b"{"))):
        return None
    try:
        parsed = json.loads(blob.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 -- falls back to a safe default value
        return None
    if not (isinstance(parsed, dict) and (parsed.get("error") or parsed.get("message"))):
        return None
    detail = "Speech provider returned an error payload"
    err = parsed.get("error")
    if isinstance(err, dict):
        detail = str(err.get("message") or err.get("msg") or detail)[:500]
    elif isinstance(err, str) and err.strip():
        detail = err.strip()[:500]
    elif isinstance(parsed.get("message"), str):
        detail = str(parsed["message"]).strip()[:500]
    return detail


def _usage(response: Any, text: str) -> tuple[dict[str, Any], int, float | None]:
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
        characters = int(characters) if characters is not None else len(text)
    except (TypeError, ValueError):
        characters = len(text)

    duration_seconds = raw_usage.get("duration_seconds") or raw_usage.get("duration")
    try:
        duration_seconds = float(duration_seconds) if duration_seconds is not None else None
    except (TypeError, ValueError):
        duration_seconds = None
    return raw_usage, characters, duration_seconds


class OpenRouterSpeechAdapter:
    provider_type = "openrouter"
    adapter_version = "openrouter-speech-v2"

    def supported_formats(self) -> tuple[str, ...]:
        # What callers may ask for. The answer is mp3, or WAV for models that
        # speak only raw pcm (see the module docstring); ``result.format`` says which.
        return ("mp3",)

    async def _post(self, *, api_key: str, base_url: str | None, request: NormalizedSpeechRequest, fmt: str) -> Any:
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
        try:
            return await get_openrouter_http_client().post(
                _audio_base(base_url),
                json=payload,
                headers=headers,
                timeout=get_settings().speech_http_timeout_seconds,
            )
        except Exception as exc:
            raise SpeechProviderError(
                f"Speech provider request failed: {exc}",
                status_code=502,
            ) from exc

    async def generate(
        self,
        *,
        api_key: str,
        base_url: str | None,
        request: NormalizedSpeechRequest,
    ) -> SpeechGenerationResult:
        model_id = (request.model_id or "").strip()
        preferred = _normalize_format(request.response_format)
        order = wire_format_order(base_url=base_url, model_id=model_id, preferred=preferred)
        tried: list[str] = []
        fmt: str | None = order[0]
        while True:
            assert fmt is not None
            tried.append(fmt)
            response = await self._post(api_key=api_key, base_url=base_url, request=request, fmt=fmt)
            if response.status_code < 400:
                break
            detail = _provider_error_detail(response)
            fmt = None
            if _format_refused(response.status_code, detail):
                fmt = _next_wire_format(detail, [f for f in order if f not in tried])
            if fmt is None:
                raise _status_error(response.status_code, detail)
        wire_format = tried[-1]

        blob = response.content
        if not blob:
            raise SpeechProviderError(
                "OpenRouter returned an empty audio response",
                status_code=502,
            )
        content_type_header = response.headers.get("Content-Type") or ""
        content_type = content_type_header.split(";")[0].strip().lower()
        # Guard against JSON error bodies returned with a 200 status.
        json_error = _json_error_detail(blob, content_type)
        if json_error is not None:
            raise SpeechProviderError(json_error, status_code=502)
        limit = audio_output_limit()
        if len(blob) > limit:
            raise SpeechProviderError(
                "Generated audio exceeds the allowed output limit",
                status_code=413,
            )

        audio = playable_audio(blob, content_type=content_type_header, requested_format=wire_format)
        if audio.duration_seconds == 0:
            raise SpeechProviderError(
                "OpenRouter returned an empty audio response",
                status_code=502,
            )
        if len(audio.blob) > limit:
            raise SpeechProviderError(
                "Generated audio exceeds the allowed output limit",
                status_code=413,
            )
        _remember_wire_format(base_url=base_url, model_id=model_id, preferred=preferred, used=wire_format)

        upstream_request_id = (
            response.headers.get("x-generation-id")
            or response.headers.get("x-request-id")
            or response.headers.get("request-id")
        )
        raw_usage, characters, duration_seconds = _usage(response, request.text)

        return SpeechGenerationResult(
            audio_blob=audio.blob,
            mime=audio.mime,
            format=audio.format,
            duration_seconds=duration_seconds if duration_seconds is not None else audio.duration_seconds,
            characters=characters,
            upstream_request_id=upstream_request_id,
            raw_usage=raw_usage,
        )
