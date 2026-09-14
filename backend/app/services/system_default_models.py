"""Admin-selected system default model, per capability.

One registry instead of a module per capability. Each kind names the
``system_settings`` key it lives under and the predicate a catalog row must
satisfy, and every read/write path below is shared.

The chat and transcription keys are imported from their own modules rather than
re-declared, so there is exactly one definition of each setting name.

Leaving a kind unset is always supported: callers fall back to whatever they did
before an admin made a choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.services.global_default_chat_model import SETTING_KEY as CHAT_SETTING_KEY
from app.services.global_default_chat_model import model_supports_text_chat
from app.services.global_default_transcription_model import (
    SETTING_KEY as VOICE_SETTING_KEY,
)
from app.services.global_default_transcription_model import model_supports_transcription
from app.services.model_access_service import ACCESS_PUBLIC
from app.services.model_capabilities import model_kinds, model_media_flags


class SystemDefaultModelError(ValueError):
    """Raised when a catalog model cannot serve as the default for a kind."""


def _catalog_kinds(model: AIModel) -> list[str]:
    media = model_media_flags(
        external_id=model.external_id or "",
        is_image_model=bool(model.is_image_model),
        is_video_model=bool(getattr(model, "is_video_model", False)),
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )
    return model_kinds(
        external_id=model.external_id or "",
        is_image_model=media["is_image_model"],
        is_video_model=media["is_video_model"],
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )


def model_supports_image_generation(model: AIModel) -> bool:
    return "image" in _catalog_kinds(model)


def model_supports_video_generation(model: AIModel) -> bool:
    return "video" in _catalog_kinds(model)


@dataclass(frozen=True, slots=True)
class DefaultModelKind:
    key: str
    label: str
    setting_key: str
    supports: Callable[[AIModel], bool]
    requirement: str
    #: Catalog tag the admin UI filters its picker by.
    catalog_kind: str


DEFAULT_MODEL_KINDS: dict[str, DefaultModelKind] = {
    "chat": DefaultModelKind(
        key="chat",
        label="Chat",
        setting_key=CHAT_SETTING_KEY,
        supports=model_supports_text_chat,
        requirement="Model must support text chat",
        catalog_kind="text",
    ),
    "voice": DefaultModelKind(
        key="voice",
        label="Voice",
        setting_key=VOICE_SETTING_KEY,
        supports=model_supports_transcription,
        requirement="Model must support transcription",
        catalog_kind="transcription",
    ),
    "image": DefaultModelKind(
        key="image",
        label="Image",
        setting_key="global_default_image_model_id",
        supports=model_supports_image_generation,
        requirement="Model must support image generation",
        catalog_kind="image",
    ),
    "video": DefaultModelKind(
        key="video",
        label="Video",
        setting_key="global_default_video_model_id",
        supports=model_supports_video_generation,
        requirement="Model must support video generation",
        catalog_kind="video",
    ),
}

DEFAULT_MODEL_KIND_KEYS = tuple(DEFAULT_MODEL_KINDS)


def resolve_kind(kind: str) -> DefaultModelKind:
    entry = DEFAULT_MODEL_KINDS.get((kind or "").strip().lower())
    if entry is None:
        raise SystemDefaultModelError(f"Unknown default kind: {kind}")
    return entry


def _parse_stored_id(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


async def get_default_model_id(db: AsyncSession, kind: str) -> int | None:
    entry = resolve_kind(kind)
    row = await db.get(SystemSetting, entry.setting_key)
    return _parse_stored_id(row.value if row else None)


async def get_all_default_model_ids(db: AsyncSession) -> dict[str, int | None]:
    return {key: await get_default_model_id(db, key) for key in DEFAULT_MODEL_KIND_KEYS}


async def set_default_model(db: AsyncSession, kind: str, model_id: int) -> AIModel:
    entry = resolve_kind(kind)
    model = await db.get(AIModel, int(model_id))
    if model is None:
        raise SystemDefaultModelError("Model not found")
    await _assert_usable(db, entry, model)
    row = await db.get(SystemSetting, entry.setting_key)
    value = str(int(model.id))
    if row is None:
        db.add(SystemSetting(key=entry.setting_key, value=value))
    else:
        row.value = value
    await db.flush()
    return model


async def clear_default_model(db: AsyncSession, kind: str) -> None:
    entry = resolve_kind(kind)
    row = await db.get(SystemSetting, entry.setting_key)
    if row is None:
        return
    row.value = None
    await db.flush()


async def clear_defaults_if_ids(db: AsyncSession, model_ids) -> None:
    """Clear every kind whose default points at one of these catalog rows."""
    targets = {int(x) for x in model_ids}
    if not targets:
        return
    for key in DEFAULT_MODEL_KIND_KEYS:
        current = await get_default_model_id(db, key)
        if current is not None and int(current) in targets:
            await clear_default_model(db, key)


async def drop_unusable_defaults(db: AsyncSession) -> None:
    """Clear any kind whose model is gone or no longer eligible."""
    for key in DEFAULT_MODEL_KIND_KEYS:
        entry = DEFAULT_MODEL_KINDS[key]
        model_id = await get_default_model_id(db, key)
        if model_id is None:
            continue
        model = await db.get(AIModel, model_id)
        if model is None or not await _is_usable(db, entry, model):
            await clear_default_model(db, key)


async def _is_usable(db: AsyncSession, entry: DefaultModelKind, model: AIModel) -> bool:
    try:
        await _assert_usable(db, entry, model)
    except SystemDefaultModelError:
        return False
    return True


async def _assert_usable(db: AsyncSession, entry: DefaultModelKind, model: AIModel) -> None:
    if not bool(model.is_enabled) or bool(model.admin_disabled):
        raise SystemDefaultModelError("Model must be enabled")
    access = (model.access_type or ACCESS_PUBLIC).strip().lower()
    if access != ACCESS_PUBLIC:
        # Every user falls back to this model, so a private one would break the
        # capability for anyone outside its access list.
        raise SystemDefaultModelError("Model must be public")
    if not entry.supports(model):
        raise SystemDefaultModelError(entry.requirement)
    # Same bar as global_default_transcription_model: a system default is what
    # every user falls back to, so it must be routable right now - a live
    # connection with credentials, not merely a catalog row.
    if model.connection_id is None:
        raise SystemDefaultModelError("Model has no connection")
    conn = await db.get(Connection, model.connection_id)
    if conn is None or not bool(conn.is_active):
        raise SystemDefaultModelError("Model connection must be active")
    if not conn.api_key_encrypted:
        raise SystemDefaultModelError("Model connection has no API key")
