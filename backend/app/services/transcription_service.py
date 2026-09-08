"""Speech-to-text for voice messages via LiteLLM (Whisper-compatible providers)."""

from __future__ import annotations

import datetime
import os
import tempfile
from pathlib import Path

from litellm import atranscription
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import CHAT_CLIENT_APP
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.budget_reservation_service import (
    reservation_hold_usd,
    reservation_key,
    reserve,
)
from app.services.proxy_service import settle_auxiliary_usage
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
) -> tuple[str, str | None, str | None, int | None]:
    """Return provider credentials and connection id for speech-to-text."""
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
            return p, decrypt_secret(conn.api_key_encrypted), conn.base_url, conn.id
    if rows and rows[0].api_key_encrypted:
        c = rows[0]
        return (
            (c.provider_type or "openai").lower(),
            decrypt_secret(c.api_key_encrypted),
            c.base_url,
            c.id,
        )
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
    user_id: int | None = None,
    username: str | None = None,
) -> str:
    if not audio_bytes:
        raise ValueError("Empty audio file.")
    if len(audio_bytes) < 800:
        raise ValueError("Recording too short. Speak a little longer and try again.")
    if len(audio_bytes) > _MAX_BYTES:
        raise ValueError("Audio file is too large (max 25 MB).")

    provider_type, api_key, base_url, connection_id = await _resolve_transcription_provider(db)
    model = _transcription_model(provider_type)
    ai_model = (
        (
            await db.execute(
                select(AIModel)
                .where(
                    AIModel.connection_id == connection_id,
                    or_(
                        AIModel.external_id == model,
                        AIModel.external_id == model.removeprefix("openai/"),
                    ),
                )
                .order_by(AIModel.id.desc())
            )
        ).scalars().first()
        if connection_id is not None
        else None
    )
    reservation_id: str | None = None
    if user_id is not None:
        hold_body = {
            "model": model,
            "bytes": len(audio_bytes),
            "filename": filename,
        }
        hold = await reserve(
            db,
            user_id=user_id,
            alpha_router_api_key_id=None,
            amount_usd=await reservation_hold_usd(
                db,
                service_type="audio",
                ai_model=ai_model,
                provider_type=provider_type,
                model_id=model,
                connection_id=connection_id,
                quantity=1.0,
                unit="request",
            ),
            operation="transcription",
            model_id=model,
            idempotency_key=reservation_key(
                hold_body,
                operation="transcription",
            ),
        )
        reservation_id = hold.id if hold else None
        await db.commit()
    suffix = _suffix_for_file(filename, mime_type)

    # Normalize the language hint for Whisper (ISO-639-1). A Persian prompt hint
    # biases the decoder toward Persian script and reduces Latin transliteration.
    norm_lang = (language or "").strip().lower()
    whisper_lang = norm_lang if norm_lang in ("en", "fa") else None
    whisper_prompt = "این یک پیام صوتی به زبان فارسی است." if whisper_lang == "fa" else None

    tmp_path: str | None = None
    result = None
    transcript = ""
    success = False
    error_message: str | None = None
    started_at = datetime.datetime.utcnow()
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
        transcript = text
        success = True
        return transcript
    except Exception as exc:
        error_message = str(exc)[:500]
        raise
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if user_id is not None and username is not None:
            await settle_auxiliary_usage(
                user_id=user_id,
                username=username,
                ai_model=ai_model,
                provider_type=provider_type,
                model_id=model,
                response=result,
                prompt=f"audio:{filename}:{len(audio_bytes)} bytes",
                completion=transcript,
                operation_name="transcription",
                client_app=f"{CHAT_CLIENT_APP} (audio:transcription)",
                budget_reservation_id=reservation_id,
                success=success,
                error_message=error_message,
                service_type="audio",
                started_at=started_at,
            )
