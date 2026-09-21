"""Derive OpenRouter-style model categories and catalog metadata from provider snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.services.provider_modalities import provider_modalities

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


def authoritative_video_model(
    *,
    provider_type: str | None,
    is_video_model: bool,
    pricing_raw: str | None,
) -> bool:
    """Return Video status using the provider's authoritative catalog.

    OpenRouter's general `/models` snapshot can advertise video output for
    non-video-generation models. Its dedicated `/videos/models` snapshot is
    embedded under `video_generation` / `video_capabilities`, so use that
    source when determining the Video tool catalog.
    """
    if (provider_type or "").strip().lower() == "openrouter":
        raw = _catalog_raw(pricing_raw)
        if raw:
            return isinstance(raw.get("video_generation") or raw.get("video_capabilities"), dict)
        # No snapshot at all: the stored flag is the only evidence anyone ever
        # recorded, and the two mistakes are not symmetric. Ignoring it would
        # offer a video model for chat, which fails in front of a user;
        # trusting it only risks hiding one from a filter.
    return bool(is_video_model)


def authoritative_image_model(
    *,
    provider_type: str | None,
    is_image_model: bool,
    pricing_raw: str | None,
) -> bool:
    """Return Image Generation status from the provider's dedicated catalog."""
    if (provider_type or "").strip().lower() == "openrouter":
        raw = _catalog_raw(pricing_raw)
        if raw:
            return isinstance(raw.get("image_generation"), dict)
        # See authoritative_video_model: with nothing stored, the flag stands.
    return bool(is_image_model)


def _architecture_from_raw(pricing_raw: str | None) -> dict[str, Any]:
    """Modalities the provider stated, in our vocabulary.

    This used to read OpenRouter's ``architecture`` block and nothing else, so
    a provider that publishes the same facts in its own shape — Google's
    ``supportedGenerationMethods``, Azure's ``capabilities`` map — was treated
    as having said nothing, and the classifier fell back to guessing from the
    model id. ``provider_modalities`` translates every dialect we know; the
    return shape stays an architecture-like dict so the rest of this module is
    unchanged.
    """
    stated = provider_modalities(_catalog_raw(pricing_raw))
    if stated is None:
        return {}
    return {
        "input_modalities": list(stated.inputs),
        "output_modalities": list(stated.outputs),
    }


def classification_source(pricing_raw: str | None) -> str:
    """``provider`` when the catalog answered, ``inferred`` when we guessed.

    An operator looking at a model in the wrong category needs to know which
    of the two happened before they can do anything about it: a wrong
    ``provider`` answer is a bug or a provider error, a wrong ``inferred`` one
    is a model whose id misled us and which nothing but a human can correct.
    """
    return "provider" if provider_modalities(_catalog_raw(pricing_raw)) else "inferred"


def classification_dialect(pricing_raw: str | None) -> str | None:
    """Which provider vocabulary answered, or None when none did."""
    stated = provider_modalities(_catalog_raw(pricing_raw))
    return stated.dialect if stated else None


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
            released_at = datetime.fromtimestamp(int(created), tz=UTC).date().isoformat()
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


def catalog_output_modalities(pricing_raw: str | None) -> list[str]:
    """Output modalities the provider catalog advertises (empty when unknown).

    For OpenRouter image models `model_sync` stores the dedicated image
    catalog's `architecture` block, so this is the authoritative answer to
    "can this model emit text as well as an image?".
    """
    _inputs, outputs = _modalities(_architecture_from_raw(pricing_raw))
    return outputs


# The only list of name fragments in the codebase that suggests image
# generation. It is a guess about a model from its id, so it is consulted in
# exactly one situation: the provider published no modality metadata at all.
# Wherever the provider did answer, its answer wins -- including when it
# contradicts a name that appears here.
#
# `model_sync` used to keep a second, shorter copy of this list, so the same
# model could be classified one way at sync time and another at read time.
IMAGE_ID_HINTS: tuple[str, ...] = (
    "image",
    "dall",
    "flux",
    "sdxl",
    "stable-diffusion",
    "nanobanana",
    "midjourney",
)


def image_id_looks_generative(external_id: str) -> bool:
    """Last-resort guess from the model id. Never call this over provider data."""
    ext = (external_id or "").lower()
    return any(hint in ext for hint in IMAGE_ID_HINTS)


def _image_id_heuristic(external_id: str, is_image_model: bool = False) -> bool:
    return bool(is_image_model or image_id_looks_generative(external_id))


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


def _video_id_heuristic(external_id: str, is_video_model: bool = False) -> bool:
    del external_id
    return bool(is_video_model)


def _video_catalog_meta(pricing_raw: str | None) -> dict[str, Any]:
    """Optional OpenRouter video-models snapshot fields embedded in pricing_raw."""
    raw = _catalog_raw(pricing_raw)
    video = raw.get("video_capabilities") or raw.get("video_generation")
    if isinstance(video, dict):
        return video
    # Direct video-models endpoint shape may be stored as the root snapshot.
    if any(
        key in raw
        for key in (
            "supported_durations",
            "supported_resolutions",
            "supported_aspect_ratios",
            "supported_frame_images",
        )
    ):
        return raw
    return {}


def video_generation_capabilities(
    *,
    external_id: str,
    is_video_model: bool = False,
    pricing_raw: str | None = None,
) -> dict[str, Any]:
    """Detect text-to-video and image-to-video support from provider catalog metadata."""
    arch = _architecture_from_raw(pricing_raw)
    inputs, outputs = _modalities(arch)
    has_catalog = bool(inputs or outputs)
    video_meta = _video_catalog_meta(pricing_raw)
    frame_images = video_meta.get("supported_frame_images")
    if isinstance(frame_images, list):
        frame_support = {str(x).lower() for x in frame_images if str(x).strip()}
    else:
        frame_support = set()

    if has_catalog:
        supports_t2v = "video" in outputs
        supports_i2v = ("image" in inputs and "video" in outputs) or bool(frame_support)
        return {
            "supports_text_to_video": supports_t2v,
            "supports_image_to_video": supports_i2v,
            "supported_durations": video_meta.get("supported_durations"),
            "supported_resolutions": video_meta.get("supported_resolutions"),
            "supported_aspect_ratios": video_meta.get("supported_aspect_ratios"),
            "supported_frame_images": list(frame_support) if frame_support else None,
        }

    heuristic = _video_id_heuristic(external_id, is_video_model)
    return {
        "supports_text_to_video": heuristic,
        "supports_image_to_video": heuristic and bool(frame_support),
        "supported_durations": video_meta.get("supported_durations"),
        "supported_resolutions": video_meta.get("supported_resolutions"),
        "supported_aspect_ratios": video_meta.get("supported_aspect_ratios"),
        "supported_frame_images": list(frame_support) if frame_support else None,
    }


def model_kinds(
    *,
    external_id: str,
    is_image_model: bool = False,
    is_video_model: bool = False,
    pricing_raw: str | None = None,
    provider_type: str | None = None,
) -> list[str]:
    """Return applicable filter tags — the single source of truth for categorization.

    Media kinds (image, video, audio) are derived from **output** modalities and
    the provider's authoritative generation catalog — not from input modalities.
    A model that merely *accepts* video/audio as input (e.g. a vision model that
    can analyse a video clip) must not appear in the Video or Audio filter.

    ID-based heuristics are a last-resort fallback when the provider supplies
    no architecture metadata at all.
    """
    ext = (external_id or "").lower()
    arch = _architecture_from_raw(pricing_raw)
    inputs, outputs = _modalities(arch)
    has_metadata = bool(inputs or outputs)
    kinds: set[str] = set()

    # --- Authoritative media flags (provider-specific) ---
    auth_video = authoritative_video_model(
        provider_type=provider_type,
        is_video_model=is_video_model,
        pricing_raw=pricing_raw,
    )
    auth_image = authoritative_image_model(
        provider_type=provider_type,
        is_image_model=is_image_model,
        pricing_raw=pricing_raw,
    )

    # --- Embeddings / rerank / transcription / speech: output modality first, ID fallback ---
    if has_metadata:
        if "embeddings" in outputs:
            kinds.add("embeddings")
        if "rerank" in outputs:
            kinds.add("rerank")
        if "transcription" in outputs:
            kinds.add("transcription")
        if "speech" in outputs:
            kinds.add("speech")
    else:
        if "embed" in ext or "embedding" in ext:
            kinds.add("embeddings")
        if "rerank" in ext:
            kinds.add("rerank")
        if any(x in ext for x in ("whisper", "transcribe", "transcription", "/stt")):
            kinds.add("transcription")
        if any(x in ext for x in ("tts", "/speech", "text-to-speech")):
            kinds.add("speech")

    # --- Image and video ---
    #
    # For OpenRouter the dedicated /images/models and /videos/models catalogs
    # are the answer and the general catalog is not: `/models` advertises media
    # output for models those endpoints do not serve. `model_sync` trims the
    # stored snapshot to match, but a row written before that trimming existed
    # still carries the untrimmed list, so the rule is enforced here as well
    # rather than trusting every row to have been written correctly.
    openrouter = (provider_type or "").strip().lower() == "openrouter"

    if auth_image or (
        not openrouter
        and (
            (has_metadata and "image" in outputs)
            or (
                not has_metadata
                and any(x in ext for x in ("dall-e", "dalle", "stable-diffusion", "flux", "midjourney", "/image"))
            )
        )
    ):
        kinds.add("image")

    if auth_video or (
        not openrouter
        and (
            (has_metadata and "video" in outputs)
            or (not has_metadata and _video_id_heuristic(external_id, is_video_model))
        )
    ):
        kinds.add("video")

    # --- Audio: output modality only (not input) ---
    if has_metadata:
        if "audio" in outputs and "transcription" not in kinds and "whisper" not in ext:
            kinds.add("audio")
    else:
        if "audio" in ext and "transcription" not in kinds and "whisper" not in ext:
            kinds.add("audio")

    # --- Text: output modality only ---
    if has_metadata:
        if "text" in outputs:
            kinds.add("text")
    else:
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


def _speech_catalog_meta(pricing_raw: str | None) -> dict[str, Any]:
    """OpenRouter speech-models snapshot fields embedded in pricing_raw.

    OpenRouter does not expose a dedicated `/audio/models` endpoint; instead the
    general `/models` catalog carries ``speech``/``audio`` pricing blocks and
    ``architecture.output_modalities`` containing ``speech``. Those fields are
    authoritative for classification. Voice lists are usually top-level
    ``supported_voices`` on the model object (not nested under ``speech``).
    """
    raw = _catalog_raw(pricing_raw)
    speech = raw.get("speech") or raw.get("audio")
    if isinstance(speech, dict):
        return speech
    return {}


def _coerce_str_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out = [str(x).strip() for x in value if str(x).strip()]
    return out or None


def _coerce_float_pair(value: Any) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            lo, hi = float(value[0]), float(value[1])
            if lo <= hi:
                return (lo, hi)
        except (TypeError, ValueError):
            return None
    return None


def speech_generation_capabilities(
    *,
    external_id: str,
    is_speech_model: bool = False,
    pricing_raw: str | None = None,
) -> dict[str, Any]:
    """Detect text-to-speech support and supported voices/formats/speeds.

    Source of truth: provider catalog metadata (``architecture.output_modalities``
    containing ``speech``), top-level ``supported_voices``, and optional nested
    ``speech``/``audio`` blocks for formats/speeds/max length.
    ID-based heuristics are a last-resort fallback.
    """
    ext = (external_id or "").lower()
    raw = _catalog_raw(pricing_raw)
    arch = _architecture_from_raw(pricing_raw)
    _, outputs = _modalities(arch)
    has_metadata = bool(outputs)
    speech_meta = _speech_catalog_meta(pricing_raw)

    supports_tts = False
    if has_metadata:
        supports_tts = "speech" in outputs
    else:
        supports_tts = is_speech_model or any(x in ext for x in ("tts", "/speech", "text-to-speech"))

    # OpenRouter stores voices on the model root as ``supported_voices``.
    voices = (
        _coerce_str_list(speech_meta.get("voices"))
        or _coerce_str_list(speech_meta.get("supported_voices"))
        or _coerce_str_list(raw.get("supported_voices"))
    )
    # Product UI only exposes mp3; keep catalog formats if present, else mp3.
    formats = _coerce_str_list(speech_meta.get("formats")) or (["mp3"] if supports_tts else None)
    if formats:
        formats = [f for f in formats if f == "mp3"] or ["mp3"]
    speeds = _coerce_float_pair(speech_meta.get("speeds")) or ((0.5, 4.0) if supports_tts else None)
    sample_rates = _coerce_str_list(speech_meta.get("sample_rates"))
    max_text = speech_meta.get("max_text_length")
    if not isinstance(max_text, int) or max_text <= 0:
        ctx = raw.get("context_length")
        max_text = ctx if isinstance(ctx, int) and ctx > 0 else 5000 if supports_tts else None

    return {
        "supports_text_to_speech": supports_tts,
        "supported_voices": voices,
        "supported_formats": formats,
        "supported_speeds": list(speeds) if speeds else None,
        "supported_sample_rates": [int(r) for r in sample_rates] if sample_rates else None,
        "supports_ssml": bool(speech_meta.get("supports_ssml")),
        "supports_voice_clone": bool(speech_meta.get("supports_voice_clone")),
        "max_text_length": max_text,
    }


def model_media_flags(
    *,
    external_id: str,
    is_image_model: bool = False,
    is_video_model: bool = False,
    pricing_raw: str | None = None,
    provider_type: str | None = None,
) -> dict[str, bool]:
    """Single source of truth for image/video/speech classification.

    Both ``/api/chat/models`` and ``/api/admin/models`` call this helper so
    the two endpoints can never diverge. Speech is derived from
    ``output_modalities`` (authoritative) rather than a dedicated endpoint.
    """
    auth_video = authoritative_video_model(
        provider_type=provider_type,
        is_video_model=is_video_model,
        pricing_raw=pricing_raw,
    )
    auth_image = authoritative_image_model(
        provider_type=provider_type,
        is_image_model=is_image_model,
        pricing_raw=pricing_raw,
    )
    arch = _architecture_from_raw(pricing_raw)
    _, outputs = _modalities(arch)
    is_speech = (
        "speech" in outputs
        if outputs
        else any(x in (external_id or "").lower() for x in ("tts", "/speech", "text-to-speech"))
    )
    return {
        "is_image_model": auth_image,
        "is_video_model": auth_video,
        "is_speech_model": is_speech,
    }


def supports_vision(
    *,
    external_id: str,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
    provider_type: str | None = None,
) -> bool:
    """True when a chat model can accept an image attachment (vision input).

    The provider's ``architecture.input_modalities`` is the answer whenever it
    exists. It used to be reached only after a name check that returned False
    for any id containing "image", "flux", "dall" and the rest, so a chat model
    the provider declared as accepting images was denied vision because of what
    it was called. A guess must never overrule an answer.

    An image *generation* model is still excluded, because it reaches images
    through the separate image-to-image path rather than as a chat attachment --
    but that exclusion now asks the authoritative catalog, not the id.
    """
    ext = (external_id or "").lower()

    if authoritative_image_model(
        provider_type=provider_type,
        is_image_model=is_image_model,
        pricing_raw=pricing_raw,
    ):
        return False

    arch = _architecture_from_raw(pricing_raw)
    inputs, _ = _modalities(arch)
    if inputs:
        return "image" in inputs

    # Nothing from the provider: fall back to the id, exclusion included.
    if _image_id_heuristic(ext, is_image_model):
        return False
    if ext in ("auto", "openrouter/auto") or ext.endswith("/auto"):
        return True
    return any(hint in ext for hint in _VISION_HEURISTIC_HINTS)
