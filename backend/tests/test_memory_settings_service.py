"""Admin memory settings defaults and validation."""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.memory_settings_service import (
    PROJECT_DENIED_CATEGORIES,
    PROJECT_MEMORY_CATEGORIES,
    MemorySettingsError,
    get_memory_settings,
    parse_memory_settings,
    update_memory_settings,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


def test_parse_defaults() -> None:
    parsed = parse_memory_settings({})
    assert parsed["feature_enabled"] is True
    assert parsed["extraction_model_id"] is None
    assert parsed["max_per_user"] == 200
    assert parsed["allowed_sensitive_categories"] == ["health", "financial"]
    assert parsed["inject_max_items"] == 12


def test_project_defaults_match_the_previous_manual_caps() -> None:
    parsed = parse_memory_settings({})
    assert parsed["project_feature_enabled"] is True
    assert parsed["project_max_per_project"] == 500
    assert parsed["project_inject_max_items"] == 60
    assert parsed["project_inject_max_chars"] == 8000
    assert parsed["project_extract_min_new_messages"] == 2


def test_project_denied_categories_are_not_admin_configurable() -> None:
    # The deny list is a hard gate in project scope; the admin allow-list above
    # cannot re-open any of these categories for a shared team memory.
    assert {"health", "financial", "personal"} <= set(PROJECT_DENIED_CATEGORIES)
    assert not (set(PROJECT_MEMORY_CATEGORIES) & set(PROJECT_DENIED_CATEGORIES))


async def _project_settings_round_trip() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        saved = await update_memory_settings(
            db,
            {
                "project_feature_enabled": False,
                "project_max_per_project": 120,
                "project_inject_max_items": 20,
                "project_manual_items": 5,
                "project_min_similarity": 0.4,
            },
        )
        assert saved["project_feature_enabled"] is False
        assert saved["project_max_per_project"] == 120
        assert saved["project_inject_max_items"] == 20
        assert saved["project_manual_items"] == 5
        assert abs(saved["project_min_similarity"] - 0.4) < 1e-9
        # User-scope settings are untouched by a project-only patch.
        assert saved["feature_enabled"] is True
        assert saved["max_per_user"] == 200

        reloaded = await get_memory_settings(db)
        assert reloaded["project_feature_enabled"] is False
        assert reloaded["project_max_per_project"] == 120

        # Out-of-range values clamp instead of failing the whole patch.
        clamped = await update_memory_settings(db, {"project_max_per_project": 5})
        assert clamped["project_max_per_project"] == 10
    await engine.dispose()


def test_project_memory_settings_round_trip() -> None:
    asyncio.run(_project_settings_round_trip())


async def _defaults_and_validation() -> None:
    factory, engine = await _session_factory()
    async with factory() as db:
        settings = await get_memory_settings(db)
        assert settings["feature_enabled"] is True
        assert settings["extraction_model_id"] is None
        assert settings["embedding_model"] == ""

        try:
            await update_memory_settings(db, {"extraction_model_id": 99999})
            assert False, "expected missing model"
        except MemorySettingsError:
            pass

        conn = Connection(
            name="local",
            provider_type="openai",
            api_key_encrypted="enc",
            is_active=True,
        )
        db.add(conn)
        await db.flush()
        disabled = AIModel(
            connection_id=conn.id,
            external_id="gpt-4o-mini",
            display_name="mini",
            provider_type="openai",
            is_enabled=False,
        )
        db.add(disabled)
        await db.flush()
        try:
            await update_memory_settings(db, {"extraction_model_id": disabled.id})
            assert False, "expected disabled model"
        except MemorySettingsError:
            pass

        enabled = AIModel(
            connection_id=conn.id,
            external_id="gpt-4o-mini-enabled",
            display_name="mini-on",
            provider_type="openai",
            is_enabled=True,
        )
        db.add(enabled)
        await db.flush()
        saved = await update_memory_settings(
            db,
            {
                "extraction_model_id": enabled.id,
                "max_per_user": 50,
                "allowed_sensitive_categories": ["health"],
            },
        )
        assert saved["extraction_model_id"] == enabled.id
        assert saved["max_per_user"] == 50
        assert saved["allowed_sensitive_categories"] == ["health"]

        try:
            await update_memory_settings(db, {"embedding_model": "not-a-spec"})
            assert False, "expected embedding spec error"
        except MemorySettingsError:
            pass

        try:
            await update_memory_settings(db, {"not_a_real_key": True})
            assert False, "expected unknown setting"
        except MemorySettingsError:
            pass

        cleared = await update_memory_settings(db, {"extraction_model_id": None})
        assert cleared["extraction_model_id"] is None

        from app.services.secret_crypto import encrypt_secret

        embed_conn = Connection(
            name="embed",
            provider_type="openai",
            api_key_encrypted=encrypt_secret("sk-test"),
            is_active=True,
        )
        db.add(embed_conn)
        await db.flush()
        embed_model = AIModel(
            connection_id=embed_conn.id,
            external_id="text-embedding-3-small",
            display_name="emb",
            provider_type="openai",
            is_enabled=True,
        )
        db.add(embed_model)
        await db.flush()

        filled = await update_memory_settings(db, {"embedding_model": "openai:text-embedding-3-small"})
        assert filled["embedding_model"] == "openai:text-embedding-3-small"
        assert filled["embedding_dimensions"] == 1536

        overridden = await update_memory_settings(db, {"embedding_dimensions": 512})
        assert overridden["embedding_dimensions"] == 512
    await engine.dispose()


def test_memory_settings_defaults_and_validation() -> None:
    asyncio.run(_defaults_and_validation())
