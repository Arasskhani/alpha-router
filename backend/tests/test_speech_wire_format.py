"""Speech wire formats: negotiated per model, and always delivered as playable audio.

Gemini TTS through OpenRouter refuses ``mp3`` and answers only in raw ``pcm``
(``Gemini TTS only supports response_format="pcm". Got "mp3".``). Raw PCM has
no header, so it has to become WAV before it is stored or played.
"""

from __future__ import annotations

import struct

import pytest

from app.services.speech_providers import openrouter
from app.services.speech_providers.audio_container import pcm_layout, playable_audio, wav_from_pcm
from app.services.speech_providers.contracts import NormalizedSpeechRequest, SpeechProviderError
from app.services.speech_providers.openrouter import OpenRouterSpeechAdapter, wire_format_order

GEMINI_REFUSAL = 'Gemini TTS only supports response_format="pcm". Got "mp3".'
PCM = struct.pack("<6h", 0, 1000, -1000, 32767, -32768, 5)  # 6 samples, 12 bytes


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", headers: dict[str, str] | None = None, error: str = ""):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._error = error
        self.text = f'{{"error":{{"message":"{error}"}}}}' if error else ""

    def json(self):
        if not self._error:
            raise ValueError("no json")
        return {"error": {"message": self._error}}


class FakeClient:
    """Answers each POST from a function of its ``response_format``, recording what was sent."""

    def __init__(self, answer):
        self.answer = answer
        self.formats: list[str] = []

    async def post(self, url, *, json, headers, timeout):
        self.formats.append(json["response_format"])
        return self.answer(json["response_format"])


def gemini_like(fmt: str) -> FakeResponse:
    if fmt != "pcm":
        return FakeResponse(400, headers={"Content-Type": "application/json"}, error=GEMINI_REFUSAL)
    return FakeResponse(200, PCM, {"Content-Type": "audio/pcm"})


@pytest.fixture(autouse=True)
def _fresh_memory(monkeypatch):
    monkeypatch.setattr(openrouter, "_LEARNED_WIRE_FORMATS", openrouter.OrderedDict())
    monkeypatch.setattr(openrouter, "audio_output_limit", lambda: 10 * 1024 * 1024)


def _install(monkeypatch, answer) -> FakeClient:
    client = FakeClient(answer)
    monkeypatch.setattr(openrouter, "get_openrouter_http_client", lambda: client)
    return client


async def _generate(model_id: str = "vendor/new-tts", response_format: str = "mp3"):
    return await OpenRouterSpeechAdapter().generate(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        request=NormalizedSpeechRequest(model_id=model_id, text="hello", voice="Kore", response_format=response_format),
    )


# --- the container ------------------------------------------------------------------------


def test_wav_from_pcm_writes_a_valid_header_and_keeps_whole_frames():
    wav = wav_from_pcm(PCM + b"\x01", sample_rate=24000, channels=1)  # a stray odd byte
    riff, size, wave, fmt_id, fmt_len, codec, channels, rate, byte_rate, align, bits, data_id, data_len = struct.unpack(
        "<4sI4s4sIHHIIHH4sI", wav[:44]
    )
    assert (riff, wave, fmt_id, data_id) == (b"RIFF", b"WAVE", b"fmt ", b"data")
    assert (fmt_len, codec, channels, rate, bits) == (16, 1, 1, 24000, 16)
    assert (byte_rate, align) == (48000, 2)
    assert data_len == len(PCM) and wav[44:] == PCM
    assert size == 36 + len(PCM) == len(wav) - 8


def test_wav_from_pcm_cuts_to_whole_stereo_frames():
    wav = wav_from_pcm(PCM[:10], sample_rate=16000, channels=2)
    assert struct.unpack("<I", wav[40:44])[0] == 8
    assert struct.unpack("<H", wav[22:24])[0] == 2


def test_pcm_layout_reads_rate_and_channels_or_defaults():
    assert pcm_layout("audio/pcm") == (24000, 1)
    assert pcm_layout("audio/L16; codec=pcm; rate=16000; channels=2") == (16000, 2)
    assert pcm_layout('audio/pcm;sample_rate="44100"') == (44100, 1)
    # Out of range or nonsense falls back instead of writing a broken header.
    assert pcm_layout("audio/pcm;rate=12;channels=99") == (24000, 1)
    assert pcm_layout("audio/pcm;rate=abc") == (24000, 1)


def test_raw_pcm_becomes_wav_with_its_duration():
    audio = playable_audio(PCM, content_type="audio/pcm;rate=24000", requested_format="pcm")
    assert (audio.format, audio.mime) == ("wav", "audio/wav")
    assert audio.blob[:4] == b"RIFF" and audio.blob[44:] == PCM
    assert audio.duration_seconds == 6 / 24000


def test_raw_pcm_labelled_as_octet_stream_is_wrapped_when_pcm_was_asked():
    audio = playable_audio(PCM, content_type="application/octet-stream", requested_format="pcm")
    assert audio.format == "wav"


def test_pcm_label_wins_even_when_mp3_was_asked():
    audio = playable_audio(PCM, content_type="audio/pcm", requested_format="mp3")
    assert audio.format == "wav"


def test_samples_that_look_like_a_frame_header_are_still_samples():
    # 0xFF 0xFB is an MP3 frame sync, and also a plausible pair of sample bytes.
    samples = b"\xff\xfb" + PCM
    assert playable_audio(samples, content_type="audio/pcm", requested_format="pcm").format == "wav"
    assert playable_audio(samples, content_type="", requested_format="pcm").format == "wav"


def test_containers_are_told_by_their_bytes_not_their_label():
    wav = wav_from_pcm(PCM, sample_rate=24000, channels=1)
    assert playable_audio(wav, content_type="audio/mpeg", requested_format="mp3").mime == "audio/wav"
    assert playable_audio(wav, content_type="audio/pcm", requested_format="pcm").blob == wav  # never wrapped twice
    assert playable_audio(b"ID3\x04rest", content_type="audio/pcm", requested_format="pcm").format == "mp3"
    assert playable_audio(b"OggS\x00rest", content_type="", requested_format="mp3").mime == "audio/ogg"
    assert playable_audio(b"fLaC\x00rest", content_type="", requested_format="mp3").mime == "audio/flac"
    assert playable_audio(b"\xff\xfbframe", content_type="", requested_format="mp3").mime == "audio/mpeg"
    assert playable_audio(b"\xff\xf1adts", content_type="", requested_format="mp3").mime == "audio/aac"


def test_an_mp3_that_was_labelled_and_framed_is_kept_when_pcm_was_asked():
    audio = playable_audio(b"\xff\xfbframe", content_type="audio/mpeg", requested_format="pcm")
    assert (audio.format, audio.mime) == ("mp3", "audio/mpeg")


def test_other_labels_and_unlabelled_mp3():
    assert playable_audio(b"\x00\x00ftyp", content_type="audio/mp4", requested_format="mp3").format == "m4a"
    assert playable_audio(b"\x1a\x45\xdf\xa3", content_type="audio/webm", requested_format="mp3").format == "webm"
    assert playable_audio(b"untagged", content_type="", requested_format="mp3").mime == "audio/mpeg"


# --- negotiation --------------------------------------------------------------------------


async def test_gemini_tts_is_asked_for_pcm_first_and_delivered_as_wav(monkeypatch):
    client = _install(monkeypatch, gemini_like)
    result = await _generate("google/gemini-3.8-flash-tts")
    assert client.formats == ["pcm"]  # no refused mp3 request first
    assert (result.format, result.mime) == ("wav", "audio/wav")
    assert result.audio_blob[:4] == b"RIFF" and result.audio_blob[44:] == PCM
    assert result.duration_seconds == 6 / 24000


async def test_a_format_refusal_is_retried_in_the_named_format_and_remembered(monkeypatch):
    client = _install(monkeypatch, gemini_like)
    result = await _generate("vendor/new-tts")
    assert client.formats == ["mp3", "pcm"]
    assert result.format == "wav"
    # The next request for that model goes straight to pcm.
    await _generate("vendor/new-tts")
    assert client.formats == ["mp3", "pcm", "pcm"]
    # Other models keep the preference.
    assert wire_format_order(base_url="https://openrouter.ai/api/v1", model_id="openai/tts-1", preferred="mp3") == [
        "mp3",
        "pcm",
    ]


async def test_a_refusal_that_names_no_format_tries_the_other_one(monkeypatch):
    def answer(fmt):
        if fmt == "mp3":
            return FakeResponse(422, error="Unsupported output format for this model")
        return FakeResponse(200, PCM, {"Content-Type": "audio/pcm"})

    client = _install(monkeypatch, answer)
    assert (await _generate()).format == "wav"
    assert client.formats == ["mp3", "pcm"]


async def test_a_model_that_learned_pcm_and_now_refuses_it_goes_back_to_mp3(monkeypatch):
    openrouter._LEARNED_WIRE_FORMATS[openrouter._model_key("https://openrouter.ai/api/v1", "vendor/new-tts")] = "pcm"

    def answer(fmt):
        if fmt == "pcm":
            return FakeResponse(400, error='Only response_format="mp3" is supported')
        return FakeResponse(200, b"ID3mp3", {"Content-Type": "audio/mpeg"})

    client = _install(monkeypatch, answer)
    assert (await _generate()).format == "mp3"
    assert client.formats == ["pcm", "mp3"]
    assert not openrouter._LEARNED_WIRE_FORMATS  # back on the preference, nothing to remember


async def test_other_errors_are_not_retried(monkeypatch):
    client = _install(monkeypatch, lambda fmt: FakeResponse(400, error="Voice 'x' is not available"))
    with pytest.raises(SpeechProviderError) as exc:
        await _generate()
    assert client.formats == ["mp3"]
    assert exc.value.status_code == 400
    assert "Voice 'x'" in exc.value.message


async def test_auth_and_payment_errors_mentioning_format_are_not_retried(monkeypatch):
    client = _install(monkeypatch, lambda fmt: FakeResponse(402, error="Insufficient credits for format pcm"))
    with pytest.raises(SpeechProviderError) as exc:
        await _generate()
    assert client.formats == ["mp3"] and exc.value.status_code == 402


async def test_every_format_refused_reports_the_last_refusal(monkeypatch):
    client = _install(monkeypatch, lambda fmt: FakeResponse(400, error=f'response_format "{fmt}" is not supported'))
    with pytest.raises(SpeechProviderError) as exc:
        await _generate()
    assert client.formats == ["mp3", "pcm"]
    assert '"pcm"' in exc.value.message
    assert not openrouter._LEARNED_WIRE_FORMATS


async def test_an_answer_with_no_whole_sample_is_empty(monkeypatch):
    _install(monkeypatch, lambda fmt: FakeResponse(200, b"\x01", {"Content-Type": "audio/pcm"}))
    with pytest.raises(SpeechProviderError) as exc:
        await _generate("google/gemini-3.8-flash-tts")
    assert "empty audio" in exc.value.message


async def test_the_wav_is_held_to_the_output_limit(monkeypatch):
    monkeypatch.setattr(openrouter, "audio_output_limit", lambda: len(PCM))
    _install(monkeypatch, gemini_like)
    with pytest.raises(SpeechProviderError) as exc:
        await _generate("google/gemini-3.8-flash-tts")
    assert exc.value.status_code == 413


def test_the_memory_is_bounded():
    for i in range(openrouter._LEARNED_LIMIT + 5):
        openrouter._remember_wire_format(base_url=None, model_id=f"m/{i}", preferred="mp3", used="pcm")
    assert len(openrouter._LEARNED_WIRE_FORMATS) == openrouter._LEARNED_LIMIT
    assert openrouter._model_key(None, "m/0") not in openrouter._LEARNED_WIRE_FORMATS
