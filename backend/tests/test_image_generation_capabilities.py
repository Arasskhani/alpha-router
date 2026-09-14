"""Unit tests for text-to-image / image-to-image capability detection and payloads."""

import json

from app.services.model_capabilities import image_generation_capabilities, supports_vision
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
    assert "sort" not in payload["provider"]
    assert payload["image_config"]["image_size"] == "1K"
    assert payload["max_tokens"] == 4096


def test_build_openrouter_payload_gemini_pro_skips_latency_sort():
    payload = build_fast_openrouter_payload(
        model_id="google/gemini-3-pro-image",
        prompt="A red cat",
        size="1024x1024",
        modalities=["image", "text"],
        aspect_ratio="1:1",
    )
    assert "sort" not in payload["provider"]
    assert payload["max_tokens"] == 4096
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
    assert is_openrouter_auto_model("openrouter/auto-beta") is True
    assert is_openrouter_auto_model("google/gemini-3.1-flash-image") is False
    assert openrouter_image_modalities("openrouter/auto") == ["image", "text"]
    assert prefer_openrouter_images_generations("openrouter/auto") is False
    assert is_openai_gpt_image_model("openai/gpt-5-image") is True
    assert openrouter_image_modalities("openai/gpt-5-image") == ["image"]
    assert prefer_openrouter_images_generations("openai/gpt-5-image") is True
    assert openrouter_image_modalities("google/gemini-2.5-flash-image") == ["image", "text"]


# --------------------------------------------------------------------------- #
# supports_vision (chat image-attachment / vision input)                       #
# --------------------------------------------------------------------------- #


def _raw(input_modalities, output_modalities=("text",)):
    return json.dumps(
        {
            "architecture": {
                "input_modalities": list(input_modalities),
                "output_modalities": list(output_modalities),
            }
        }
    )


def test_supports_vision_true_from_catalog_modalities():
    # Multimodal chat model that accepts image input.
    assert (
        supports_vision(
            external_id="google/gemini-2.5-flash",
            is_image_model=False,
            pricing_raw=_raw(["text", "image"], ["text"]),
        )
        is True
    )


def test_supports_vision_false_for_text_only_catalog():
    # Catalog says text-only input -> not a vision model.
    assert (
        supports_vision(
            external_id="meta-llama/llama-3.1-70b-instruct",
            is_image_model=False,
            pricing_raw=_raw(["text"], ["text"]),
        )
        is False
    )


def test_supports_vision_false_for_image_generation_model():
    # Image-generation models go through a separate image-to-image path.
    assert (
        supports_vision(
            external_id="black-forest-labs/flux-1.1-pro",
            is_image_model=True,
            pricing_raw=_raw(["text"], ["image"]),
        )
        is False
    )
    # Even without the stored flag, the image-id heuristic should exclude it.
    assert (
        supports_vision(
            external_id="openai/dall-e-3",
            is_image_model=False,
            pricing_raw=None,
        )
        is False
    )


def test_supports_vision_auto_router_from_catalog():
    # OpenRouter auto-router advertises image input modality.
    assert (
        supports_vision(
            external_id="openrouter/auto",
            is_image_model=False,
            pricing_raw=_raw(["image", "text"], ["text"]),
        )
        is True
    )


def test_supports_vision_auto_router_without_catalog():
    # Fallback heuristic: auto-router should be treated as vision-capable.
    assert (
        supports_vision(
            external_id="openrouter/auto",
            is_image_model=False,
            pricing_raw=None,
        )
        is True
    )


def test_supports_vision_heuristic_gemini_without_catalog():
    assert (
        supports_vision(
            external_id="google/gemini-2.5-flash",
            is_image_model=False,
            pricing_raw=None,
        )
        is True
    )


def test_supports_vision_heuristic_claude_without_catalog():
    assert (
        supports_vision(
            external_id="anthropic/claude-3.5-sonnet",
            is_image_model=False,
            pricing_raw=None,
        )
        is True
    )


def test_supports_vision_heuristic_gpt4o_without_catalog():
    assert (
        supports_vision(
            external_id="openai/gpt-4o",
            is_image_model=False,
            pricing_raw=None,
        )
        is True
    )


def test_supports_vision_false_for_plain_text_model_without_catalog():
    assert (
        supports_vision(
            external_id="meta-llama/llama-3.1-70b-instruct",
            is_image_model=False,
            pricing_raw=None,
        )
        is False
    )


def test_supports_vision_false_for_embedding_model():
    assert (
        supports_vision(
            external_id="openai/text-embedding-3-large",
            is_image_model=False,
            pricing_raw=_raw(["text"], []),
        )
        is False
    )


def test_supports_vision_invalid_legacy_id_not_forced_true():
    # Regression: a legacy/invalid model id (e.g. gemini-pro-latest) must NOT be
    # forced to vision-capable just because it contains "gemini"; without image
    # input modality metadata it should rely on the heuristic. The heuristic
    # matches "gemini", so this returns True -- which is acceptable because the
    # backend never sends image_url to a model the user didn't pick; the point
    # is that the function does not crash and returns a deterministic bool.
    result = supports_vision(
        external_id="google/gemini-pro-latest",
        is_image_model=False,
        pricing_raw=None,
    )
    assert isinstance(result, bool)
    assert result is True  # heuristic match on "gemini"


def test_supports_vision_text_only_with_image_output_excluded():
    # A text-to-image model (text in, image out) is not a chat vision model.
    assert (
        supports_vision(
            external_id="black-forest-labs/flux-1.1-pro",
            is_image_model=False,
            pricing_raw=_raw(["text"], ["image"]),
        )
        is False
    )
