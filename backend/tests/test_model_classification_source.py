"""The provider's answer wins; a model id is only ever a guess.

Categorisation had several places where a name overruled metadata the provider
had actually published: a chat model that accepts image input was denied vision
because its id contained "image", and `/api/chat/models` withheld the provider
snapshot from its own capability helpers, which sent them to the id fallback and
produced a payload that contradicted itself.
"""

from __future__ import annotations

import json

from app.services.model_capabilities import (
    IMAGE_ID_HINTS,
    image_generation_capabilities,
    image_id_looks_generative,
    model_kinds,
    model_media_flags,
    supports_vision,
)


def _snapshot(**arch) -> str:
    return json.dumps({"architecture": arch})


# A chat model whose id happens to carry a hint word. Providers ship these:
# "*-image-reasoner", "*-flux-*", and anything an OpenRouter author names freely.
_TRAP_ID = "vendor/omni-image-reasoner"


def test_the_id_hint_list_has_exactly_one_home():
    """model_sync kept a second, shorter copy, so the same model could be
    classified one way at sync time and another at read time."""
    from app.services import model_sync

    assert not hasattr(model_sync, "_guess_is_image_model")
    assert image_id_looks_generative(_TRAP_ID) is True
    assert "midjourney" in IMAGE_ID_HINTS


class TestVision:
    def test_a_declared_vision_model_keeps_vision_whatever_it_is_called(self):
        detail = _snapshot(input_modalities=["text", "image"], output_modalities=["text"])
        assert supports_vision(external_id=_TRAP_ID, pricing_raw=detail) is True

    def test_a_declared_text_only_model_does_not_get_vision_from_its_name(self):
        detail = _snapshot(input_modalities=["text"], output_modalities=["text"])
        # "gemini" is in the name-based fallback list; the provider says no.
        assert supports_vision(external_id="google/gemini-2.0-pro", pricing_raw=detail) is False

    def test_an_image_generation_model_is_still_excluded(self):
        detail = json.dumps(
            {
                "image_generation": {"id": "vendor/paint"},
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["image"]},
            }
        )
        assert supports_vision(external_id="vendor/paint", pricing_raw=detail, provider_type="openrouter") is False

    def test_the_name_is_used_only_when_the_provider_said_nothing(self):
        assert supports_vision(external_id="openai/gpt-4o") is True
        assert supports_vision(external_id="vendor/plain-text-model") is False
        # And the id-based exclusion still applies in that case.
        assert supports_vision(external_id=_TRAP_ID) is False


class TestPayloadConsistency:
    """`is_image_model: false` and `supports_text_to_image: true` cannot both be right."""

    def test_withholding_the_snapshot_was_what_broke_it(self):
        detail = _snapshot(input_modalities=["text"], output_modalities=["text"])

        flags = model_media_flags(external_id=_TRAP_ID, pricing_raw=detail, provider_type="openrouter")
        assert flags["is_image_model"] is False

        # What the endpoint does now: the helper gets the snapshot either way.
        with_snapshot = image_generation_capabilities(external_id=_TRAP_ID, pricing_raw=detail)
        assert with_snapshot["supports_text_to_image"] is False

        # What it did before: None meant "no metadata", so the id decided.
        without = image_generation_capabilities(external_id=_TRAP_ID, pricing_raw=None)
        assert without["supports_text_to_image"] is True, "the old behaviour this test exists to prevent"

    def test_the_endpoints_do_not_withhold_it(self):
        import inspect

        from app.api import admin, chat

        for module in (chat, admin):
            source = inspect.getsource(module)
            assert "pricing_raw=m.pricing_raw if media[" not in source, module.__name__


class TestKinds:
    def test_a_named_image_model_the_provider_calls_text_is_text(self):
        detail = _snapshot(input_modalities=["text"], output_modalities=["text"])
        kinds = model_kinds(external_id=_TRAP_ID, pricing_raw=detail, provider_type="openrouter")
        assert kinds == ["text"]

    def test_the_authoritative_catalog_decides_image_and_video(self):
        detail = json.dumps(
            {
                "video_generation": {"id": "vendor/clip"},
                "architecture": {"input_modalities": ["text"], "output_modalities": ["video"]},
            }
        )
        kinds = model_kinds(external_id="vendor/clip", pricing_raw=detail, provider_type="openrouter")
        assert "video" in kinds
        assert "image" not in kinds

    def test_openrouter_general_catalog_alone_does_not_make_a_video_model(self):
        """`/models` advertises video output for models `/videos/models` omits."""
        detail = _snapshot(input_modalities=["text"], output_modalities=["text", "video"])
        flags = model_media_flags(external_id="vendor/pretender", pricing_raw=detail, provider_type="openrouter")
        assert flags["is_video_model"] is False


class TestCodeInterpreterPreFilter:
    def _model(self, **kw):
        from types import SimpleNamespace

        base = {
            "external_id": "vendor/chat",
            "is_image_model": False,
            "is_video_model": False,
            "is_enabled": True,
            "admin_disabled": False,
            "pricing_raw": _snapshot(input_modalities=["text"], output_modalities=["text"]),
            "provider_type": "openrouter",
        }
        base.update(kw)
        return SimpleNamespace(**base)

    def test_a_stale_column_no_longer_excludes_a_text_model(self):
        """Rows synced before the authoritative catalogs existed still carry a
        guess in `is_image_model`; that must not bar them from probing."""
        from app.services.model_tool_compatibility_service import is_code_interpreter_candidate

        assert is_code_interpreter_candidate(self._model(external_id=_TRAP_ID, is_image_model=True)) is True

    def test_a_real_image_model_is_still_excluded(self):
        from app.services.model_tool_compatibility_service import is_code_interpreter_candidate

        detail = json.dumps(
            {
                "image_generation": {"id": "vendor/paint"},
                "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]},
            }
        )
        assert is_code_interpreter_candidate(self._model(external_id="vendor/paint", pricing_raw=detail)) is False

    def test_a_video_model_is_excluded_too(self):
        from app.services.model_tool_compatibility_service import is_code_interpreter_candidate

        detail = json.dumps(
            {
                "video_generation": {"id": "vendor/clip"},
                "architecture": {"input_modalities": ["text"], "output_modalities": ["video"]},
            }
        )
        assert is_code_interpreter_candidate(self._model(external_id="vendor/clip", pricing_raw=detail)) is False

    def test_disabled_models_are_still_skipped(self):
        from app.services.model_tool_compatibility_service import is_code_interpreter_candidate

        assert is_code_interpreter_candidate(self._model(is_enabled=False)) is False
        assert is_code_interpreter_candidate(self._model(admin_disabled=True)) is False
