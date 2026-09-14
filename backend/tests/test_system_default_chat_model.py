"""Admin system default for new chats (kind "chat") — never writes UserChatPrefs.

Uses the shared ``db_session`` fixture from conftest.py.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.models.user import User
from app.services.system_default_models import (
    CHAT_SETTING_KEY as SETTING_KEY,
)
from app.services.system_default_models import (
    SystemDefaultModelError,
    clear_defaults_if_ids,
    drop_unusable_defaults,
    get_default_model,
    get_default_model_id,
    set_default_model,
)
from app.services.model_access_service import ACCESS_PRIVATE, ACCESS_PUBLIC
from app.services.user_chat_storage_service import load_user_prefs, save_user_prefs


async def _conn(db: AsyncSession) -> Connection:
    c = Connection(
        name="or",
        provider_type="openrouter",
        api_key_encrypted="enc",
        is_active=True,
    )
    db.add(c)
    await db.flush()
    return c


async def _model(
    db: AsyncSession,
    conn: Connection,
    ext: str,
    *,
    enabled: bool = True,
    access: str = ACCESS_PUBLIC,
    admin_disabled: bool = False,
) -> AIModel:
    m = AIModel(
        connection_id=conn.id,
        external_id=ext,
        display_name=ext,
        provider_type="openrouter",
        is_enabled=enabled,
        admin_disabled=admin_disabled,
        access_type=access,
    )
    db.add(m)
    await db.flush()
    return m


async def _user(db: AsyncSession) -> User:
    u = User(
        username="alice",
        email="alice@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u


async def test_set_and_read(db_session: AsyncSession) -> None:
    db = db_session
    conn = await _conn(db)
    model = await _model(db, conn, "openai/gpt-4o")
    saved = await set_default_model(db, "chat", model.id)
    await db.commit()
    assert int(saved.id) == int(model.id)
    assert await get_default_model_id(db, "chat") == int(model.id)
    loaded = await get_default_model(db, "chat")
    assert loaded is not None
    assert int(loaded.id) == int(model.id)


async def test_rejects_private_disabled_and_non_text(db_session: AsyncSession) -> None:
    db = db_session
    conn = await _conn(db)
    private = await _model(db, conn, "openai/private", access=ACCESS_PRIVATE)
    disabled = await _model(db, conn, "openai/off", enabled=False)
    embed = await _model(db, conn, "openai/text-embedding-3-large")
    embed.pricing_raw = '{"architecture": {"output_modalities": ["embeddings"]}}'
    await db.flush()
    with pytest.raises(SystemDefaultModelError):
        await set_default_model(db, "chat", private.id)
    with pytest.raises(SystemDefaultModelError):
        await set_default_model(db, "chat", disabled.id)
    with pytest.raises(SystemDefaultModelError):
        await set_default_model(db, "chat", embed.id)
    assert await get_default_model_id(db, "chat") is None


async def test_does_not_write_user_prefs(db_session: AsyncSession) -> None:
    db = db_session
    user = await _user(db)
    conn = await _conn(db)
    personal = await _model(db, conn, "openai/gpt-4o-mini")
    system = await _model(db, conn, "openai/gpt-4o")
    await save_user_prefs(db, user.id, {"default_model": f"model::{personal.id}"})
    await db.commit()
    before = await load_user_prefs(db, user.id)
    await set_default_model(db, "chat", system.id)
    await db.commit()
    after = await load_user_prefs(db, user.id)
    assert after["default_model"] == before["default_model"] == f"model::{personal.id}"
    setting = await db.get(SystemSetting, SETTING_KEY)
    assert setting is not None
    assert setting.value == str(int(system.id))


async def test_clear_when_disabled(db_session: AsyncSession) -> None:
    db = db_session
    conn = await _conn(db)
    model = await _model(db, conn, "openai/gpt-4o")
    await set_default_model(db, "chat", model.id)
    await db.commit()
    await clear_defaults_if_ids(db, [model.id])
    await db.commit()
    assert await get_default_model_id(db, "chat") is None


async def test_drop_when_model_becomes_private(db_session: AsyncSession) -> None:
    db = db_session
    conn = await _conn(db)
    model = await _model(db, conn, "openai/gpt-4o")
    await set_default_model(db, "chat", model.id)
    model.access_type = ACCESS_PRIVATE
    await db.flush()
    await drop_unusable_defaults(db)
    await db.commit()
    assert await get_default_model_id(db, "chat") is None
