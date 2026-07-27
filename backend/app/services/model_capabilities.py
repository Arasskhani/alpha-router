"""Derive OpenRouter-style model categories and catalog metadata from provider snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

MODEL_KINDS = (
    "text",
    "image",
    "embeddings",
    "audio",
    "video",
    "rerank",
    "speech",
    "transcription",
)


def provider_slug(external_id: str) -> str:
    return ((external_id or "").split("/")[0] or "unknown").strip().lower()


def _catalog_raw(pricing_raw: str | None) -> dict[str, Any]:
    if not pricing_raw:
        return {}
    try:
        data = json.loads(pricing_raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _architecture_from_raw(pricing_raw: str | None) -> dict[str, Any]:
    data = _catalog_raw(pricing_raw)
    arch = data.get("architecture")
    if isinstance(arch, dict):
        return arch
    if "input_modalities" in data or "output_modalities" in data:
        return data
    return {}


def model_catalog_meta(
    *,
    external_id: str,
    display_name: str | None,
    pricing_raw: str | None,
    context_length: int | None = None,
) -> dict[str, Any]:
    """Description and release info from provider snapshot (OpenRouter /v1/models)."""
    raw = _catalog_raw(pricing_raw)
    description = (raw.get("description") or "").strip()
    ctx = raw.get("context_length") or context_length
    created = raw.get("created")
    released_at: str | None = None
    if created is not None:
        try:
            released_at = datetime.fromtimestamp(int(created), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            released_at = None
    title = (display_name or raw.get("name") or external_id or "").strip()
    return {
        "title": title,
        "description": description,
        "context_length": int(ctx) if ctx is not None else None,
        "provider_author": provider_slug(external_id),
        "released_at": released_at,
    }


def _modalities(arch: dict[str, Any]) -> tuple[list[str], list[str]]:
    def _list(key: str) -> list[str]:
        raw = arch.get(key) or []
        if not isinstance(raw, list):
            return []
        return [str(x).lower() for x in raw if str(x).strip()]

    return _list("input_modalities"), _list("output_modalities")


def _image_id_heuristic(external_id: str, is_image_model: bool = False) -> bool:
    ext = (external_id or "").lower()
    return bool(
        is_image_model
        or "image" in ext
        or "dall" in ext
        or "flux" in ext
        or "sdxl" in ext
        or "stable-diffusion" in ext
        or "nanobanana" in ext
        or "midjourney" in ext
    )


def _image_to_image_heuristic(external_id: str) -> bool:
    ext = (external_id or "").lower()
    if "gemini" in ext and "image" in ext:
        return True
    return any(
        hint in ext
        for hint in (
            "kontext",
            "img2img",
            "image-to-image",
            "image_edit",
            "image-edit",
            "/edit",
        )
    )


def image_generation_capabilities(
    *,
    external_id: str,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
) -> dict[str, bool]:
    """Detect text-to-image and image-to-image support from provider catalog metadata."""
    arch = _architecture_from_raw(pricing_raw)
    inputs, outputs = _modalities(arch)
    has_catalog = bool(inputs or outputs)

    if has_catalog:
        supports_t2i = "image" in outputs
        supports_i2i = "image" in inputs and "image" in outputs
        return {
            "supports_text_to_image": supports_t2i,
            "supports_image_to_image": supports_i2i,
        }

    heuristic = _image_id_heuristic(external_id, is_image_model)
    supports_i2i = _image_to_image_heuristic(external_id)
    return {
        "supports_text_to_image": heuristic or supports_i2i,
        "supports_image_to_image": supports_i2i,
    }


def model_kinds(
    *,
    external_id: str,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
) -> list[str]:
    """Return applicable filter tags (a model may match several, like OpenRouter)."""
    ext = (external_id or "").lower()
    arch = _architecture_from_raw(pricing_raw)
    inputs, outputs = _modalities(arch)
    kinds: set[str] = set()

    if "embed" in ext or "embedding" in ext:
        kinds.add("embeddings")
    if "rerank" in ext:
        kinds.add("rerank")
    if any(x in ext for x in ("whisper", "transcribe", "transcription", "/stt")):
        kinds.add("transcription")
    if any(x in ext for x in ("tts", "/speech", "text-to-speech")):
        kinds.add("speech")
    if is_image_model or any(
        x in ext for x in ("dall-e", "dalle", "stable-diffusion", "flux", "midjourney", "/image")
    ):
        kinds.add("image")
    if "video" in inputs or "video" in outputs or "video" in ext:
        kinds.add("video")
    if ("audio" in inputs or "audio" in outputs) and "transcription" not in kinds:
        if "whisper" not in ext:
            kinds.add("audio")
    if "text" in outputs or "text" in inputs:
        kinds.add("text")
    if not kinds:
        if not any(
            k in ext
            for k in ("embed", "rerank", "whisper", "tts", "dall", "flux", "video", "audio")
        ):
            kinds.add("text")
    return [k for k in MODEL_KINDS if k in kinds]


_VISION_HEURISTIC_HINTS = (
    "vision",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4-turbo",
    "gpt-4",
    "claude-3",
    "claude-4",
    "claude-sonnet",
    "claude-opus",
    "claude-haiku",
    "gemini",
    "llava",
    "pixtral",
    "qwen-vl",
    "qwen2-vl",
)


def supports_vision(
    *,
    external_id: str,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
) -> bool:
    """True when a chat model can accept an image attachment (vision input).

    Image-generation models use a separate image-to-image path and are excluded.
    Provider catalog metadata (``architecture.input_modalities``) takes precedence;
    a name-based heuristic is used as a fallback for models without catalog metadata.
    """
    ext = (external_id or "").lower()
    if is_image_model or _image_id_heuristic(ext):
        return False

    arch = _architecture_from_raw(pricing_raw)
    inputs, _ = _modalities(arch)
    if inputs:
        return "image" in inputs

    # Fallback heuristic when provider metadata is unavailable.
    if ext in ("auto", "openrouter/auto") or ext.endswith("/auto"):
        return True
    return any(hint in ext for hint in _VISION_HEURISTIC_HINTS)
