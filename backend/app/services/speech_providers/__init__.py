"""Provider-neutral speech (text-to-speech) generation adapters."""

from app.services.speech_providers.contracts import (
    NormalizedSpeechRequest,
    SpeechGenerationResult,
    SpeechProviderAdapter,
    SpeechProviderError,
)
from app.services.speech_providers.registry import (
    get_speech_adapter,
    register_speech_adapter,
    registered_speech_adapters,
)

__all__ = [
    "NormalizedSpeechRequest",
    "SpeechGenerationResult",
    "SpeechProviderAdapter",
    "SpeechProviderError",
    "get_speech_adapter",
    "register_speech_adapter",
    "registered_speech_adapters",
]
