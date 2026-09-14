"""first_seen_at is set on first catalog insert and survives later syncs."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.model_sync import sync_connection_models


@pytest.fixture(autouse=True)
def isolate_specialized_openrouter_catalog():
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


def _catalog_item(model_id: str, name: str | None = None) -> dict:
    return {
        "id": model_id,
        "name": name or model_id,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
        "context_length": 128000,
    }


async def _test_new_model_records_first_seen_and_keeps_it() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = Connection(
            name="or",
            provider_type="openrouter",
            api_key_encrypted="enc-key",
            is_active=True,
        )
        db.add(conn)
        await db.flush()

        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(return_value=[_catalog_item("openai/gpt-4o", "GPT-4o")]),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()

        created = (await db.execute(select(AIModel).where(AIModel.external_id == "openai/gpt-4o"))).scalars().first()
        assert created is not None
        assert created.first_seen_at is not None
        first_seen = created.first_seen_at
        created.first_seen_at = first_seen - timedelta(days=2)
        await db.commit()
        pinned = created.first_seen_at

        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(return_value=[_catalog_item("openai/gpt-4o", "GPT-4o Updated")]),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()

        await db.refresh(created)
        assert created.display_name == "GPT-4o Updated"
        assert created.first_seen_at == pinned
        assert created.last_synced_at is not None
        assert created.last_synced_at != pinned
    await engine.dispose()


async def _test_existing_null_first_seen_stays_null() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        conn = Connection(
            name="or",
            provider_type="openrouter",
            api_key_encrypted="enc-key",
            is_active=True,
        )
        db.add(conn)
        await db.flush()
        model = AIModel(
            connection_id=conn.id,
            external_id="openai/gpt-4o",
            display_name="openai/gpt-4o",
            provider_type="openrouter",
            is_enabled=True,
            first_seen_at=None,
        )
        db.add(model)
        await db.commit()

        with patch(
            "app.services.model_sync.fetch_openrouter_models",
            new=AsyncMock(return_value=[_catalog_item("openai/gpt-4o", "GPT-4o")]),
        ):
            await sync_connection_models(db, conn, "sk-test")
            await db.commit()

        await db.refresh(model)
        assert model.display_name == "GPT-4o"
        assert model.first_seen_at is None
    await engine.dispose()


def test_new_model_records_first_seen_and_keeps_it():
    asyncio.run(_test_new_model_records_first_seen_and_keeps_it())


def test_existing_null_first_seen_stays_null():
    asyncio.run(_test_existing_null_first_seen_stays_null())
