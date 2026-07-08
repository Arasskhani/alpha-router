"""Tests for image generation API Logs + budget accounting."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.budget_service import get_month_usage
from app.services.image_billing_service import (
    ImageBillingCapture,
    compute_image_cost_usd,
    log_image_usage,
    usage_from_provider_payload,
)


def test_usage_from_openrouter_json():
    payload = {
        "usage": {
            "prompt_tokens": 42,
            "completion_tokens": 128,
            "prompt_tokens_details": {"cached_tokens": 10},
        }
    }
    pt, ct, cache = usage_from_provider_payload(payload)
    assert pt == 42
    assert ct == 128
    assert cache == 10


def test_usage_from_empty_payload():
    assert usage_from_provider_payload(None) == (0, 0, 0)
    assert usage_from_provider_payload({}) == (0, 0, 0)


def test_compute_image_cost_with_catalog_rates():
    model = SimpleNamespace(
        input_cost_per_1k=0.001,
        output_cost_per_1k=0.002,
        provider_type="openrouter",
    )
    cost = compute_image_cost_usd(
        model,
        model_id="google/gemini-2.5-flash-image-preview",
        provider_type="openrouter",
        prompt="a red cube",
        prompt_tokens=1000,
        completion_tokens=500,
    )
    assert cost == pytest.approx(0.002)


async def _test_log_image_usage_writes_request_log_and_budget() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        user = User(
            username="imguser",
            email="imguser@test",
            hashed_password="x",
            role="user",
            auth_provider="local",
            monthly_budget_usd=10.0,
        )
        db.add(user)
        await db.flush()
        ai_model = AIModel(
            connection_id=1,
            external_id="google/gemini-2.5-flash-image-preview",
            display_name="Gemini Image",
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            is_enabled=True,
        )
        capture = ImageBillingCapture(
            model_id="google/gemini-2.5-flash-image-preview",
            ai_model=ai_model,
            provider_type="openrouter",
            usage_source={
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "prompt_tokens_details": {}}
            },
        )
        await log_image_usage(
            db,
            user=user,
            capture=capture,
            prompt="sunset over mountains",
            response_time_ms=1234.5,
            success=True,
            source_ip="127.0.0.1",
            operation="generation",
        )
        await db.commit()

        row = (await db.execute(select(RequestLog))).scalar_one()
        assert row.username == "imguser"
        assert row.user_id == user.id
        assert row.model_id == "google/gemini-2.5-flash-image-preview"
        assert row.source == "nitro_chat"
        assert row.client_app == "NITRO Chat (image:generation)"
        assert row.prompt_tokens == 1000
        assert row.completion_tokens == 500
        assert row.success is True
        assert row.total_cost_usd == pytest.approx(0.002)

        usage = await get_month_usage(db, user.id)
        assert usage == pytest.approx(0.002)

        count = (await db.execute(select(func.count()).select_from(RequestLog))).scalar_one()
        assert count == 1


def test_log_image_usage_writes_request_log_and_budget():
    asyncio.run(_test_log_image_usage_writes_request_log_and_budget())


async def _test_log_image_usage_failure_row() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        user = User(
            username="imgfail",
            email="imgfail@test",
            hashed_password="x",
            role="user",
            auth_provider="local",
        )
        db.add(user)
        await db.flush()
        capture = ImageBillingCapture(model_id="flux/test")
        await log_image_usage(
            db,
            user=user,
            capture=capture,
            prompt="test",
            response_time_ms=50.0,
            success=False,
            error_message="provider timeout",
            operation="img2img",
        )
        await db.commit()
        row = (await db.execute(select(RequestLog))).scalar_one()
        assert row.success is False
        assert row.error_message == "provider timeout"
        assert row.client_app == "NITRO Chat (image:img2img)"
        assert row.total_cost_usd == 0.0


def test_log_image_usage_failure_row():
    asyncio.run(_test_log_image_usage_failure_row())
