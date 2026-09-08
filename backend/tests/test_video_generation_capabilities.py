"""Unit tests for text-to-video / image-to-video capability detection."""

import json

from app.services.model_capabilities import (
    authoritative_image_model,
    authoritative_video_model,
    model_kinds,
    video_generation_capabilities,
)
from app.services.openrouter_video_service import (
    build_video_generation_payload,
    catalog_video_durations,
    extract_job_ids,
    job_status,
    normalize_video_resolution,
    parse_video_duration,
)


def test_capabilities_from_openrouter_modalities():
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["video"],
            },
            "video_generation": {
                "supported_frame_images": ["first_frame", "last_frame"],
                "supported_durations": [4, 8],
                "supported_resolutions": ["720p", "1080p"],
            },
        }
    )
    caps = video_generation_capabilities(
        external_id="google/veo-3.1",
        is_video_model=True,
        pricing_raw=raw,
    )
    assert caps["supports_text_to_video"] is True
    assert caps["supports_image_to_video"] is True
    assert caps["supported_durations"] == [4, 8]


def test_capabilities_text_to_video_only():
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["video"],
            }
        }
    )
    caps = video_generation_capabilities(
        external_id="example/t2v",
        is_video_model=True,
        pricing_raw=raw,
    )
    assert caps["supports_text_to_video"] is True
    assert caps["supports_image_to_video"] is False


def test_capabilities_require_catalog_metadata_or_explicit_flag():
    caps = video_generation_capabilities(
        external_id="google/veo-3.1-lite",
        is_video_model=False,
        pricing_raw=None,
    )
    assert caps["supports_text_to_video"] is False


def test_openrouter_ignores_stale_general_catalog_video_flag():
    stale_general_snapshot = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["video"],
            }
        }
    )
    assert (
        authoritative_video_model(
            provider_type="openrouter",
            is_video_model=True,
            pricing_raw=stale_general_snapshot,
        )
        is False
    )


def test_openrouter_uses_dedicated_image_catalog():
    stale_general_snapshot = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["image"],
            }
        }
    )
    assert (
        authoritative_image_model(
            provider_type="openrouter",
            is_image_model=True,
            pricing_raw=stale_general_snapshot,
        )
        is False
    )


def test_build_video_payload_has_no_callback_url():
    payload = build_video_generation_payload(
        model_id="google/veo-3.1-lite",
        prompt="A glass greenhouse at sunrise",
        duration=4,
        resolution="720p",
        aspect_ratio="16:9",
        generate_audio=False,
    )
    assert payload["model"] == "google/veo-3.1-lite"
    assert payload["duration"] == 4
    assert payload["resolution"] == "720p"
    assert "callback_url" not in payload


def test_model_kinds_video_only_for_output_modality():
    """A model that accepts video as INPUT must not be classified as Video."""
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text", "image", "video"],
                "output_modalities": ["text"],
            }
        }
    )
    kinds = model_kinds(
        external_id="provider/vision-model",
        pricing_raw=raw,
        provider_type="openrouter",
    )
    assert "video" not in kinds
    assert "text" in kinds


def test_model_kinds_audio_only_for_output_modality():
    """A model that accepts audio as INPUT must not be classified as Audio."""
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text", "audio"],
                "output_modalities": ["text"],
            }
        }
    )
    kinds = model_kinds(
        external_id="provider/whisper-large",
        pricing_raw=raw,
        provider_type="openrouter",
    )
    # whisper is transcription, not audio output
    assert "audio" not in kinds


def test_model_kinds_text_only_for_output_modality():
    """A model with text output should be Text, even if it accepts many input types."""
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text", "image", "audio", "video"],
                "output_modalities": ["text"],
            }
        }
    )
    kinds = model_kinds(
        external_id="provider/multimodal-model",
        pricing_raw=raw,
        provider_type="openrouter",
    )
    assert kinds == ["text"]


def test_model_kinds_video_for_authoritative_openrouter():
    """OpenRouter video models from /videos/models should be Video."""
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["video"],
            },
            "video_generation": {"supported_durations": [5]},
        }
    )
    kinds = model_kinds(
        external_id="bytedance/seedance-2.5",
        pricing_raw=raw,
        provider_type="openrouter",
    )
    assert "video" in kinds


def test_model_kinds_image_for_authoritative_openrouter():
    """OpenRouter image models from /images/models should be Image."""
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["image"],
            },
            "image_generation": {"supported_parameters": {}},
        }
    )
    kinds = model_kinds(
        external_id="qwen/qwen-image-3-pro",
        pricing_raw=raw,
        provider_type="openrouter",
    )
    assert "image" in kinds


def test_user_selected_duration_is_not_capped():
    assert parse_video_duration(30) == 30
    assert parse_video_duration(8) == 8
    assert parse_video_duration(4) == 4
    assert parse_video_duration(None) is None
    assert parse_video_duration(0) is None
    assert catalog_video_durations([4, 8, 30, 8]) == [4, 8, 30]
    payload = build_video_generation_payload(
        model_id="google/veo-3.1-lite",
        prompt="A glass greenhouse at sunrise",
        duration=30,
        resolution="720p",
        aspect_ratio="16:9",
        generate_audio=False,
    )
    assert payload["duration"] == 30
    assert normalize_video_resolution("1080p") == "1080p"
    assert normalize_video_resolution("nope") == "720p"


def test_job_status_and_ids():
    assert job_status({"status": "completed"}) == "completed"
    assert job_status({"status": "processing"}) == "running"
    job_id, poll = extract_job_ids({"id": "abc", "polling_url": "https://openrouter.ai/api/v1/videos/abc"})
    assert job_id == "abc"
    assert poll.endswith("/abc")
