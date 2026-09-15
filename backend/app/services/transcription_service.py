"""Speech-to-text for voice messages via LiteLLM (Whisper-compatible providers)."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import struct
import tempfile
from dataclasses import dataclass

from litellm import atranscription
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding import CHAT_CLIENT_APP
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.failure_details import failure_message
from app.services.budget_reservation_service import (
    reservation_hold_usd,
    reservation_key,
    reserve,
)
from app.services.system_default_models import get_default_model, model_supports_transcription
from app.services.llm_providers import litellm_transcription_model
from app.services.openrouter_transcription_service import (
    OpenRouterTranscriptionError,
    transcribe_with_openrouter,
)
from app.services.model_access_service import resolve_access_subject, user_can_access_model
from app.services.usage_logging_service import settle_auxiliary_usage
from app.services.secret_crypto import decrypt_secret
import contextlib

logger = logging.getLogger("app.services.transcription")

_MAX_BYTES = 25 * 1024 * 1024

#: The recorder asks for 128 kbps, i.e. ~16 KB per second of audio. Used only as
#: a floor/estimate for billing when nothing more authoritative is available.
_ESTIMATED_BYTES_PER_SECOND = 16_000
#: Opus on a near-silent stream can fall this low. Used as the *ceiling* on
#: duration: a file simply cannot hold more seconds than this implies, so a
#: wrong or hostile client value can never over-bill the user.
_MIN_BYTES_PER_SECOND = 500
#: Never bill more than this from one recording, whatever a caller claims.
_MAX_BILLABLE_SECONDS = 3600.0

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


def _supports_verbose_json(model_id: str, provider_type: str | None) -> bool:
    """Whisper on OpenAI/Azure returns an authoritative ``duration``.

    Narrow on purpose: the gpt-4o transcription models reject the format, and a
    gateway sitting in front of Whisper may not implement it either. Everywhere
    else the recorded client duration is used, which is already bounded by file
    size on both sides.
    """
    provider = (provider_type or "").strip().lower()
    if provider not in ("openai", "azure"):
        return False
    return "whisper" in (model_id or "").lower()


def wav_duration_seconds(audio_bytes: bytes) -> float | None:
    """Exact duration of a RIFF/WAVE upload, read from its own header.

    The client converts recordings to WAV before upload, so this is normally
    available and removes the estimate entirely — no trusting a client-supplied
    number, no guessing a bitrate. Returns None for any other container.

    Chunks are walked rather than read at fixed offsets, because a WAV may carry
    LIST/fact chunks before `data`.
    """
    if len(audio_bytes) < 44 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        return None
    try:
        pos = 12
        sample_rate = channels = bits = None
        data_size = None
        while pos + 8 <= len(audio_bytes):
            chunk_id = audio_bytes[pos : pos + 4]
            (chunk_size,) = struct.unpack_from("<I", audio_bytes, pos + 4)
            body = pos + 8
            if chunk_id == b"fmt " and body + 16 <= len(audio_bytes):
                (channels,) = struct.unpack_from("<H", audio_bytes, body + 2)
                (sample_rate,) = struct.unpack_from("<I", audio_bytes, body + 4)
                (bits,) = struct.unpack_from("<H", audio_bytes, body + 14)
            elif chunk_id == b"data":
                data_size = min(chunk_size, len(audio_bytes) - body)
                break
            # Chunks are word-aligned: an odd size is followed by a pad byte.
            pos = body + chunk_size + (chunk_size & 1)
        if not sample_rate or not channels or not bits or not data_size:
            return None
        # Header sanity: a crafted fmt chunk (1 Hz, 1 channel, 8 bit) would make
        # a few kilobytes "hours" of billable audio, or the reverse.
        if not (8000 <= sample_rate <= 192_000) or not (1 <= channels <= 8) or bits not in (8, 16, 24, 32, 64):
            return None
        bytes_per_frame = channels * (bits // 8)
        if bytes_per_frame <= 0:
            return None
        seconds = data_size / bytes_per_frame / sample_rate
        return seconds if seconds > 0 else None
    except (struct.error, ZeroDivisionError, ValueError):
        return None


def _write_temp_audio(audio_bytes: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        return tmp.name


def _unlink_quietly(path: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(path)


def resolve_billable_seconds(
    audio_bytes: bytes,
    *,
    client_seconds: float | None,
    provider_seconds: float | None,
) -> tuple[float, str]:
    """Seconds of audio to bill, plus where the number came from.

    Order of trust: the provider's own measurement, then the container's own
    header, then the client's recorded length, then a size-based estimate.

    The client value is bounded on both sides by what the file size makes
    physically possible, so it can neither under-report its way to a cheaper
    bill nor over-report into an inflated one. The two upper layers need no
    such bounding: both are measured, not claimed.
    """
    if provider_seconds and float(provider_seconds) > 0:
        return min(float(provider_seconds), _MAX_BILLABLE_SECONDS), "provider"
    container_seconds = wav_duration_seconds(audio_bytes)
    if container_seconds:
        return min(container_seconds, _MAX_BILLABLE_SECONDS), "container"

    size_estimate = len(audio_bytes) / _ESTIMATED_BYTES_PER_SECOND
    # A file cannot contain more audio than its own bytes allow.
    size_ceiling = max(len(audio_bytes) / _MIN_BYTES_PER_SECOND, 1.0)
    hard_cap = min(size_ceiling, _MAX_BILLABLE_SECONDS)
    claimed = float(client_seconds or 0)
    if claimed > 0:
        # Opus is variable-bitrate, so a quiet recording is legitimately smaller
        # than the nominal estimate; half of it is a safe floor.
        bounded = max(claimed, size_estimate * 0.5)
        return min(bounded, hard_cap), "client"
    return min(size_estimate, hard_cap), "estimate"


def _provider_duration_seconds(result) -> float | None:
    for attr in ("duration", "duration_seconds"):
        value = getattr(result, attr, None)
        if value is None and isinstance(result, dict):
            value = result.get(attr)
        try:
            if value is not None and float(value) > 0:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


_ALLOWED_AUDIO_SUFFIXES = frozenset(_EXT_BY_MIME.values()) | frozenset({".m4a", ".mp4", ".oga", ".opus"})


def _suffix_for_file(filename: str, mime_type: str) -> str:
    """Temp-file suffix for the LiteLLM upload, from a fixed audio whitelist.

    The suffix came straight from the client filename (``voice.php``,
    ``x.exe``...). It only names a temp file, but the whitelist keeps the
    file we hand to a third-party library an audio file by name too.
    """
    name = (filename or "").lower()
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1]
        if ext in _ALLOWED_AUDIO_SUFFIXES:
            return ext
    mime = (mime_type or "").split(";")[0].strip().lower()
    return _EXT_BY_MIME.get(mime, ".webm")


@dataclass(slots=True)
class ResolvedTranscription:
    """Everything one transcription call needs, plus where the choice came from."""

    model_id: str
    api_key: str | None
    base_url: str | None
    provider_type: str
    connection_id: int | None
    ai_model: AIModel | None
    source: str  # "user" | "admin" | "legacy"


def parse_model_ref(value: str | int | None) -> int | None:
    """Accept a catalog id as ``model::12``, ``"12"`` or ``12``."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.startswith("model::"):
        raw = raw.split("::", 1)[1]
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


async def _resolve_catalog_row(
    db: AsyncSession,
    model: AIModel | None,
    *,
    source: str,
) -> ResolvedTranscription | None:
    """Turn a catalog row into a usable target, or None when it is not."""
    if model is None:
        return None
    if not bool(model.is_enabled) or bool(model.admin_disabled):
        return None
    if not model_supports_transcription(model):
        return None
    if model.connection_id is None:
        return None
    conn = await db.get(Connection, model.connection_id)
    if conn is None or not bool(conn.is_active) or not conn.api_key_encrypted:
        return None
    return ResolvedTranscription(
        model_id=model.external_id,
        api_key=decrypt_secret(conn.api_key_encrypted),
        base_url=conn.base_url,
        provider_type=(conn.provider_type or model.provider_type or "openai").lower(),
        connection_id=conn.id,
        ai_model=model,
        source=source,
    )


async def _resolve_user_choice(
    db: AsyncSession,
    model_pk: int,
    user_id: int | None,
) -> ResolvedTranscription | None:
    """A model the user picked for themselves, checked against their own ACL."""
    model = await db.get(AIModel, model_pk)
    if model is None:
        return None
    if user_id is not None:
        subject = await resolve_access_subject(db, user_id=user_id)
        if not await user_can_access_model(db, model, subject):
            return None
    return await _resolve_catalog_row(db, model, source="user")


async def resolve_transcription_target(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    preferred_model_ref: str | int | None = None,
) -> ResolvedTranscription:
    """Pick the speech-to-text model: user choice, then admin default, then legacy.

    Each layer is skipped silently when its model is missing, disabled, private
    to someone else, or not a transcription model — a stale preference must
    never block dictation, it just falls through to the next layer.
    """
    preferred_pk = parse_model_ref(preferred_model_ref)
    if preferred_pk is not None:
        resolved = await _resolve_user_choice(db, preferred_pk, user_id)
        if resolved is not None:
            return resolved
        logger.info(
            "Transcription model %s is not usable for user %s; falling back",
            preferred_pk,
            user_id,
        )

    admin_model = await get_default_model(db, "voice")
    resolved = await _resolve_catalog_row(db, admin_model, source="admin")
    if resolved is not None:
        return resolved

    # Legacy: no catalog model configured. Guess a provider and assume whisper-1.
    # Kept so installs that never set a default keep working after an upgrade.
    provider_type, api_key, base_url, connection_id = await _resolve_transcription_provider(db)
    model_id = _transcription_model(provider_type)
    ai_model = (
        (
            await db.execute(
                select(AIModel)
                .where(
                    AIModel.connection_id == connection_id,
                    or_(
                        AIModel.external_id == model_id,
                        AIModel.external_id == model_id.removeprefix("openai/"),
                    ),
                )
                .order_by(AIModel.id.desc())
            )
        )
        .scalars()
        .first()
        if connection_id is not None
        else None
    )
    return ResolvedTranscription(
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        provider_type=provider_type,
        connection_id=connection_id,
        ai_model=ai_model,
        source="legacy",
    )


async def _resolve_transcription_provider(
    db: AsyncSession,
) -> tuple[str, str | None, str | None, int | None]:
    """Return provider credentials and connection id for speech-to-text."""
    preferred = ("openai", "azure", "openrouter")
    rows = (
        (
            await db.execute(
                select(Connection).where(Connection.is_active == True).order_by(Connection.id)  # noqa: E712
            )
        )
        .scalars()
        .all()
    )
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
    preferred_model_ref: str | int | None = None,
    client_duration_seconds: float | None = None,
) -> str:
    if not audio_bytes:
        raise ValueError("Empty audio file.")
    if len(audio_bytes) < 800:
        raise ValueError("Recording too short. Speak a little longer and try again.")
    if len(audio_bytes) > _MAX_BYTES:
        raise ValueError("Audio file is too large (max 25 MB).")

    target = await resolve_transcription_target(
        db,
        user_id=user_id,
        preferred_model_ref=preferred_model_ref,
    )
    provider_type = target.provider_type
    api_key = target.api_key
    base_url = target.base_url
    connection_id = target.connection_id
    model = target.model_id
    ai_model = target.ai_model
    if not api_key:
        raise ValueError("No active connection with an API key is available for speech-to-text.")
    # Hold on the estimated length; the settle below uses the measured one.
    # Whisper-class models are priced per minute of audio, so a flat per-request
    # hold made a ten-second note and a ten-minute one cost the same.
    billable_seconds, duration_source = resolve_billable_seconds(
        audio_bytes,
        client_seconds=client_duration_seconds,
        provider_seconds=None,
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
                quantity=billable_seconds,
                unit="second",
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
    #
    # "auto" (the default) and any unrecognized value send **no** `language` at
    # all so the provider detects the spoken language. This matters: forcing
    # "en" on Persian audio makes Whisper transliterate it into Latin script or
    # translate it outright, which reads as "speech-to-text is broken".
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
        if provider_type == "openrouter":
            # OpenRouter's transcription endpoint takes JSON with base64 audio,
            # not OpenAI's multipart upload, so LiteLLM cannot reach it at all.
            try:
                result = await transcribe_with_openrouter(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    audio_bytes=audio_bytes,
                    filename=filename,
                    mime_type=mime_type,
                    language=whisper_lang,
                )
            except OpenRouterTranscriptionError as exc:
                raise ValueError(str(exc)) from exc
        else:
            # Only the LiteLLM path needs the audio on disk as a file handle.
            # Writing up to MAX_VOICE_UPLOAD_BYTES is disk I/O: off the loop.
            tmp_path = await asyncio.to_thread(_write_temp_audio, audio_bytes, suffix)

            kwargs: dict = {
                # A catalog id is not a LiteLLM route. See
                # `litellm_transcription_model` for why transcription needs its
                # own mapping rather than the chat one.
                "model": litellm_transcription_model(model, provider_type),
                "api_key": api_key,
            }
            if whisper_lang:
                kwargs["language"] = whisper_lang
            if whisper_prompt:
                kwargs["prompt"] = whisper_prompt
            if _supports_verbose_json(model, provider_type):
                # verbose_json carries `duration`, which the settle bills on.
                kwargs["response_format"] = "verbose_json"
            if provider_type == "azure":
                kwargs["custom_llm_provider"] = "azure"
            if base_url:
                # Honour the connection's base_url so an OpenAI-compatible
                # gateway is not silently bypassed for api.openai.com.
                kwargs["api_base"] = base_url.rstrip("/")

            with open(tmp_path, "rb") as audio_file:
                kwargs["file"] = audio_file
                result = await atranscription(**kwargs)

        provider_seconds = _provider_duration_seconds(result)
        if provider_seconds is not None:
            billable_seconds, duration_source = resolve_billable_seconds(
                audio_bytes,
                client_seconds=client_duration_seconds,
                provider_seconds=provider_seconds,
            )
        text = (getattr(result, "text", None) or "").strip()
        if not text:
            raise ValueError("No speech detected. Try speaking closer to the microphone.")
        transcript = text
        success = True
        return transcript
    except Exception as exc:
        error_message = failure_message(exc)[:500]
        raise
    finally:
        if tmp_path:
            await asyncio.to_thread(_unlink_quietly, tmp_path)
        if user_id is not None and username is not None:
            logger.info(
                "Transcription billed %.2fs (source=%s) model=%s via %s",
                billable_seconds,
                duration_source,
                model,
                target.source,
            )
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
                # Without these the settle had no quantity at all, so every
                # transcription landed at (or near) zero cost.
                quantity=billable_seconds if success else None,
                unit="second" if success else None,
                started_at=started_at,
            )
