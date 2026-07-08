"""Tests for shared LiteLLM provider routing."""

from app.services.llm_providers import litellm_model_for_provider, resolve_litellm_provider


def test_resolve_litellm_provider_includes_custom():
    assert resolve_litellm_provider("custom") == "openai"
    assert resolve_litellm_provider("openai") == "openai"
    assert resolve_litellm_provider("unknown") is None


def test_litellm_model_for_provider_openrouter_prefix():
    assert litellm_model_for_provider("google/gemini-2.5-flash", "openrouter") == (
        "openrouter/google/gemini-2.5-flash"
    )
    assert litellm_model_for_provider("gpt-4o", "openai") == "gpt-4o"
    assert litellm_model_for_provider("my-model", "custom") == "my-model"
