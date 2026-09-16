"""Sticky admin_disabled semantics for catalog models."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.model_sync import (
    disable_models_for_connection,
    enable_models_for_connection,
    set_model_admin_enabled,
    sync_connection_models,
    sync_connection_with_flash,
)


@pytest.fixture(autouse=True)
def isolate_specialized_openrouter_catalog():
    """These tests exercise generic upsert semantics, not live video catalog data."""
    with (
        patch(
            "app.services.model_sync.fetch_openrouter_video_models",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.services.model_sync.fetch_openrouter_image_models",
            new=AsyncMock(return_value={}),
        ),
    ):
        yield


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _seed_connection(db: AsyncSession, *, name: str = "or", active: bool = True) -> Connection:
    conn = Connection(
        name=name,
        provider_type="openrouter",
        api_key_encrypted="enc-key",
        is_active=active,
    )
    db.add(conn)
    await db.flush()
    return conn


async def _find(db: AsyncSession, external_id: str) -> AIModel | None:
    return (await db.execute(select(AIModel).where(AIModel.external_id == external_id))).scalars().first()


async def _seed_model(
    db: AsyncSession,
    conn: Connection,
    *,
    external_id: str,
    enabled: bool = True,
    admin_disabled: bool = False,
) -> AIModel:
    m = AIModel(
        connection_id=conn.id,
        external_id=external_id,
        display_name=external_id,
        provider_type=conn.provider_type,
        is_enabled=enabled,
        admin_disabled=admin_disabled,
    )
    db.add(m)
    await db.flush()
    return m


async def _test_admin_off_survives_sync() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _seed_connection(db)
        model = await _seed_model(db, conn, external_id="openai/gpt-4o")
        await set_model_admin_enabled(db, model, False)
        await db.commit()

        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "openai/gpt-4o",
                        "name": "GPT-4o",
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                        "context_length": 128000,
                    }
                ]
            ),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()

        refreshed = await db.get(AIModel, model.id)
        assert refreshed is not None
        assert refreshed.admin_disabled is True
        assert refreshed.is_enabled is False
        assert refreshed.display_name == "GPT-4o"
    await engine.dispose()


async def _test_admin_off_survives_connection_enable() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _seed_connection(db, active=False)
        locked = await _seed_model(db, conn, external_id="openai/gpt-4o", enabled=False, admin_disabled=True)
        unlocked = await _seed_model(db, conn, external_id="openai/gpt-4o-mini", enabled=False, admin_disabled=False)
        await db.commit()

        conn.is_active = True
        count = await enable_models_for_connection(db, conn.id)
        await db.commit()

        assert count == 1
        await db.refresh(locked)
        await db.refresh(unlocked)
        assert locked.is_enabled is False
        assert locked.admin_disabled is True
        assert unlocked.is_enabled is True
        assert unlocked.admin_disabled is False
    await engine.dispose()


async def _test_admin_on_respects_connection_active() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _seed_connection(db, active=True)
        model = await _seed_model(db, conn, external_id="openai/gpt-4o", enabled=False, admin_disabled=True)
        await set_model_admin_enabled(db, model, True)
        await db.commit()
        await db.refresh(model)
        assert model.admin_disabled is False
        assert model.is_enabled is True

        conn.is_active = False
        await db.commit()
        model2 = await _seed_model(db, conn, external_id="openai/o1", enabled=False, admin_disabled=True)
        await set_model_admin_enabled(db, model2, True)
        await db.commit()
        await db.refresh(model2)
        assert model2.admin_disabled is False
        assert model2.is_enabled is False
    await engine.dispose()


async def _test_bulk_off_sticky() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _seed_connection(db)
        a = await _seed_model(db, conn, external_id="a")
        b = await _seed_model(db, conn, external_id="b")
        await db.commit()
        for m in (a, b):
            await set_model_admin_enabled(db, m, False)
        await db.commit()
        rows = (await db.execute(select(AIModel).where(AIModel.connection_id == conn.id))).scalars().all()
        assert all(r.admin_disabled and not r.is_enabled for r in rows)
    await engine.dispose()


async def _test_sync_flash_does_not_touch_other_connection() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn_a = await _seed_connection(db, name="a")
        conn_b = await _seed_connection(db, name="b")
        other = await _seed_model(db, conn_b, external_id="other/model", enabled=False, admin_disabled=True)
        await _seed_model(db, conn_a, external_id="openai/gpt-4o")
        await db.commit()

        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "openai/gpt-4o",
                        "name": "GPT-4o",
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    }
                ]
            ),
        ):
            result = await sync_connection_with_flash(db, conn_a, "sk-test")
            await db.commit()

        assert result["synced"] == 1
        await db.refresh(other)
        assert other.is_enabled is False
        assert other.admin_disabled is True
    await engine.dispose()


async def _test_new_model_from_sync_defaults() -> None:
    """A model the provider just added is not in service until someone says so."""
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _seed_connection(db, active=True)
        await db.commit()
        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "openai/new-model",
                        "name": "New",
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    }
                ]
            ),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()

        row = await _find(db, "openai/new-model")
        assert row is not None
        # Off even though the connection is active: the provider adding a model
        # is not a decision this organization has made.
        assert row.is_enabled is False
        # And locked, or the next connection toggle would quietly enable it.
        assert row.admin_disabled is True
    await engine.dispose()


async def _test_new_model_stays_off_across_a_connection_toggle() -> None:
    """The hazard the lock exists for.

    `enable_models_for_connection` switches on everything that is not locked, so
    an unapproved model recorded only as `is_enabled=False` would go live the
    first time an administrator disabled and re-enabled the connection.
    """
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _seed_connection(db, active=True)
        approved = await _seed_model(db, conn, external_id="openai/approved")
        await db.commit()

        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(
                return_value=[
                    {"id": "openai/approved", "name": "Approved", "pricing": {}},
                    {"id": "openai/brand-new", "name": "Brand new", "pricing": {}},
                ]
            ),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()

        conn.is_active = False
        await disable_models_for_connection(db, conn.id)
        await db.commit()
        conn.is_active = True
        await enable_models_for_connection(db, conn.id)
        await db.commit()

        await db.refresh(approved)
        assert approved.is_enabled is True, "an approved model comes back with the connection"

        brand_new = await _find(db, "openai/brand-new")
        assert brand_new is not None
        assert brand_new.is_enabled is False, "an unapproved model must not ride in on a connection toggle"
        assert brand_new.admin_disabled is True
    await engine.dispose()


async def _test_approving_a_new_model_is_one_action() -> None:
    """Turning it ON is the approval — no separate unlock step."""
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = await _seed_connection(db, active=True)
        await db.commit()
        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(return_value=[{"id": "openai/fresh", "name": "Fresh", "pricing": {}}]),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()

        fresh = await _find(db, "openai/fresh")
        assert fresh is not None
        await set_model_admin_enabled(db, fresh, True)
        await db.commit()
        await db.refresh(fresh)
        assert fresh.is_enabled is True
        assert fresh.admin_disabled is False

        # And a later sync leaves that decision alone.
        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(return_value=[{"id": "openai/fresh", "name": "Fresh v2", "pricing": {}}]),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()
        await db.refresh(fresh)
        assert fresh.is_enabled is True
        assert fresh.display_name == "Fresh v2"
    await engine.dispose()


async def test_admin_off_survives_sync():
    await _test_admin_off_survives_sync()


async def test_admin_off_survives_connection_enable():
    await _test_admin_off_survives_connection_enable()


async def test_admin_on_respects_connection_active():
    await _test_admin_on_respects_connection_active()


async def test_bulk_off_sticky():
    await _test_bulk_off_sticky()


async def test_sync_flash_does_not_touch_other_connection():
    await _test_sync_flash_does_not_touch_other_connection()


async def test_new_model_from_sync_defaults():
    await _test_new_model_from_sync_defaults()


async def test_new_model_stays_off_across_a_connection_toggle():
    await _test_new_model_stays_off_across_a_connection_toggle()


async def test_approving_a_new_model_is_one_action():
    await _test_approving_a_new_model_is_one_action()
