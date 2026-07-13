"""Tests for Auto Router → concrete image model resolution."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.image_model_resolver import (
    _image_model_rank,
    resolve_auto_router_image_model,
    resolve_openrouter_auto_image_model,
    score_image_model_candidate,
)


def test_score_image_model_candidate_is_quality_first():
    auto = score_image_model_candidate("openrouter/auto")
    gemini = score_image_model_candidate(
        "google/gemini-2.5-flash-image-preview",
        is_image_model=True,
    )
    flux = score_image_model_candidate("black-forest-labs/flux-1.1-pro", is_image_model=True)
    text = score_image_model_candidate("anthropic/claude-sonnet-4.5")

    assert auto < 0
    assert flux > gemini > 0
    assert text == 0


def test_score_prefers_newer_model_at_same_quality_tier():
    old = score_image_model_candidate("vendor/image-2.0-pro", is_image_model=True)
    new = score_image_model_candidate("vendor/image-4.0-pro", is_image_model=True)
    assert new > old


def test_bayesian_feedback_can_change_close_model_ranking():
    liked = score_image_model_candidate(
        "vendor/image-2.0-pro",
        is_image_model=True,
        feedback_score=0.95,
        feedback_count=30,
    )
    disliked = score_image_model_candidate(
        "vendor/image-3.0-pro",
        is_image_model=True,
        feedback_score=0.15,
        feedback_count=30,
    )
    assert liked > disliked


def test_failure_signal_can_hold_back_an_unstable_new_model():
    proven = score_image_model_candidate(
        "vendor/image-2.0-pro",
        is_image_model=True,
        stability_score=0.99,
        stability_count=50,
    )
    failing_canary = score_image_model_candidate(
        "vendor/image-3.0-pro",
        is_image_model=True,
        stability_score=0.1,
        stability_count=10,
    )
    assert proven > failing_canary


def test_image_model_rank_prefers_non_lite_at_same_score():
    lite = _image_model_rank("google/gemini-3.1-flash-lite-image", 100)
    full = _image_model_rank("google/gemini-3.1-flash-image", 100)
    assert full < lite


async def _run_auto_resolve() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        conn = Connection(
            name="OR",
            provider_type="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_encrypted="secret",
            is_active=True,
        )
        session.add(conn)
        await session.flush()

        session.add_all(
            [
                AIModel(
                    connection_id=conn.id,
                    external_id="openrouter/auto",
                    display_name="Auto Router",
                    provider_type="openrouter",
                    is_enabled=True,
                ),
                AIModel(
                    connection_id=conn.id,
                    external_id="black-forest-labs/flux-1.1-pro",
                    display_name="Flux",
                    provider_type="openrouter",
                    is_enabled=True,
                    is_image_model=True,
                ),
                AIModel(
                    connection_id=conn.id,
                    external_id="google/gemini-2.5-flash-image-preview",
                    display_name="Gemini Image",
                    provider_type="openrouter",
                    is_enabled=True,
                    is_image_model=True,
                ),
            ]
        )
        await session.commit()

        picked = await resolve_auto_router_image_model(session, connection_id=conn.id)
        assert picked is not None
        external_id, model, picked_conn = picked
        assert external_id == "black-forest-labs/flux-1.1-pro"
        assert model.display_name == "Flux"
        assert picked_conn.id == conn.id

        empty = await resolve_auto_router_image_model(session, connection_id=99999)
        assert empty is None


async def _run_text_only_returns_none() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        conn = Connection(
            name="OR",
            provider_type="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_encrypted="secret",
            is_active=True,
        )
        session.add(conn)
        await session.flush()
        session.add_all(
            [
                AIModel(
                    connection_id=conn.id,
                    external_id="openrouter/auto",
                    display_name="Auto Router",
                    provider_type="openrouter",
                    is_enabled=True,
                ),
                AIModel(
                    connection_id=conn.id,
                    external_id="anthropic/claude-sonnet-4.5",
                    display_name="Claude",
                    provider_type="openrouter",
                    is_enabled=True,
                ),
            ]
        )
        await session.commit()

        assert await resolve_auto_router_image_model(session, connection_id=conn.id) is None


async def _run_prefers_non_lite_gemini() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        conn = Connection(
            name="OR",
            provider_type="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_encrypted="secret",
            is_active=True,
        )
        session.add(conn)
        await session.flush()
        session.add_all(
            [
                AIModel(
                    connection_id=conn.id,
                    external_id="google/gemini-3.1-flash-lite-image",
                    display_name="Lite",
                    provider_type="openrouter",
                    is_enabled=True,
                    is_image_model=True,
                ),
                AIModel(
                    connection_id=conn.id,
                    external_id="google/gemini-3.1-flash-image",
                    display_name="Full",
                    provider_type="openrouter",
                    is_enabled=True,
                    is_image_model=True,
                ),
            ]
        )
        await session.commit()

        picked = await resolve_auto_router_image_model(session, connection_id=conn.id)
        assert picked is not None
        assert picked[0] == "google/gemini-3.1-flash-image"


def test_resolve_auto_router_image_model():
    asyncio.run(_run_auto_resolve())


def test_resolve_openrouter_auto_image_model_alias():
    asyncio.run(_run_auto_resolve())
    asyncio.run(_run_text_only_returns_none())
    asyncio.run(_run_prefers_non_lite_gemini())
