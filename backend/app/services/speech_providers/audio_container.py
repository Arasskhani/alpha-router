"""Turn whatever a speech provider sends into audio a browser can play.

Speech providers answer in more than one shape. Most send a container (MP3,
WAV, Ogg, FLAC) whose bytes say what it is. Some send raw PCM samples with no
header at all: Gemini TTS through OpenRouter answers only in ``pcm``. Raw PCM
cannot be played by ``<audio>``, has no safe inline MIME type, and would be
stored and served under a wrong label. So every answer goes through
:func:`playable_audio`, which:

* trusts the bytes before the headers: a container with a magic word (RIFF,
  ID3, OggS, fLaC) is what it says, whatever ``Content-Type`` claims;
* wraps raw PCM in a WAV header, with the sample rate and channel count the
  ``Content-Type`` names (``audio/pcm;rate=24000;channels=1``) or the
  providers' common default of 24 kHz mono;
* keeps 16-bit samples: every provider that sends raw PCM for speech sends
  16-bit little-endian samples, ``audio/L16`` included in practice.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# Raw PCM from speech providers (Gemini, OpenAI's ``pcm``) is 24 kHz mono 16-bit.
DEFAULT_PCM_SAMPLE_RATE = 24_000
DEFAULT_PCM_CHANNELS = 1
PCM_SAMPLE_WIDTH_BYTES = 2
_WAV_HEADER_BYTES = 44
_MIN_SAMPLE_RATE = 8_000
_MAX_SAMPLE_RATE = 192_000
_MAX_CHANNELS = 8

# Content types that mean "samples with no container".
_RAW_PCM_TYPES = frozenset({"audio/pcm", "audio/l16", "audio/raw", "audio/x-raw", "audio/basic-pcm"})


# Formats (file extensions) for labels whose subtype is not the usual extension.
_FORMAT_BY_LABEL = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/x-flac": "flac",
}


@dataclass(frozen=True)
class PlayableAudio:
    blob: bytes
    mime: str
    format: str
    # Known exactly only when the samples were counted (raw PCM wrapped here).
    duration_seconds: float | None = None


def _content_type_parts(content_type: str | None) -> tuple[str, dict[str, str]]:
    parts = [p.strip() for p in (content_type or "").split(";")]
    media = (parts[0] if parts else "").lower()
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if sep:
            params[key.strip().lower()] = value.strip().strip('"').lower()
    return media, params


def _int_param(params: dict[str, str], names: tuple[str, ...], *, low: int, high: int, default: int) -> int:
    for name in names:
        raw = params.get(name)
        if raw is None:
            continue
        try:
            value = int(float(raw))
        except ValueError:
            continue
        if low <= value <= high:
            return value
    return default


def pcm_layout(content_type: str | None) -> tuple[int, int]:
    """Sample rate and channel count a raw PCM answer declares, else the default."""
    _, params = _content_type_parts(content_type)
    rate = _int_param(
        params,
        ("rate", "sample_rate", "samplerate", "sample-rate"),
        low=_MIN_SAMPLE_RATE,
        high=_MAX_SAMPLE_RATE,
        default=DEFAULT_PCM_SAMPLE_RATE,
    )
    channels = _int_param(params, ("channels",), low=1, high=_MAX_CHANNELS, default=DEFAULT_PCM_CHANNELS)
    return rate, channels


def _signature(blob: bytes) -> tuple[str, str] | None:
    """A container told by a magic word no raw samples plausibly start with."""
    head = blob[:12]
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav", "audio/wav"
    if head[:3] == b"ID3":
        return "mp3", "audio/mpeg"
    if head[:4] == b"OggS":
        return "ogg", "audio/ogg"
    if head[:4] == b"fLaC":
        return "flac", "audio/flac"
    return None


def _frame_sync(blob: bytes) -> tuple[str, str] | None:
    """An MPEG or ADTS frame header: 11 set bits, which raw samples can also start with."""
    if len(blob) < 2 or blob[0] != 0xFF or (blob[1] & 0xE0) != 0xE0:
        return None
    # The layer bits tell MP3 (layer set) from AAC ADTS (layer 0, 0xFFF1 / 0xFFF9).
    return ("mp3", "audio/mpeg") if blob[1] & 0x06 else ("aac", "audio/aac")


def wav_from_pcm(samples: bytes, *, sample_rate: int, channels: int) -> bytes:
    """A RIFF/WAVE file holding 16-bit little-endian ``samples``, cut to whole frames."""
    frame = PCM_SAMPLE_WIDTH_BYTES * channels
    data = samples[: len(samples) - (len(samples) % frame)]
    byte_rate = sample_rate * frame
    header = b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + len(data)),
            b"WAVE",
            b"fmt ",
            struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, frame, PCM_SAMPLE_WIDTH_BYTES * 8),
            b"data",
            struct.pack("<I", len(data)),
        )
    )
    return header + data


def playable_audio(blob: bytes, *, content_type: str | None, requested_format: str) -> PlayableAudio:
    """What to store and serve for a provider's answer (see the module docstring).

    ``requested_format`` is the wire format asked of the provider; it decides only
    answers that neither their bytes nor their content type describe.
    """
    signed = _signature(blob)
    if signed:
        return PlayableAudio(blob=blob, mime=signed[1], format=signed[0])
    media, _ = _content_type_parts(content_type)
    synced = _frame_sync(blob)
    labelled_raw = media in _RAW_PCM_TYPES
    if labelled_raw or requested_format == "pcm":
        # Asked for samples: only a matching label and a frame header say it is not.
        if not labelled_raw and synced and media == synced[1]:
            return PlayableAudio(blob=blob, mime=synced[1], format=synced[0])
        rate, channels = pcm_layout(content_type)
        wav = wav_from_pcm(blob, sample_rate=rate, channels=channels)
        frames = (len(wav) - _WAV_HEADER_BYTES) // (PCM_SAMPLE_WIDTH_BYTES * channels)
        return PlayableAudio(blob=wav, mime="audio/wav", format="wav", duration_seconds=frames / rate)
    if synced:
        return PlayableAudio(blob=blob, mime=synced[1], format=synced[0])
    if media.startswith("audio/"):
        # A container we do not sniff (m4a, webm...): its own label is the best we have.
        subtype = media.split("/", 1)[1]
        fmt = _FORMAT_BY_LABEL.get(media) or "".join(ch for ch in subtype if ch.isalnum())[:8] or "audio"
        return PlayableAudio(blob=blob, mime=media, format=fmt)
    # Unlabelled bytes for an mp3 request: some MP3 encoders start without a tag.
    return PlayableAudio(blob=blob, mime="audio/mpeg", format="mp3")
