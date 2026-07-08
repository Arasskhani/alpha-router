"""Shared LiteLLM provider routing for chat, embeddings, and images."""

from __future__ import annotations

LLM_PROVIDER_MAP: dict[str, str] = {
    "openai": "openai",
    "openrouter": "openrouter",
    "anthropic": "anthropic",
    "google": "gemini",
    "gemini": "gemini",
    "azure": "azure",
    "custom": "openai",  # OpenAI-compatible custom base URLs
    "xai": "xai",
}


def resolve_litellm_provider(provider_type: str | None) -> str | None:
    provider = (provider_type or "").strip().lower()
    return LLM_PROVIDER_MAP.get(provider)


def litellm_model_for_provider(model_id: str, provider_type: str | None) -> str:
    model = (model_id or "").strip()
    while model.startswith("~"):
        model = model[1:]
    provider = (provider_type or "").strip().lower()
    if provider == "openrouter" and model and not model.startswith("openrouter/"):
        return f"openrouter/{model}"
    return model
