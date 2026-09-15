"""Admin-selected system default for new chats.

Stored in system_settings. Never written into UserChatPrefs — users who already
chose a personal default_model keep it.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.services.model_access_service import ACCESS_PUBLIC
from app.services.model_capabilities import model_kinds, model_media_flags
from app.services.model_tool_compatibility_service import is_auto_router_model_id

SETTING_KEY = "global_default_chat_model_id"


class GlobalDefaultModelError(ValueError):
    """Raised when the catalog model cannot be used as the system default."""


def chat_model_id(catalog_id: int) -> str:
    return f"model::{int(catalog_id)}"


def parse_stored_id(value: str | None) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def model_supports_text_chat(model: AIModel) -> bool:
    if is_auto_router_model_id(model.external_id):
        return True
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
    if not kinds:
        return True
    return "text" in kinds


async def get_global_default_model_id(db: AsyncSession) -> int | None:
    row = await db.get(SystemSetting, SETTING_KEY)
    return parse_stored_id(row.value if row else None)


async def get_global_default_model(db: AsyncSession) -> AIModel | None:
    model_id = await get_global_default_model_id(db)
    if model_id is None:
        return None
    model = await db.get(AIModel, model_id)
    if model is None:
        return None
    if not await _is_usable_system_default(db, model):
        return None
    return model


async def set_global_default_model(db: AsyncSession, model_id: int) -> AIModel:
    model = await db.get(AIModel, int(model_id))
    if model is None:
        raise GlobalDefaultModelError("Model not found")
    await _assert_usable_system_default(db, model)
    row = await db.get(SystemSetting, SETTING_KEY)
    value = str(int(model.id))
    if row is None:
        db.add(SystemSetting(key=SETTING_KEY, value=value))
    else:
        row.value = value
    await db.flush()
    return model


async def clear_global_default_model(db: AsyncSession) -> None:
    row = await db.get(SystemSetting, SETTING_KEY)
    if row is None:
        return
    row.value = None
    await db.flush()


async def clear_global_default_if_ids(db: AsyncSession, model_ids: list[int] | set[int]) -> None:
    current = await get_global_default_model_id(db)
    if current is None:
        return
    if int(current) in {int(x) for x in model_ids}:
        await clear_global_default_model(db)


async def drop_unusable_global_default(db: AsyncSession) -> None:
    """Clear the setting when the pointed-to model is gone or no longer eligible."""
    model_id = await get_global_default_model_id(db)
    if model_id is None:
        return
    model = await db.get(AIModel, model_id)
    if model is None or not await _is_usable_system_default(db, model):
        await clear_global_default_model(db)


async def _is_usable_system_default(db: AsyncSession, model: AIModel) -> bool:
    try:
        await _assert_usable_system_default(db, model)
    except GlobalDefaultModelError:
        return False
    return True


async def _assert_usable_system_default(db: AsyncSession, model: AIModel) -> None:
    if not bool(model.is_enabled) or bool(model.admin_disabled):
        raise GlobalDefaultModelError("Model must be enabled")
    access = (model.access_type or ACCESS_PUBLIC).strip().lower()
    if access != ACCESS_PUBLIC:
        raise GlobalDefaultModelError("Model must be public")
    if not model_supports_text_chat(model):
        raise GlobalDefaultModelError("Model must support text chat")
    if model.connection_id is not None:
        conn = await db.get(Connection, model.connection_id)
        if conn is None or not bool(conn.is_active):
            raise GlobalDefaultModelError("Model connection must be active")
