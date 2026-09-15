"""Tests for text-to-speech capabilities, markers, and adapters."""

from __future__ import annotations

import json

from app.services.attachment_policy import (
    is_inline_audio_media,
    media_response_type_and_disposition,
)
from app.services.chat_markers import SPEECH_MESSAGE_PREFIX, SPEECH_PENDING_MARKER
from app.services.model_capabilities import (
    model_kinds,
    model_media_flags,
    speech_generation_capabilities,
)
from app.services.speech_providers import get_speech_adapter
from app.services.speech_providers.contracts import NormalizedSpeechRequest, SpeechProviderError
from app.services.speech_providers.openrouter import (
    OpenRouterSpeechAdapter,
    normalize_openrouter_base,
)
from app.services.user_chat_storage_service import _build_speech_message


def test_speech_capabilities_from_output_modalities():
    raw = json.dumps(
        {
            "architecture": {"output_modalities": ["speech"]},
            "speech": {
                "voices": ["alloy", "nova"],
                "formats": ["mp3", "wav"],
                "speeds": [0.5, 4.0],
                "max_text_length": 4000,
            },
        }
    )
    caps = speech_generation_capabilities(external_id="openai/tts-1", pricing_raw=raw)
    assert caps["supports_text_to_speech"] is True
    assert caps["supported_voices"] == ["alloy", "nova"]
    assert caps["supported_formats"] == ["mp3"]
    assert caps["max_text_length"] == 4000


def test_speech_capabilities_reads_top_level_supported_voices():
    raw = json.dumps(
        {
            "architecture": {"output_modalities": ["speech"]},
            "supported_voices": ["eve", "ara", "rex", "sal", "leo"],
            "context_length": 15000,
        }
    )
    caps = speech_generation_capabilities(
        external_id="x-ai/grok-voice-tts-1.0",
        pricing_raw=raw,
    )
    assert caps["supports_text_to_speech"] is True
    assert caps["supported_voices"] == ["eve", "ara", "rex", "sal", "leo"]
    assert caps["supported_formats"] == ["mp3"]
    assert caps["max_text_length"] == 15000


def test_model_media_flags_includes_speech():
    raw = json.dumps({"architecture": {"output_modalities": ["speech"]}})
    flags = model_media_flags(
        external_id="openai/tts-1",
        pricing_raw=raw,
        provider_type="openrouter",
    )
    assert flags["is_speech_model"] is True
    assert flags["is_image_model"] is False
    assert flags["is_video_model"] is False


def test_model_kinds_includes_speech_from_output_modalities():
    raw = json.dumps({"architecture": {"output_modalities": ["speech"]}})
    kinds = model_kinds(
        external_id="openai/tts-1",
        pricing_raw=raw,
        provider_type="openrouter",
    )
    assert "speech" in kinds


def test_inline_audio_media_and_disposition():
    assert is_inline_audio_media(kind="audio", mime="audio/mpeg") is True
    assert is_inline_audio_media(kind="image", mime="audio/mpeg") is False
    mime, disposition = media_response_type_and_disposition(
        file_name="speech.mp3",
        kind="audio",
        stored_mime="audio/mpeg",
    )
    assert mime == "audio/mpeg"
    assert disposition.startswith("inline;")


def test_speech_message_markers():
    content = _build_speech_message(
        "/api/chat/media/1/file",
        "hello",
        "openai/tts-1",
        params={"voice": "alloy", "format": "mp3"},
    )
    assert content.startswith(SPEECH_MESSAGE_PREFIX)
    assert SPEECH_PENDING_MARKER.startswith("__ALPHA_ROUTER_SPEECH_")
    payload = json.loads(content[len(SPEECH_MESSAGE_PREFIX) :])
    assert payload["url"] == "/api/chat/media/1/file"
    assert payload["voice"] == "alloy"


def test_speech_adapter_registry():
    adapter = get_speech_adapter("openrouter")
    assert isinstance(adapter, OpenRouterSpeechAdapter)
    assert "mp3" in adapter.supported_formats()


async def test_openrouter_speech_adapter_rejects_empty_response(monkeypatch):
    adapter = OpenRouterSpeechAdapter()

    class FakeResponse:
        status_code = 200
        content = b""
        text = ""
        headers = {}

    class FakeClient:
        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.speech_providers.openrouter.get_openrouter_http_client",
        lambda: FakeClient(),
    )
    try:
        await adapter.generate(
            api_key="sk-test",
            base_url="https://openrouter.ai/api/v1",
            request=NormalizedSpeechRequest(
                model_id="openai/tts-1",
                text="hello",
                voice="alloy",
                response_format="mp3",
            ),
        )
    except SpeechProviderError as exc:
        assert "empty audio" in str(exc)
        assert exc.status_code == 502
        return
    raise AssertionError("expected SpeechProviderError for empty audio")


def test_normalize_openrouter_base_forces_api_root():
    assert normalize_openrouter_base("https://openrouter.ai") == "https://openrouter.ai/api/v1"
    assert normalize_openrouter_base("https://openrouter.ai/api/v1/") == "https://openrouter.ai/api/v1"


async def test_openrouter_speech_adapter_maps_provider_400(monkeypatch):
    adapter = OpenRouterSpeechAdapter()

    class FakeResponse:
        status_code = 400
        content = b'{"error":{"message":"Provider returned 400"}}'
        text = '{"error":{"message":"Provider returned 400"}}'
        headers = {"Content-Type": "application/json"}

        def json(self):
            return {"error": {"message": "Provider returned 400"}}

    class FakeClient:
        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.speech_providers.openrouter.get_openrouter_http_client",
        lambda: FakeClient(),
    )
    try:
        await adapter.generate(
            api_key="sk-test",
            base_url="https://openrouter.ai",
            request=NormalizedSpeechRequest(
                model_id="openai/tts-1",
                text="hello",
                voice="alloy",
                response_format="wav",
            ),
        )
    except SpeechProviderError as exc:
        assert exc.status_code == 400
        assert "Provider returned 400" in exc.message
        return
    raise AssertionError("expected SpeechProviderError for upstream 400")


async def test_openrouter_speech_adapter_success(monkeypatch):
    adapter = OpenRouterSpeechAdapter()
    audio = b"ID3fake-mp3-bytes"

    class FakeResponse:
        status_code = 200
        content = audio
        text = ""
        headers = {"Content-Type": "audio/mpeg", "x-request-id": "req-1"}

    class FakeClient:
        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.speech_providers.openrouter.get_openrouter_http_client",
        lambda: FakeClient(),
    )
    monkeypatch.setattr(
        "app.services.speech_providers.openrouter.audio_output_limit",
        lambda: 10 * 1024 * 1024,
    )

    async def run():
        return await adapter.generate(
            api_key="sk-test",
            base_url="https://openrouter.ai/api/v1",
            request=NormalizedSpeechRequest(
                model_id="openai/tts-1",
                text="hello world",
                voice="alloy",
                response_format="mp3",
            ),
        )

    result = await run()
    assert result.audio_blob == audio
    assert result.mime == "audio/mpeg"
    assert result.characters == len("hello world")
    assert result.upstream_request_id == "req-1"
