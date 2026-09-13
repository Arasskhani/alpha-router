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


def litellm_transcription_model(model_id: str, provider_type: str | None) -> str:
    """Map a catalog external_id to the LiteLLM model string for transcription.

    Deliberately NOT ``litellm_model_for_provider``: LiteLLM routes
    ``/audio/transcriptions`` by different rules than chat.

    Inside ``atranscription`` it re-derives the provider from the *model string*
    and ignores any ``custom_llm_provider`` that was passed, and it ships no
    transcription adapter for most chat providers. So ``openrouter/<id>`` fails
    with "Unmapped provider passed in", and a bare vendor-namespaced id such as
    ``microsoft/mai-transcribe-2`` fails with "LLM Provider NOT provided"
    because ``microsoft`` is read as the provider.

    Every OpenAI-compatible endpoint must therefore be addressed as
    ``openai/<id>`` alongside ``api_base`` — which is exactly what the original
    hardcoded ``"openai/whisper-1"`` was doing before this was generalized to
    the catalog.
    """
    model = normalize_model_id(model_id)
    if not model:
        return model
    provider = (provider_type or "").strip().lower()
    # A LiteLLM chat-routing prefix is not valid here; drop it before mapping.
    model = model.removeprefix("openrouter/") or model
    if provider == "azure":
        return model if model.startswith("azure/") else f"azure/{model}"
    if model.startswith(("openai/", "azure/")):
        return model
    if provider == "openai" and "/" not in model:
        # Native OpenAI ids ("whisper-1", "gpt-4o-transcribe") route as they are.
        return model
    return f"openai/{model}"


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
