"""Speech-to-text for voice messages via LiteLLM (Whisper-compatible providers)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from litellm import atranscription
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.services.secret_crypto import decrypt_secret

_MAX_BYTES = 25 * 1024 * 1024

_EXT_BY_MIME = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
}


def _suffix_for_file(filename: str, mime_type: str) -> str:
    name = (filename or "").lower()
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1]
        if ext != ".":
            return ext
    mime = (mime_type or "").split(";")[0].strip().lower()
    return _EXT_BY_MIME.get(mime, ".webm")


async def _resolve_transcription_provider(
    db: AsyncSession,
) -> tuple[str, str | None, str | None]:
    """Return (provider_type, api_key, base_url) for the first usable STT connection."""
    preferred = ("openai", "azure", "openrouter")
    rows = (
        await db.execute(
            select(Connection).where(Connection.is_active == True).order_by(Connection.id)  # noqa: E712
        )
    ).scalars().all()
    by_type: dict[str, Connection] = {}
    for conn in rows:
        p = (conn.provider_type or "").lower()
        if p and p not in by_type and conn.api_key_encrypted:
            by_type[p] = conn
    for p in preferred:
        conn = by_type.get(p)
        if conn:
            return p, decrypt_secret(conn.api_key_encrypted), conn.base_url
    if rows and rows[0].api_key_encrypted:
        c = rows[0]
        return (c.provider_type or "openai").lower(), decrypt_secret(c.api_key_encrypted), c.base_url
    raise ValueError("No active connection with an API key is available for speech-to-text.")


def _normalize_openrouter_base(base_url: str | None) -> str:
    base = (base_url or "https://openrouter.ai/api/v1").strip().rstrip("/")
    if "openrouter.ai" in base.lower() and "/api/" not in base.lower():
        return "https://openrouter.ai/api/v1"
    return base


def _transcription_model(provider_type: str) -> str:
    if provider_type == "openrouter":
        return "openai/whisper-1"
    return "whisper-1"


async def transcribe_audio_bytes(
    db: AsyncSession,
    audio_bytes: bytes,
    *,
    filename: str = "voice.webm",
    mime_type: str = "audio/webm",
    language: str | None = None,
) -> str:
    if not audio_bytes:
        raise ValueError("Empty audio file.")
    if len(audio_bytes) < 800:
        raise ValueError("Recording too short. Speak a little longer and try again.")
    if len(audio_bytes) > _MAX_BYTES:
        raise ValueError("Audio file is too large (max 25 MB).")

    provider_type, api_key, base_url = await _resolve_transcription_provider(db)
    model = _transcription_model(provider_type)
    suffix = _suffix_for_file(filename, mime_type)

    # Normalize the language hint for Whisper (ISO-639-1). A Persian prompt hint
    # biases the decoder toward Persian script and reduces Latin transliteration.
    norm_lang = (language or "").strip().lower()
    whisper_lang = norm_lang if norm_lang in ("en", "fa") else None
    whisper_prompt = "این یک پیام صوتی به زبان فارسی است." if whisper_lang == "fa" else None

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            tmp_path = tmp.name

        kwargs: dict = {
            "model": model,
            "api_key": api_key,
        }
        if whisper_lang:
            kwargs["language"] = whisper_lang
        if whisper_prompt:
            kwargs["prompt"] = whisper_prompt
        if provider_type == "openai":
            kwargs["custom_llm_provider"] = "openai"
        elif provider_type == "azure":
            kwargs["custom_llm_provider"] = "azure"
        elif provider_type == "openrouter":
            kwargs["custom_llm_provider"] = "openrouter"
            kwargs["api_base"] = _normalize_openrouter_base(base_url)
        elif base_url:
            kwargs["api_base"] = base_url.rstrip("/")

        with open(tmp_path, "rb") as audio_file:
            kwargs["file"] = audio_file
            result = await atranscription(**kwargs)

        text = (getattr(result, "text", None) or "").strip()
        if not text:
            raise ValueError("No speech detected. Try speaking closer to the microphone.")
        return text
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
