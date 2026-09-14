"""Admin system default for new chats — never writes UserChatPrefs."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.system import SystemSetting
from app.models.user import User
from app.services.global_default_chat_model import (
    SETTING_KEY,
    GlobalDefaultModelError,
    clear_global_default_if_ids,
    drop_unusable_global_default,
    get_global_default_model,
    get_global_default_model_id,
    set_global_default_model,
)
from app.services.model_access_service import ACCESS_PRIVATE, ACCESS_PUBLIC
from app.services.user_chat_storage_service import load_user_prefs, save_user_prefs


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


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


async def _test_set_and_read() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _conn(db)
        model = await _model(db, conn, "openai/gpt-4o")
        saved = await set_global_default_model(db, model.id)
        await db.commit()
        assert int(saved.id) == int(model.id)
        assert await get_global_default_model_id(db) == int(model.id)
        loaded = await get_global_default_model(db)
        assert loaded is not None
        assert int(loaded.id) == int(model.id)
    await engine.dispose()


async def _test_rejects_private_disabled_and_non_text() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _conn(db)
        private = await _model(db, conn, "openai/private", access=ACCESS_PRIVATE)
        disabled = await _model(db, conn, "openai/off", enabled=False)
        embed = await _model(db, conn, "openai/text-embedding-3-large")
        embed.pricing_raw = '{"architecture": {"output_modalities": ["embeddings"]}}'
        await db.flush()
        try:
            await set_global_default_model(db, private.id)
            raise AssertionError("private model should be rejected")
        except GlobalDefaultModelError:
            pass
        try:
            await set_global_default_model(db, disabled.id)
            raise AssertionError("disabled model should be rejected")
        except GlobalDefaultModelError:
            pass
        try:
            await set_global_default_model(db, embed.id)
            raise AssertionError("embeddings model should be rejected")
        except GlobalDefaultModelError:
            pass
        assert await get_global_default_model_id(db) is None
    await engine.dispose()


async def _test_does_not_write_user_prefs() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        user = await _user(db)
        conn = await _conn(db)
        personal = await _model(db, conn, "openai/gpt-4o-mini")
        system = await _model(db, conn, "openai/gpt-4o")
        await save_user_prefs(db, user.id, {"default_model": f"model::{personal.id}"})
        await db.commit()
        before = await load_user_prefs(db, user.id)
        await set_global_default_model(db, system.id)
        await db.commit()
        after = await load_user_prefs(db, user.id)
        assert after["default_model"] == before["default_model"] == f"model::{personal.id}"
        setting = await db.get(SystemSetting, SETTING_KEY)
        assert setting is not None
        assert setting.value == str(int(system.id))
    await engine.dispose()


async def _test_clear_when_disabled() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _conn(db)
        model = await _model(db, conn, "openai/gpt-4o")
        await set_global_default_model(db, model.id)
        await db.commit()
        await clear_global_default_if_ids(db, [model.id])
        await db.commit()
        assert await get_global_default_model_id(db) is None
    await engine.dispose()


async def _test_drop_when_model_becomes_private() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _conn(db)
        model = await _model(db, conn, "openai/gpt-4o")
        await set_global_default_model(db, model.id)
        model.access_type = ACCESS_PRIVATE
        await db.flush()
        await drop_unusable_global_default(db)
        await db.commit()
        assert await get_global_default_model_id(db) is None
    await engine.dispose()


async def test_set_and_read():
    await _test_set_and_read()


async def test_rejects_private_disabled_and_non_text():
    await _test_rejects_private_disabled_and_non_text()


async def test_does_not_write_user_prefs():
    await _test_does_not_write_user_prefs()


async def test_clear_when_disabled():
    await _test_clear_when_disabled()


async def test_drop_when_model_becomes_private():
    await _test_drop_when_model_becomes_private()
