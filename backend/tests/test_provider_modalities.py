"""Each provider states capability in its own words; we have to read them all.

The classifier spoke one dialect — OpenRouter's `architecture.*_modalities` —
so a provider that published the same facts differently was treated as having
said nothing, and the model's kind was guessed from its id. Google publishes
`supportedGenerationMethods`; that is the answer, in Google's words.
"""

from __future__ import annotations

import json

from app.services.model_capabilities import (
    classification_dialect,
    classification_source,
    model_kinds,
)
from app.services.provider_modalities import provider_modalities

# Shapes as the providers actually return them, trimmed to the relevant fields.
OPENROUTER = {
    "id": "openai/gpt-4o",
    "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
}
GOOGLE_CHAT = {
    "id": "gemini-2.5-flash",
    "supportedGenerationMethods": ["generateContent", "streamGenerateContent", "countTokens"],
}
GOOGLE_EMBED = {
    "id": "gemini-embedding-001",
    "supportedGenerationMethods": ["embedContent", "countTokens"],
}
AZURE_CHAT = {
    "id": "gpt-4o",
    "capabilities": {"chat_completion": True, "completion": False, "embeddings": False},
}
AZURE_EMBED = {
    "id": "text-embedding-3-large",
    "capabilities": {"chat_completion": False, "embeddings": True},
}
GATEWAY = {
    "id": "local/llava",
    "modalities": {"input": ["text", "image"], "output": ["text"]},
}
# OpenAI's /v1/models really is this bare. There is nothing here to read.
OPENAI = {"id": "gpt-4o", "object": "model", "created": 1715367049, "owned_by": "system"}


class TestReaders:
    def test_openrouter_modality_lists(self):
        stated = provider_modalities(OPENROUTER)
        assert stated is not None
        assert stated.dialect == "modality_lists"
        assert stated.inputs == ("text", "image")
        assert stated.outputs == ("text",)

    def test_google_generation_methods(self):
        stated = provider_modalities(GOOGLE_CHAT)
        assert stated is not None
        assert stated.dialect == "google_generation_methods"
        assert stated.outputs == ("text",)

    def test_google_embedding_model_is_not_a_chat_model(self):
        stated = provider_modalities(GOOGLE_EMBED)
        assert stated is not None
        assert stated.outputs == ("embeddings",)
        assert "text" not in stated.outputs

    def test_azure_capability_map(self):
        assert provider_modalities(AZURE_CHAT).outputs == ("text",)
        assert provider_modalities(AZURE_EMBED).outputs == ("embeddings",)

    def test_a_false_capability_is_not_a_capability(self):
        assert "embeddings" not in provider_modalities(AZURE_CHAT).outputs

    def test_a_gateway_modalities_object(self):
        stated = provider_modalities(GATEWAY)
        assert stated is not None
        assert stated.dialect == "modalities_object"
        assert stated.inputs == ("text", "image")

    def test_a_bare_catalog_says_nothing(self):
        """The honest answer, and the only case where guessing is allowed."""
        assert provider_modalities(OPENAI) is None
        assert provider_modalities({}) is None
        assert provider_modalities(None) is None

    def test_methods_that_say_nothing_about_modality_are_ignored(self):
        assert provider_modalities({"supportedGenerationMethods": ["countTokens"]}) is None


class TestClassification:
    def test_a_google_embedding_model_is_classified_by_the_provider(self):
        raw = json.dumps(GOOGLE_EMBED)
        assert model_kinds(external_id="gemini-embedding-001", pricing_raw=raw) == ["embeddings"]
        assert classification_source(raw) == "provider"
        assert classification_dialect(raw) == "google_generation_methods"

    def test_the_same_model_used_to_be_guessed_from_its_name(self):
        """Without the snapshot the id is all there is — and it happens to work
        here, which is exactly why the gap went unnoticed for so long."""
        assert model_kinds(external_id="gemini-embedding-001", pricing_raw=None) == ["text", "embeddings"]
        assert classification_source(None) == "inferred"

    def test_a_google_chat_model_is_text_not_embeddings(self):
        raw = json.dumps(GOOGLE_CHAT)
        assert model_kinds(external_id="gemini-2.5-flash", pricing_raw=raw) == ["text"]

    def test_an_azure_embedding_model_is_not_offered_for_chat(self):
        raw = json.dumps(AZURE_EMBED)
        kinds = model_kinds(external_id="text-embedding-3-large", pricing_raw=raw)
        assert kinds == ["embeddings"]
        assert "text" not in kinds

    def test_a_gateway_vision_model_keeps_its_vision(self):
        from app.services.model_capabilities import supports_vision

        raw = json.dumps(GATEWAY)
        assert supports_vision(external_id="local/llava", pricing_raw=raw) is True

    def test_openai_stays_inferred_because_there_is_nothing_to_read(self):
        raw = json.dumps(OPENAI)
        assert classification_source(raw) == "inferred"
        assert classification_dialect(raw) is None
        # Still usable: the id fallback is not removed, only demoted.
        assert "text" in model_kinds(external_id="gpt-4o", pricing_raw=raw)

    def test_openrouter_authoritative_catalogs_still_win(self):
        """The dedicated /images/models and /videos/models snapshots outrank the
        general catalog's modality list, and this change must not disturb that."""
        raw = json.dumps(
            {
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text", "video"]},
            }
        )
        kinds = model_kinds(external_id="vendor/pretender", pricing_raw=raw, provider_type="openrouter")
        assert "video" not in kinds


def test_the_admin_payload_reports_the_source():
    import inspect

    from app.api import admin

    source = inspect.getsource(admin)
    assert '"kinds_source": classification_source(' in source
    assert '"kinds_dialect": classification_dialect(' in source


def test_with_nothing_stored_the_flag_still_stands():
    """The two mistakes are not symmetric.

    An OpenRouter row with no snapshot should not exist — sync always stores
    one — but if it does, ignoring the stored flag would offer an image or
    video model for chat, which fails in front of a user. Trusting it only
    risks hiding a model from a filter.
    """
    from app.services.model_capabilities import model_media_flags

    flags = model_media_flags(
        external_id="black-forest-labs/flux",
        is_image_model=True,
        pricing_raw=None,
        provider_type="openrouter",
    )
    assert flags["is_image_model"] is True

    # But the moment a snapshot exists, it is the answer.
    text_only = json.dumps({"architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}})
    flags = model_media_flags(
        external_id="black-forest-labs/flux",
        is_image_model=True,
        pricing_raw=text_only,
        provider_type="openrouter",
    )
    assert flags["is_image_model"] is False
