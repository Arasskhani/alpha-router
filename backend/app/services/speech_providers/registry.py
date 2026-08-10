"""Provider adapter registry for text-to-speech generation."""

from __future__ import annotations

from collections.abc import Mapping

from app.services.speech_providers.contracts import SpeechProviderAdapter
from app.services.speech_providers.openrouter import OpenRouterSpeechAdapter

_ADAPTERS: dict[str, SpeechProviderAdapter] = {
    "openrouter": OpenRouterSpeechAdapter(),
}


def register_speech_adapter(adapter: SpeechProviderAdapter) -> None:
    key = (adapter.provider_type or "").strip().lower()
    if not key:
        raise ValueError("Speech adapter provider_type is required")
    _ADAPTERS[key] = adapter


def get_speech_adapter(provider_type: str, *, adapter_key: str | None = None) -> SpeechProviderAdapter:
    key = (adapter_key or provider_type or "").strip().lower()
    try:
        return _ADAPTERS[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_ADAPTERS))
        raise ValueError(f"Unsupported speech provider '{key}'. Registered providers: {supported}") from exc


def registered_speech_adapters() -> Mapping[str, SpeechProviderAdapter]:
    return dict(_ADAPTERS)
