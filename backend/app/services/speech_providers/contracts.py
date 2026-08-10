"""Provider-neutral contracts for synchronous text-to-speech generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class SpeechProviderError(Exception):
    """Upstream speech provider failure with an HTTP-ish status for API mapping."""

    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = int(status_code or 502)
        self.message = (message or "").strip() or "Speech provider request failed"


@dataclass(frozen=True)
class NormalizedSpeechRequest:
    model_id: str
    text: str
    voice: str | None = None
    response_format: str = "mp3"
    speed: float | None = None
    pitch: float | None = None
    sample_rate: int | None = None
    routing: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SpeechGenerationResult:
    audio_blob: bytes
    mime: str
    format: str
    duration_seconds: float | None = None
    characters: int | None = None
    upstream_request_id: str | None = None
    raw_usage: dict[str, Any] = field(default_factory=dict)


class SpeechProviderAdapter(Protocol):
    """The only upstream contract used by the speech orchestrator."""

    provider_type: str
    adapter_version: str

    async def generate(
        self,
        *,
        api_key: str,
        base_url: str | None,
        request: NormalizedSpeechRequest,
    ) -> SpeechGenerationResult:
        ...

    def supported_formats(self) -> tuple[str, ...]:
        ...
