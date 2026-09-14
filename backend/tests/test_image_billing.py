"""Tests for image generation API Logs + budget accounting."""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.cost_accounting import UsageEvent
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
            usage_source={"usage": {"prompt_tokens": 1000, "completion_tokens": 500, "prompt_tokens_details": {}}},
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
        assert row.source == "alpha_router_chat"
        assert row.client_app == "Alpharouter Chat (image:generation)"
        assert row.prompt_tokens == 1000
        assert row.completion_tokens == 500
        assert row.success is True
        assert row.total_cost_usd == pytest.approx(0.002)

        usage = await get_month_usage(db, user.id)
        assert usage == pytest.approx(0.002)

        count = (await db.execute(select(func.count()).select_from(RequestLog))).scalar_one()
        assert count == 1


async def test_log_image_usage_writes_request_log_and_budget():
    await _test_log_image_usage_writes_request_log_and_budget()


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
        assert row.client_app == "Alpharouter Chat (image:img2img)"
        assert row.total_cost_usd == 0.0


async def test_log_image_usage_failure_row():
    await _test_log_image_usage_failure_row()


async def _test_image_attempts_keep_individual_outcomes_and_quantities() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        user = User(
            username="img-attempts",
            email="img-attempts@test",
            hashed_password="x",
            auth_provider="local",
            monthly_budget_usd=10.0,
        )
        db.add(user)
        await db.flush()
        capture = ImageBillingCapture(
            model_id="provider/image-model",
            ai_model=SimpleNamespace(
                external_id="provider/image-model",
                provider_type="openrouter",
                connection_id=None,
                input_cost_per_1k=None,
                output_cost_per_1k=None,
                pricing_raw=None,
            ),
            provider_type="openrouter",
        )
        capture.add_usage(
            {"id": "failed-attempt", "usage": {}},
            success=False,
            error_message="empty image response",
        )
        capture.add_usage(
            {"id": "successful-attempt", "usage": {"cost": 0.2}},
            success=True,
            quantity=2,
        )

        await log_image_usage(
            db,
            user=user,
            capture=capture,
            prompt="two images",
            response_time_ms=100,
            success=True,
            quantity=4,
        )
        await db.commit()

        events = (await db.execute(select(UsageEvent).order_by(UsageEvent.attempt_index))).scalars().all()
        log_row = (await db.execute(select(RequestLog))).scalar_one()
        assert [(event.status, event.quantity) for event in events] == [
            ("failed", None),
            ("succeeded", 2.0),
        ]
        assert events[0].error_message == "empty image response"
        assert float(events[1].final_cost_usd) == pytest.approx(0.2)
        assert log_row.total_cost_usd == pytest.approx(0.2)
        assert log_row.has_unpriced_usage is True

    await engine.dispose()


async def test_image_attempts_keep_individual_outcomes_and_quantities():
    await _test_image_attempts_keep_individual_outcomes_and_quantities()
