"""Provider-neutral video catalog capability normalization."""

from __future__ import annotations

from typing import Any

from app.services.video_providers import get_video_adapter


def normalize_video_capabilities(
    *,
    provider_type: str,
    model_id: str,
    raw: dict[str, Any] | None,
) -> dict[str, Any]:
    """Convert provider metadata into the versioned catalog shape."""
    data = raw if isinstance(raw, dict) else {}
    architecture = data.get("architecture") if isinstance(data.get("architecture"), dict) else {}
    inputs = {str(value).lower() for value in architecture.get("input_modalities", []) if value}
    outputs = {str(value).lower() for value in architecture.get("output_modalities", []) if value}
    metadata = data.get("video_capabilities") or data.get("video_generation") or data
    if not isinstance(metadata, dict):
        metadata = {}
    frame_images = metadata.get("supported_frame_images") or []
    return {
        "schema_version": "video-capabilities.v1",
        "provider_type": provider_type,
        "model_id": model_id,
        "supports_text_to_video": "video" in outputs or bool(metadata.get("supports_text_to_video")),
        "supports_image_to_video": (
            ("image" in inputs and "video" in outputs)
            or bool(metadata.get("supports_image_to_video"))
            or bool(frame_images)
        ),
        "supported_durations": metadata.get("supported_durations") or [],
        "supported_resolutions": metadata.get("supported_resolutions") or [],
        "supported_aspect_ratios": metadata.get("supported_aspect_ratios") or [],
        "supported_frame_images": frame_images,
        "supports_audio": bool(metadata.get("generate_audio") or metadata.get("supports_audio")),
        "pricing_units": metadata.get("pricing_units") or ["clip"],
        "pricing": metadata.get("pricing") or metadata.get("pricing_skus") or {},
        "adapter": getattr(get_video_adapter(provider_type), "adapter_version", "unknown"),
    }

