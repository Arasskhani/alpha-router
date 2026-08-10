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


def normalize_model_id(model_id: str | None) -> str:
    """Trim whitespace only.

    OpenRouter alias IDs begin with ``~`` (for example
    ``~deepseek/deepseek-v4-flash-latest``). That character is part of the
    upstream wire ID and must not be stripped before catalog lookup or provider
    calls.
    """
    return (model_id or "").strip()


def external_id_lookup_candidates(model_id: str | None) -> list[str]:
    """Return catalog lookup variants without inventing a different model.

    Tries the exact ID first, then common OpenRouter prefix / alias spellings so
    a client that omits ``openrouter/`` or ``~`` can still resolve the row.
    """
    raw = normalize_model_id(model_id)
    if not raw:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            candidates.append(value)

    add(raw)
    core = raw
    if core.startswith("openrouter/"):
        core = core.removeprefix("openrouter/")
        add(core)
    if core.startswith("~"):
        add(core[1:])
    else:
        add(f"~{core}")
    return candidates


def litellm_model_for_provider(model_id: str, provider_type: str | None) -> str:
    """Map a catalog external_id to the LiteLLM model string.

    Preserves OpenRouter ``~`` alias prefixes. Only adds the ``openrouter/``
    LiteLLM routing prefix when it is not already present.
    """
    model = normalize_model_id(model_id)
    provider = (provider_type or "").strip().lower()
    if provider == "openrouter" and model and not model.startswith("openrouter/"):
        return f"openrouter/{model}"
    return model
