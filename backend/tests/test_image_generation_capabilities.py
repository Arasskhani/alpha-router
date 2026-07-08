"""Unit tests for text-to-image / image-to-image capability detection and payloads."""

import json

from app.services.model_capabilities import image_generation_capabilities
from app.services.openrouter_image_service import build_fast_openrouter_payload


def test_capabilities_from_openrouter_modalities():
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text", "image"],
            }
        }
    )
    caps = image_generation_capabilities(
        external_id="google/gemini-2.5-flash-image-preview",
        is_image_model=True,
        pricing_raw=raw,
    )
    assert caps["supports_text_to_image"] is True
    assert caps["supports_image_to_image"] is True


def test_capabilities_text_to_image_only():
    raw = json.dumps(
        {
            "architecture": {
                "input_modalities": ["text"],
                "output_modalities": ["image"],
            }
        }
    )
    caps = image_generation_capabilities(
        external_id="black-forest-labs/flux-1.1-pro",
        is_image_model=True,
        pricing_raw=raw,
    )
    assert caps["supports_text_to_image"] is True
    assert caps["supports_image_to_image"] is False


def test_capabilities_heuristic_gemini_without_catalog():
    caps = image_generation_capabilities(
        external_id="google/gemini-2.5-flash-image-preview",
        is_image_model=False,
        pricing_raw=None,
    )
    assert caps["supports_text_to_image"] is True
    assert caps["supports_image_to_image"] is True


def test_build_openrouter_payload_text_to_image():
    payload = build_fast_openrouter_payload(
        model_id="google/gemini-2.5-flash-image-preview",
        prompt="A red cat",
        size="1024x1024",
        modalities=["image", "text"],
        aspect_ratio="1:1",
    )
    assert payload["messages"][0]["content"] == "A red cat"
    assert payload["model"] == "google/gemini-2.5-flash-image-preview"
    assert payload["provider"]["allow_fallbacks"] is True
    assert payload["provider"]["sort"] == "latency"
    assert payload["image_config"]["image_size"] == "1K"


def test_build_openrouter_payload_wide_preview_clamps_to_1k():
    payload = build_fast_openrouter_payload(
        model_id="google/gemini-2.5-flash-image-preview",
        prompt="A panorama",
        size="1792x1024",
        modalities=["image", "text"],
        aspect_ratio="16:9",
    )
    assert payload["image_config"]["aspect_ratio"] == "16:9"
    assert payload["image_config"]["image_size"] == "1K"


def test_build_openrouter_payload_wide_ga_uses_2k_tier():
    payload = build_fast_openrouter_payload(
        model_id="google/gemini-2.5-flash-image",
        prompt="A panorama",
        size="1792x1024",
        modalities=["image", "text"],
        aspect_ratio="16:9",
    )
    assert payload["image_config"]["aspect_ratio"] == "16:9"
    assert payload["image_config"]["image_size"] == "2K"


def test_optimize_openrouter_image_model_chat_skips_nitro():
    from app.services.openrouter_image_service import optimize_openrouter_image_model

    assert optimize_openrouter_image_model("google/gemini-2.5-flash-image-preview", chat_completions=True) == (
        "google/gemini-2.5-flash-image-preview"
    )
    assert optimize_openrouter_image_model("google/gemini-2.5-flash-image-preview") == (
        "google/gemini-2.5-flash-image-preview"
    )
    assert optimize_openrouter_image_model("black-forest-labs/flux-1.1-pro") == "black-forest-labs/flux-1.1-pro:nitro"


def test_build_openrouter_payload_image_to_image():
    ref = "data:image/png;base64,abc123"
    payload = build_fast_openrouter_payload(
        model_id="google/gemini-2.5-flash-image-preview",
        prompt="Make the sky purple",
        size="1024x1024",
        modalities=["image", "text"],
        aspect_ratio="1:1",
        reference_image=ref,
    )
    content = payload["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "Make the sky purple"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == ref


def test_build_openrouter_payload_gpt_image_disables_fallbacks():
    payload = build_fast_openrouter_payload(
        model_id="openai/gpt-5-image",
        prompt="A red cat",
        size="1024x1024",
        modalities=["image"],
        aspect_ratio="1:1",
        allow_fallbacks=False,
    )
    assert payload["modalities"] == ["image"]
    assert payload["provider"]["allow_fallbacks"] is False


def test_openrouter_gpt_image_routing_helpers():
    from app.services.openrouter_image_service import (
        is_openai_gpt_image_model,
        is_openrouter_auto_model,
        openrouter_image_modalities,
        prefer_openrouter_images_generations,
    )

    assert is_openrouter_auto_model("openrouter/auto") is True
    assert openrouter_image_modalities("openrouter/auto") == ["image", "text"]
    assert prefer_openrouter_images_generations("openrouter/auto") is False
    assert is_openai_gpt_image_model("openai/gpt-5-image") is True
    assert openrouter_image_modalities("openai/gpt-5-image") == ["image"]
    assert prefer_openrouter_images_generations("openai/gpt-5-image") is True
    assert openrouter_image_modalities("google/gemini-2.5-flash-image") == ["image", "text"]
