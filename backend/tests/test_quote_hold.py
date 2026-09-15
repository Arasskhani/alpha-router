"""Unified hold quotes share the settlement catalog/configured path."""

from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.services.budget_reservation_service import reservation_hold_usd
from app.services.usage_accounting_service import (
    COST_SOURCE_CATALOG,
    COST_SOURCE_UNPRICED,
    quote_hold,
)


def _video_model():
    return SimpleNamespace(
        external_id="runway/gen-4.5",
        provider_type="openrouter",
        connection_id=None,
        input_cost_per_1k=None,
        output_cost_per_1k=None,
        pricing_raw=json.dumps(
            {
                "id": "runway/gen-4.5",
                "pricing": {"prompt": "0", "completion": "0"},
                "video_generation": {
                    "pricing_skus": {"cents_per_second_output": "12"},
                },
                "video_capabilities": {
                    "pricing": {"cents_per_second_output": "12"},
                },
            }
        ),
    )


def _chat_model():
    return SimpleNamespace(
        external_id="provider/chat",
        provider_type="openrouter",
        connection_id=None,
        input_cost_per_1k=1.0,
        output_cost_per_1k=2.0,
        pricing_raw=None,
    )


async def _session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory, engine


async def _flow() -> None:
    factory, engine = await _session()
    async with factory() as db:
        four = await quote_hold(
            db,
            service_type="video",
            ai_model=_video_model(),
            provider_type="openrouter",
            model_id="runway/gen-4.5",
            quantity=4.0,
            unit="second",
        )
        eight = await quote_hold(
            db,
            service_type="video",
            ai_model=_video_model(),
            provider_type="openrouter",
            model_id="runway/gen-4.5",
            quantity=8.0,
            unit="second",
        )
        assert four.priced is True
        assert four.cost_source == COST_SOURCE_CATALOG
        assert four.quoted_usd == 0.48
        assert four.hold_usd == 0.528
        assert eight.quoted_usd == 0.96
        assert eight.hold_usd == 0.528 * 2

        unpriced = await quote_hold(
            db,
            service_type="video",
            ai_model=None,
            provider_type="openrouter",
            model_id="unknown/video",
            quantity=30.0,
            unit="second",
        )
        assert unpriced.priced is False
        assert unpriced.cost_source == COST_SOURCE_UNPRICED
        assert unpriced.hold_usd == 0.05

        chat_hold = await reservation_hold_usd(
            db,
            service_type="llm",
            ai_model=_chat_model(),
            provider_type="openrouter",
            body={
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1000,
            },
        )
        assert chat_hold > 0
        assert chat_hold < 5.0

        image_unpriced = await reservation_hold_usd(
            db,
            service_type="image",
            quantity=1.0,
            unit="image",
        )
        assert image_unpriced == 0.05

    await engine.dispose()


async def test_hold_quotes_use_catalog_then_shared_unpriced_fallback() -> None:
    await _flow()
