"""Speech-to-text system default: the setting key, its gate, and the read path.

Writes go through ``system_default_models``, which owns every capability's
default and imports ``SETTING_KEY`` from here — so the setting name has exactly
one definition and only one writer.

Leaving this unset is a supported state: the transcription pipeline falls back
to its legacy provider heuristic, so an upgraded install keeps working until an
admin chooses a model.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.services.model_access_service import ACCESS_PUBLIC
from app.services.model_capabilities import model_kinds, model_media_flags

SETTING_KEY = "global_default_transcription_model_id"


class GlobalDefaultTranscriptionModelError(ValueError):
    """Raised by the eligibility gate below when a model cannot be used."""


def parse_stored_id(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def model_supports_transcription(model: AIModel) -> bool:
    """True only when the catalog says this model transcribes audio.

    Unlike ``model_supports_text_chat``, an unclassified model is **not** given
    the benefit of the doubt: sending audio to a model that cannot accept it
    fails at the provider and bills the user for the attempt.
    """
    media = model_media_flags(
        external_id=model.external_id or "",
        is_image_model=bool(model.is_image_model),
        is_video_model=bool(getattr(model, "is_video_model", False)),
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )
    kinds = model_kinds(
        external_id=model.external_id or "",
        is_image_model=media["is_image_model"],
        is_video_model=media["is_video_model"],
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )
    return "transcription" in kinds


async def get_transcription_default_model_id(db: AsyncSession) -> int | None:
    row = await db.get(SystemSetting, SETTING_KEY)
    return parse_stored_id(row.value if row else None)


async def get_transcription_default_model(db: AsyncSession) -> AIModel | None:
    """The configured default, or None when unset or no longer eligible."""
    model_id = await get_transcription_default_model_id(db)
    if model_id is None:
        return None
    model = await db.get(AIModel, model_id)
    if model is None:
        return None
    if not await _is_usable_transcription_default(db, model):
        return None
    return model


async def _is_usable_transcription_default(db: AsyncSession, model: AIModel) -> bool:
    try:
        await _assert_usable_transcription_default(db, model)
    except GlobalDefaultTranscriptionModelError:
        return False
    return True


async def _assert_usable_transcription_default(db: AsyncSession, model: AIModel) -> None:
    if not bool(model.is_enabled) or bool(model.admin_disabled):
        raise GlobalDefaultTranscriptionModelError("Model must be enabled")
    access = (model.access_type or ACCESS_PUBLIC).strip().lower()
    if access != ACCESS_PUBLIC:
        # Every user falls back to this model, so a private one would break
        # transcription for anyone outside its access list.
        raise GlobalDefaultTranscriptionModelError("Model must be public")
    if not model_supports_transcription(model):
        raise GlobalDefaultTranscriptionModelError("Model must support transcription")
    if model.connection_id is None:
        raise GlobalDefaultTranscriptionModelError("Model has no connection")
    conn = await db.get(Connection, model.connection_id)
    if conn is None or not bool(conn.is_active):
        raise GlobalDefaultTranscriptionModelError("Model connection must be active")
    if not conn.api_key_encrypted:
        raise GlobalDefaultTranscriptionModelError("Model connection has no API key")
