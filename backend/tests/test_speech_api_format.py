"""The speech API reports and stores the format the provider delivered, not the one asked for."""

from __future__ import annotations

import struct
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api import speech
from app.services.speech_providers.contracts import SpeechGenerationResult

# A minimal 16-bit mono WAV: what a model that speaks only raw pcm is delivered as.
SAMPLES = struct.pack("<4h", 0, 100, -100, 0)
WAV = (
    b"RIFF"
    + struct.pack("<I", 36 + len(SAMPLES))
    + b"WAVEfmt "
    + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16)
    + b"data"
    + struct.pack("<I", len(SAMPLES))
    + SAMPLES
)


async def test_the_api_stores_and_reports_the_format_that_was_delivered(monkeypatch):
    """Asked for mp3, answered in WAV: the file, its record, the chat and the reply all say WAV."""
    wav = WAV

    class WavAdapter:
        provider_type = "openrouter"
        adapter_version = "test"

        def supported_formats(self):
            return ("mp3",)

        async def generate(self, *, api_key, base_url, request):
            assert request.response_format == "mp3"
            return SpeechGenerationResult(
                audio_blob=wav, mime="audio/wav", format="wav", duration_seconds=0.25, characters=5
            )

    @asynccontextmanager
    async def log_session():
        yield SimpleNamespace(commit=AsyncMock())

    ai_model = SimpleNamespace(id=7, connection_id=3, pricing_raw=None)
    store = AsyncMock(return_value=SimpleNamespace(id="asset-1"))
    finalize = AsyncMock()
    for name, value in {
        "assert_tool_for_user": AsyncMock(),
        "assert_session_allows_model_generation": AsyncMock(),
        "check_generation_rate_limit": AsyncMock(),
        "_resolve_speech_model": AsyncMock(
            return_value=("google/gemini-3.8-flash-tts", "sk", "https://openrouter.ai/api/v1", "openrouter", ai_model)
        ),
        "reservation_hold_usd": AsyncMock(return_value=0.0),
        "reserve": AsyncMock(return_value=None),
        "get_speech_adapter": lambda provider_type: WavAdapter(),
        "store_media_from_blob": store,
        "finalize_chat_session_speech": finalize,
        "log_speech_usage": AsyncMock(return_value=None),
        "AsyncSessionLocal": log_session,
    }.items():
        monkeypatch.setattr(speech, name, value)

    request = MagicMock()
    request.headers = {}
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = AsyncMock(return_value=False)
    db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    user = SimpleNamespace(id=1, username="u")

    out = await speech.generate_speech(
        request,
        speech.SpeechRequest(model="google/gemini-3.8-flash-tts", text="hello", chat_session_id="s1"),
        user,
        db,
    )

    assert out["format"] == "wav"
    stored = store.await_args.kwargs
    assert stored["mime"] == "audio/wav" and stored["blob"] == wav
    assert stored["file_name_hint"].endswith(".wav")
    assert stored["metadata"]["format"] == "wav"
    assert finalize.await_args.kwargs["params"]["format"] == "wav"
