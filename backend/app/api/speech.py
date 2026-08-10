"""Text-to-speech generation (synchronous, OpenAI-compatible audio/speech API)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user
from app.config import get_settings
from app.database import AsyncSessionLocal, get_db
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.model_access_service import resolve_access_subject, user_can_access_model
from app.services.budget_reservation_service import (
    estimate_speech_hold,
    reservation_key,
    reserve,
)
from app.services.model_capabilities import speech_generation_capabilities
from app.services.secret_crypto import decrypt_secret
from app.services.speech_billing_service import SpeechBillingCapture, log_speech_usage
from app.services.speech_providers import NormalizedSpeechRequest, get_speech_adapter
from app.services.speech_providers.contracts import SpeechProviderError
from app.services.storage_service import (
    media_content_hash,
    media_public_url,
    store_media_from_blob,
)
from app.services.user_chat_storage_service import finalize_chat_session_speech

router = APIRouter(prefix="/api/speech", tags=["speech"])


class SpeechClientDisconnected(Exception):
    """Internal signal used to stop upstream work after the browser disconnects."""


class SpeechRequest(BaseModel):
    model: str
    text: str
    voice: str | None = None
    response_format: str = "mp3"
    speed: float | None = None
    pitch: float | None = None
    sample_rate: int | None = None
    chat_session_id: str | None = None
    persist: bool = True
    routing: dict[str, object] | None = None
    assistant_client_message_id: str | None = None


def _normalize_model_id(model_id: str) -> str:
    raw = (model_id or "").strip()
    while raw.startswith("~"):
        raw = raw[1:]
    return raw


def _normalize_text(text: str) -> str:
    return (text or "").strip()


def _normalize_response_format(value: str | None) -> str:
    # Product surface only uses mp3 for chat TTS.
    del value
    return "mp3"


async def _await_speech_work(
    work,
    *,
    request: Request,
    timeout_seconds: float,
):
    """Await upstream work with a hard deadline and client-disconnect cancellation."""
    task = asyncio.create_task(work)
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise SpeechClientDisconnected()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise asyncio.TimeoutError()
            await asyncio.wait({task}, timeout=min(0.5, remaining))
        return await task
    except BaseException:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        raise


async def _resolve_speech_model(
    db: AsyncSession,
    raw_model: str,
    *,
    access_user_id: int | None = None,
) -> tuple[str, str | None, str | None, str | None, AIModel | None]:
    model_id = _normalize_model_id(raw_model)
    subject = (
        await resolve_access_subject(db, user_id=access_user_id) if access_user_id is not None else None
    )
    row: AIModel | None = None
    if model_id.startswith("model::"):
        try:
            model_pk = int(model_id.split("::", 1)[1])
        except Exception:
            model_pk = None
        if model_pk is not None:
            row = (
                await db.execute(
                    select(AIModel).where(AIModel.id == model_pk, AIModel.is_enabled == True)  # noqa: E712
                )
            ).scalars().first()
        if row:
            conn = await db.get(Connection, row.connection_id)
            if conn and conn.is_active:
                if subject is None or await user_can_access_model(db, row, subject):
                    return (
                        row.external_id,
                        decrypt_secret(conn.api_key_encrypted),
                        conn.base_url,
                        conn.provider_type,
                        row,
                    )
            row = None

    if not row:
        candidates = (
            await db.execute(
                select(AIModel, Connection)
                .join(Connection, Connection.id == AIModel.connection_id)
                .where(
                    AIModel.external_id == model_id,
                    AIModel.is_enabled == True,  # noqa: E712
                    Connection.is_active == True,  # noqa: E712
                )
                .order_by(AIModel.id.desc())
            )
        ).all()
        for cand_row, conn in candidates:
            if subject is None or await user_can_access_model(db, cand_row, subject):
                return (
                    cand_row.external_id,
                    decrypt_secret(conn.api_key_encrypted),
                    conn.base_url,
                    conn.provider_type,
                    cand_row,
                )

    if not row:
        return model_id, None, None, None, None
    return model_id, None, None, None, None


def _validate_capabilities(
    *,
    external_id: str,
    pricing_raw: str | None,
    text: str,
    voice: str | None,
    response_format: str,
    speed: float | None,
) -> dict[str, Any]:
    """Validate request parameters against model capabilities; raise on mismatch."""
    settings = get_settings()
    caps = speech_generation_capabilities(
        external_id=external_id,
        pricing_raw=pricing_raw,
    )
    if not caps.get("supports_text_to_speech"):
        raise HTTPException(
            status_code=400,
            detail="This model does not support text-to-speech generation.",
        )
    max_text = caps.get("max_text_length") or int(settings.speech_max_text_length or 5000)
    if len(text) > max_text:
        raise HTTPException(
            status_code=400,
            detail=f"Text exceeds the maximum length of {max_text} characters for this model.",
        )
    voices = caps.get("supported_voices") or []
    # Remap stale UI defaults (e.g. OpenAI "alloy") onto the model's first voice.
    if voices:
        if not voice or voice not in voices:
            caps = {**caps, "_resolved_voice": voices[0]}
        else:
            caps = {**caps, "_resolved_voice": voice}
    elif voice:
        caps = {**caps, "_resolved_voice": voice}
    else:
        caps = {**caps, "_resolved_voice": None}
    formats = caps.get("supported_formats")
    if formats and response_format not in formats:
        raise HTTPException(
            status_code=400,
            detail=f"Format '{response_format}' is not supported by this model. Supported: {', '.join(formats)}",
        )
    speeds = caps.get("supported_speeds")
    if speeds and speed is not None:
        lo, hi = float(speeds[0]), float(speeds[1])
        if speed < lo or speed > hi:
            raise HTTPException(
                status_code=400,
                detail=f"Speed must be between {lo} and {hi} for this model.",
            )
    return caps


@router.post("/generate")
async def generate_speech(
    request: Request,
    body: SpeechRequest,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    generation_start = time.perf_counter()
    settings = get_settings()
    # Capture identity primitives before any commit/rollback expires the ORM user.
    settle_user_id = int(user.id)
    settle_username = str(user.username or "")
    billing = SpeechBillingCapture(model_id=_normalize_model_id(body.model))
    budget_reservation_id: str | None = None
    success = True
    error_message: str | None = None
    response_out: dict | None = None

    text = _normalize_text(body.text)
    if not text:
        raise HTTPException(status_code=400, detail="Text is required for speech generation.")
    response_format = _normalize_response_format(body.response_format)

    try:
        model_id, api_key, base_url, provider_type, ai_model = await _resolve_speech_model(
            db, body.model, access_user_id=user.id
        )
        billing.model_id = model_id
        billing.ai_model_id = getattr(ai_model, "id", None) if ai_model else None
        billing.connection_id = getattr(ai_model, "connection_id", None) if ai_model else None
        billing.provider_type = provider_type
        body.model = model_id

        if not api_key:
            raise HTTPException(status_code=400, detail="Connection has no API key configured.")
        if not provider_type:
            raise HTTPException(status_code=400, detail="Connection has no provider type configured.")

        caps = _validate_capabilities(
            external_id=model_id,
            pricing_raw=getattr(ai_model, "pricing_raw", None) if ai_model else None,
            text=text,
            voice=body.voice,
            response_format=response_format,
            speed=body.speed,
        )
        resolved_voice = caps.get("_resolved_voice")
        if isinstance(resolved_voice, str):
            body.voice = resolved_voice

        adapter = get_speech_adapter(provider_type)

        # Budget hold — per character.
        hold_body = body.model_dump()
        if request.headers.get("Idempotency-Key"):
            hold_body["_idempotency_key"] = request.headers["Idempotency-Key"]
        configured_hold = await _configured_speech_cost(
            db,
            provider_type=provider_type or "unknown",
            model_id=model_id,
            connection_id=billing.connection_id,
            characters=len(text),
        )
        hold = await reserve(
            db,
            user_id=user.id,
            alpha_router_api_key_id=None,
            amount_usd=max(
                estimate_speech_hold(ai_model, characters=len(text)),
                float(configured_hold or 0) * 1.1,
            ),
            operation="speech",
            model_id=model_id,
            idempotency_key=reservation_key(hold_body, operation="speech"),
        )
        budget_reservation_id = hold.id if hold else None
        await db.commit()

        normalized = NormalizedSpeechRequest(
            model_id=model_id,
            text=text,
            voice=body.voice,
            response_format=response_format,
            speed=body.speed,
            pitch=body.pitch,
            sample_rate=body.sample_rate,
            routing=dict(body.routing or {}),
        )

        result = await _await_speech_work(
            adapter.generate(api_key=api_key, base_url=base_url, request=normalized),
            request=request,
            timeout_seconds=float(settings.speech_request_timeout_seconds or 120),
        )

        billing.characters = result.characters
        billing.duration_seconds = result.duration_seconds
        billing.upstream_request_id = result.upstream_request_id
        billing.raw_usage = result.raw_usage

        # Persist the audio asset.
        audio_url: str | None = None
        if body.persist:
            blob, mime, content_hash = await asyncio.to_thread(
                media_content_hash,
                result.audio_blob,
                result.mime,
                "audio",
            )
            asset = await store_media_from_blob(
                db,
                user_id=user.id,
                username=user.username,
                kind="audio",
                blob=blob,
                mime=mime,
                content_hash=content_hash,
                source_model=model_id,
                source_prompt=text,
                chat_session_id=body.chat_session_id,
                file_name_hint=f"speech-{int(time.time())}.{response_format}",
                metadata={
                    "voice": body.voice,
                    "format": response_format,
                    "characters": result.characters,
                    "duration_seconds": result.duration_seconds,
                },
            )
            audio_url = media_public_url(asset.id)
            if body.chat_session_id and audio_url:
                await finalize_chat_session_speech(
                    db,
                    user.id,
                    body.chat_session_id,
                    audio_url,
                    text,
                    model_id,
                    params={
                        "voice": body.voice,
                        "format": response_format,
                        "duration_seconds": result.duration_seconds,
                        "characters": result.characters,
                    },
                )
        await db.commit()

        response_out = {
            "data": [{"url": audio_url}] if audio_url else [],
            "format": response_format,
            "voice": body.voice,
            "model": model_id,
            "characters": result.characters,
            "duration_seconds": result.duration_seconds,
        }
        return response_out  # mutated in finally with request_log_id when available

    except SpeechClientDisconnected as exc:
        success = False
        error_message = "Speech generation stopped because the client disconnected."
        raise HTTPException(status_code=499, detail=error_message) from exc
    except asyncio.TimeoutError as exc:
        success = False
        error_message = "Speech generation timed out."
        raise HTTPException(status_code=504, detail=error_message) from exc
    except SpeechProviderError as exc:
        success = False
        error_message = exc.message
        raise HTTPException(status_code=exc.status_code, detail=error_message) from exc
    except HTTPException as exc:
        success = False
        detail = exc.detail
        error_message = detail if isinstance(detail, str) else str(detail)
        raise
    except Exception as exc:
        success = False
        import logging

        logging.getLogger("app.api.speech").exception("Unhandled error during speech generation")
        error_message = "Speech generation failed due to an internal error"
        raise HTTPException(status_code=500, detail=error_message) from exc
    finally:
        elapsed_ms = (time.perf_counter() - generation_start) * 1000
        commit_error: Exception | None = None
        try:
            if success:
                await db.commit()
            else:
                await db.rollback()
        except Exception as exc:
            import logging

            logging.getLogger("app.api.speech").exception(
                "Failed to close speech request transaction before billing"
            )
            try:
                await db.rollback()
            except Exception:
                pass
            if success:
                success = False
                error_message = "Speech persistence failed"
                commit_error = exc

        async def _settle_speech_usage() -> int | None:
            for attempt in range(3):
                try:
                    async with AsyncSessionLocal() as log_db:
                        log_id = await log_speech_usage(
                            log_db,
                            user_id=settle_user_id,
                            username=settle_username,
                            capture=billing,
                            prompt=text,
                            response_time_ms=elapsed_ms,
                            success=success,
                            error_message=error_message,
                            source_ip=request.client.host if request.client else None,
                            budget_reservation_id=budget_reservation_id,
                        )
                        if log_id and success and body.chat_session_id:
                            from app.services.user_chat_storage_service import (
                                attach_request_log_id_to_chat_message,
                            )

                            await attach_request_log_id_to_chat_message(
                                log_db,
                                settle_user_id,
                                body.chat_session_id,
                                int(log_id),
                                client_message_id=body.assistant_client_message_id,
                            )
                        await log_db.commit()
                    return log_id
                except Exception:
                    if attempt < 2:
                        await asyncio.sleep(0.1 * (attempt + 1))
                        continue
                    import logging

                    logging.getLogger("app.api.speech").exception(
                        "Speech usage settlement failed after retries; "
                        "reservation remains held for recovery"
                    )
            return None

        settled_log_id = await asyncio.shield(_settle_speech_usage())
        if response_out is not None and settled_log_id:
            response_out["request_log_id"] = int(settled_log_id)
        if commit_error is not None:
            raise HTTPException(
                status_code=500,
                detail="Speech persistence failed due to an internal error",
            ) from commit_error


async def _configured_speech_cost(
    db: AsyncSession,
    *,
    provider_type: str,
    model_id: str,
    connection_id: int | None,
    characters: int,
) -> float | None:
    from app.services.usage_accounting_service import configured_metered_cost

    return await configured_metered_cost(
        db,
        provider_type=provider_type,
        service_type="speech",
        model_id=model_id,
        connection_id=connection_id,
        quantity=float(max(1, characters)),
        unit="character",
    )
