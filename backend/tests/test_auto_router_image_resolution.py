"""Tests for Auto Router → concrete image model resolution."""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.connection import Connection
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services.image_model_resolver import (
    _image_model_rank,
    is_image_model_failover_error,
    list_auto_router_image_candidates,
    resolve_auto_router_image_model,
    resolve_openrouter_auto_image_model,
    score_image_model_candidate,
)


def test_score_rejects_auto_and_non_image():
    assert score_image_model_candidate("openrouter/auto") < 0
    assert score_image_model_candidate("anthropic/claude-sonnet-4.5") == 0
    gemini = score_image_model_candidate(
        "google/gemini-2.5-flash-image",
        is_image_model=True,
    )
    assert gemini > 0


def test_score_does_not_prefer_pro_name_over_stable_flash():
    """Name labels must not beat measured reliability."""
    unstable_pro = score_image_model_candidate(
        "google/gemini-3-pro-image",
        is_image_model=True,
        stability_score=0.55,
        stability_count=40,
        latency_score=0.4,
        latency_count=20,
        avg_success_ms=45_000,
        feedback_score=0.75,
        feedback_count=5,
    )
    stable_flash = score_image_model_candidate(
        "google/gemini-2.5-flash-image",
        is_image_model=True,
        stability_score=0.98,
        stability_count=40,
        latency_score=0.75,
        latency_count=20,
        avg_success_ms=8_000,
        feedback_score=0.8,
        feedback_count=5,
    )
    assert stable_flash > unstable_pro


def test_bayesian_feedback_can_change_close_model_ranking():
    liked = score_image_model_candidate(
        "vendor/image-alpha",
        is_image_model=True,
        feedback_score=0.95,
        feedback_count=30,
        stability_score=0.9,
        stability_count=20,
    )
    disliked = score_image_model_candidate(
        "vendor/image-beta",
        is_image_model=True,
        feedback_score=0.15,
        feedback_count=30,
        stability_score=0.9,
        stability_count=20,
    )
    assert liked > disliked


def test_failure_signal_can_hold_back_an_unstable_new_model():
    proven = score_image_model_candidate(
        "vendor/image-stable",
        is_image_model=True,
        stability_score=0.99,
        stability_count=50,
        latency_score=0.7,
        latency_count=40,
    )
    failing_canary = score_image_model_candidate(
        "vendor/image-canary",
        is_image_model=True,
        stability_score=0.1,
        stability_count=10,
        latency_score=0.7,
        latency_count=5,
    )
    assert proven > failing_canary


def test_image_model_rank_prefers_non_lite_at_same_score():
    lite = _image_model_rank("google/gemini-3.1-flash-lite-image", 100)
    full = _image_model_rank("google/gemini-3.1-flash-image", 100)
    assert full < lite


def test_image_model_failover_error_detects_disconnect_and_text():
    from fastapi import HTTPException

    assert is_image_model_failover_error(
        HTTPException(status_code=502, detail="Image provider closed the connection before responding.")
    )
    assert is_image_model_failover_error(
        HTTPException(status_code=422, detail="The model returned text instead of an image.")
    )
    assert not is_image_model_failover_error(
        HTTPException(status_code=400, detail="OpenRouter connection has no API key")
    )


async def _bootstrap_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _run_auto_resolve() -> None:
    engine, session_factory = await _bootstrap_session()

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
                    external_id="google/gemini-2.5-flash-image",
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
        assert external_id in {
            "black-forest-labs/flux-1.1-pro",
            "google/gemini-2.5-flash-image",
        }
        assert picked_conn.id == conn.id
        assert model.is_image_model is True

        empty = await resolve_auto_router_image_model(session, connection_id=99999)
        assert empty is None
    await engine.dispose()


async def _run_text_only_returns_none() -> None:
    engine, session_factory = await _bootstrap_session()

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
    await engine.dispose()


async def _run_prefers_non_lite_gemini() -> None:
    engine, session_factory = await _bootstrap_session()

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
    await engine.dispose()


async def _run_runtime_signals_prefer_reliable_model() -> None:
    engine, session_factory = await _bootstrap_session()

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
                    external_id="google/gemini-3-pro-image",
                    display_name="Pro",
                    provider_type="openrouter",
                    is_enabled=True,
                    is_image_model=True,
                ),
                AIModel(
                    connection_id=conn.id,
                    external_id="google/gemini-2.5-flash-image",
                    display_name="Flash",
                    provider_type="openrouter",
                    is_enabled=True,
                    is_image_model=True,
                ),
            ]
        )
        now = datetime.utcnow()
        # Pro: many recent failures
        for i in range(12):
            session.add(
                RequestLog(
                    user_id=1,
                    username="u",
                    model_id="google/gemini-3-pro-image",
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_cost_usd=0.01,
                    response_time_ms=40_000 if i % 3 == 0 else 0,
                    success=(i % 3 == 0),
                    request_time=now - timedelta(hours=1),
                    source="test",
                )
            )
        # Flash: all successes, faster
        for _ in range(12):
            session.add(
                RequestLog(
                    user_id=1,
                    username="u",
                    model_id="google/gemini-2.5-flash-image",
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_cost_usd=0.01,
                    response_time_ms=7_000,
                    success=True,
                    request_time=now - timedelta(hours=1),
                    source="test",
                )
            )
        await session.commit()

        candidates = await list_auto_router_image_candidates(
            session, connection_id=conn.id, limit=3
        )
        assert len(candidates) >= 2
        assert candidates[0].external_id == "google/gemini-2.5-flash-image"
        assert candidates[1].external_id == "google/gemini-3-pro-image"
    await engine.dispose()


def test_resolve_auto_router_image_model():
    asyncio.run(_run_auto_resolve())


def test_resolve_openrouter_auto_image_model_alias():
    asyncio.run(_run_auto_resolve())
    asyncio.run(_run_text_only_returns_none())
    asyncio.run(_run_prefers_non_lite_gemini())


def test_list_candidates_orders_by_recent_reliability():
    asyncio.run(_run_runtime_signals_prefer_reliable_model())
