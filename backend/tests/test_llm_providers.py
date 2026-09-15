"""Tests for shared LiteLLM provider routing."""

from app.services.llm_providers import (
    external_id_lookup_candidates,
    litellm_model_for_provider,
    normalize_model_id,
    resolve_litellm_provider,
)


def test_resolve_litellm_provider_includes_custom():
    assert resolve_litellm_provider("custom") == "openai"
    assert resolve_litellm_provider("openai") == "openai"
    assert resolve_litellm_provider("unknown") is None


def test_litellm_model_for_provider_openrouter_prefix():
    assert litellm_model_for_provider("google/gemini-2.5-flash", "openrouter") == ("openrouter/google/gemini-2.5-flash")
    assert litellm_model_for_provider("gpt-4o", "openai") == "gpt-4o"
    assert litellm_model_for_provider("my-model", "custom") == "my-model"


def test_openrouter_alias_tilde_is_preserved_for_upstream():
    """OpenRouter alias IDs keep '~'; stripping them makes the model ID invalid."""
    assert normalize_model_id("~deepseek/deepseek-v4-flash-latest") == ("~deepseek/deepseek-v4-flash-latest")
    assert litellm_model_for_provider("~deepseek/deepseek-v4-flash-latest", "openrouter") == (
        "openrouter/~deepseek/deepseek-v4-flash-latest"
    )
    assert (
        litellm_model_for_provider(
            "openrouter/~deepseek/deepseek-v4-flash-latest",
            "openrouter",
        )
        == "openrouter/~deepseek/deepseek-v4-flash-latest"
    )


def test_external_id_lookup_candidates_cover_alias_spellings():
    assert external_id_lookup_candidates("~deepseek/deepseek-v4-flash-latest") == [
        "~deepseek/deepseek-v4-flash-latest",
        "deepseek/deepseek-v4-flash-latest",
    ]
    assert external_id_lookup_candidates("deepseek/deepseek-v4-flash-latest") == [
        "deepseek/deepseek-v4-flash-latest",
        "~deepseek/deepseek-v4-flash-latest",
    ]
    assert external_id_lookup_candidates("openrouter/~deepseek/deepseek-v4-flash-latest") == [
        "openrouter/~deepseek/deepseek-v4-flash-latest",
        "~deepseek/deepseek-v4-flash-latest",
        "deepseek/deepseek-v4-flash-latest",
    ]
