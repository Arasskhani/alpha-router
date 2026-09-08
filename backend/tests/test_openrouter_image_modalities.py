"""Regression tests for the OpenRouter image `modalities` decision.

Background: OpenRouter answers HTTP 404 "No endpoints found that support the
requested output modalities: image, text" when a chat/completions request asks
for text output from a model that only emits images. Most of OpenRouter's image
catalog is image-only, so deciding this from the model id's substrings broke
every image model whose name happened not to contain one of the hints
(meta/muse-image, microsoft/mai-image-*, bytedance-seed/seedream-*, ...).

The stored catalog snapshot (`AIModel.pricing_raw` ->
`architecture.output_modalities`) is the authoritative source, and for image
models `model_sync` fills it from OpenRouter's dedicated image catalog.
"""

import json

from app.services.model_capabilities import catalog_output_modalities
from app.services.openrouter_image_service import (
    catalog_image_modalities,
    openrouter_image_modalities,
    prefer_openrouter_images_generations,
)


def _raw(output_modalities, input_modalities=("text",), nested=True):
    arch = {
        "input_modalities": list(input_modalities),
        "output_modalities": list(output_modalities),
    }
    return json.dumps({"architecture": arch} if nested else arch)


# --------------------------------------------------------------------------- #
# catalog_output_modalities                                                    #
# --------------------------------------------------------------------------- #


def test_catalog_output_modalities_reads_nested_architecture():
    assert catalog_output_modalities(_raw(["image"])) == ["image"]
    assert catalog_output_modalities(_raw(["image", "TEXT"])) == ["image", "text"]


def test_catalog_output_modalities_reads_flat_architecture():
    assert catalog_output_modalities(_raw(["image"], nested=False)) == ["image"]


def test_catalog_output_modalities_tolerates_missing_or_broken_snapshot():
    assert catalog_output_modalities(None) == []
    assert catalog_output_modalities("") == []
    assert catalog_output_modalities("not json") == []
    assert catalog_output_modalities(json.dumps({"architecture": "nope"})) == []
    assert catalog_output_modalities(json.dumps({"architecture": {"output_modalities": 5}})) == []


def test_catalog_image_modalities_returns_none_when_model_emits_no_image():
    assert catalog_image_modalities(_raw(["text"])) is None
    assert catalog_image_modalities(None) is None


# --------------------------------------------------------------------------- #
# openrouter_image_modalities                                                  #
# --------------------------------------------------------------------------- #


def test_image_only_catalog_model_does_not_request_text():
    """The bug: these ids contain no hint substring, so they asked for text."""
    for model_id in (
        "meta/muse-image",
        "microsoft/mai-image-1",
        "bytedance-seed/seedream-4.0",
    ):
        assert openrouter_image_modalities(model_id, _raw(["image"])) == ["image"]


def test_image_and_text_catalog_model_still_requests_both():
    assert openrouter_image_modalities(
        "google/gemini-2.5-flash-image", _raw(["image", "text"])
    ) == ["image", "text"]


def test_catalog_overrides_the_name_hint_list():
    """A hinted name whose catalog says image+text must not be forced image-only."""
    assert openrouter_image_modalities(
        "sourceful/riverflow-v2.5", _raw(["image", "text"])
    ) == ["image", "text"]
    # ...and the reverse: an un-hinted name whose catalog says image-only.
    assert openrouter_image_modalities("acme/pretty-pictures", _raw(["image"])) == ["image"]


def test_auto_router_ignores_the_catalog():
    """Auto Router resolves to an arbitrary downstream model, so keep both."""
    assert openrouter_image_modalities("openrouter/auto", _raw(["image"])) == ["image", "text"]


def test_name_hints_remain_the_fallback_without_a_snapshot():
    assert openrouter_image_modalities("black-forest-labs/flux-1.1-pro") == ["image"]
    assert openrouter_image_modalities("openai/gpt-5-image") == ["image"]
    assert openrouter_image_modalities("google/gemini-2.5-flash-image") == ["image", "text"]
    # A text-only snapshot carries no image information, so fall back too.
    assert openrouter_image_modalities("google/gemini-2.5-flash-image", _raw(["text"])) == [
        "image",
        "text",
    ]


# --------------------------------------------------------------------------- #
# prefer_openrouter_images_generations (endpoint routing)                      #
# --------------------------------------------------------------------------- #


def test_image_only_models_route_to_the_dedicated_image_api():
    """OpenRouter's new image models reject chat/completions outright."""
    for model_id in (
        "meta/muse-image",
        "microsoft/mai-image-1",
        "bytedance-seed/seedream-4.0",
    ):
        assert prefer_openrouter_images_generations(model_id, _raw(["image"])) is True


def test_image_and_text_models_stay_on_chat_completions():
    """Gemini image works through chat/completions today; do not reroute it."""
    assert (
        prefer_openrouter_images_generations(
            "google/gemini-2.5-flash-image", _raw(["image", "text"])
        )
        is False
    )


def test_endpoint_routing_falls_back_to_name_hints():
    assert prefer_openrouter_images_generations("openai/gpt-5-image") is True
    assert prefer_openrouter_images_generations("black-forest-labs/flux-1.1-pro") is True
    assert prefer_openrouter_images_generations("meta/muse-image") is False
    assert prefer_openrouter_images_generations("openrouter/auto") is False
    # Auto Router resolves late, so the snapshot must not decide for it.
    assert prefer_openrouter_images_generations("openrouter/auto", _raw(["image"])) is False


def test_endpoint_paths_try_the_documented_one_first():
    from app.services.openrouter_image_service import OPENROUTER_IMAGE_ENDPOINT_PATHS

    assert OPENROUTER_IMAGE_ENDPOINT_PATHS[0] == "/images"
    assert "/images/generations" in OPENROUTER_IMAGE_ENDPOINT_PATHS


def test_input_references_payload_shape():
    from app.services.openrouter_image_service import openrouter_input_references

    assert openrouter_input_references(None) == []
    assert openrouter_input_references("   ") == []
    assert openrouter_input_references("https://example.com/a.png") == [
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
    ]
    assert openrouter_input_references("data:image/png;base64,AAA") == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}
    ]


def _payload(path, refs=None):
    from app.services.openrouter_image_service import (
        build_openrouter_image_endpoint_payload,
    )

    return build_openrouter_image_endpoint_payload(
        path=path,
        model="meta/muse-image",
        prompt="A red cat",
        n=1,
        size="1024x1024",
        input_references=refs,
    )


def test_image_api_payload_carries_references_and_no_response_format():
    refs = [{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]
    payload = _payload("/images", refs)
    assert payload == {
        "model": "meta/muse-image",
        "prompt": "A red cat",
        "n": 1,
        "size": "1024x1024",
        "input_references": refs,
    }
    # `response_format` is not a field of the dedicated Image API.
    assert "response_format" not in payload


def test_compat_shim_payload_keeps_response_format():
    assert _payload("/images/generations")["response_format"] == "b64_json"


def test_compat_shim_cannot_serve_an_img2img_request():
    refs = [{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]
    assert _payload("/images/generations", refs) is None


# --------------------------------------------------------------------------- #
# 404 safety net                                                               #
# --------------------------------------------------------------------------- #


def test_output_modality_404_detection():
    import httpx

    from app.api.images import _is_output_modality_404

    real_body = json.dumps(
        {
            "error": {
                "message": (
                    "No endpoints found that support the requested output "
                    "modalities: image, text"
                ),
                "code": 404,
            }
        }
    )
    assert _is_output_modality_404(httpx.Response(404, text=real_body)) is True
    # Any other 404, a success, or no response at all must not trigger a retry.
    assert _is_output_modality_404(httpx.Response(404, text='{"error":{"message":"No endpoints found for meta/nope"}}')) is False
    assert _is_output_modality_404(httpx.Response(200, text=real_body)) is False
    assert _is_output_modality_404(None) is False
