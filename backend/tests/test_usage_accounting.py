"""Provider-agnostic usage ledger and reconciliation tests."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.cost_accounting import LedgerEntry, UsageEvent, UsageOperation
from app.models.logging import RequestLog
from app.models.user import User
from app.services.proxy_service import log_usage
from app.services.provider_reconciliation_service import (
    OpenAIReconciliationAdapter,
    OpenRouterReconciliationAdapter,
    automatic_reconciliation_providers,
)
from app.services.usage_accounting_service import (
    CONFIDENCE_CALCULATED,
    CONFIDENCE_EXACT,
    COST_SOURCE_CATALOG,
    COST_SOURCE_CONFIGURED,
    COST_SOURCE_PROVIDER,
    capture_usage_event,
    create_configured_pricing_snapshot,
    create_reconciliation_run,
    extract_normalized_usage,
    finish_reconciliation_run,
    persist_usage_operation,
    quote_usage,
    reconcile_usage_event,
    NormalizedUsage,
)


def _model(**overrides):
    values = {
        "external_id": "provider/model",
        "provider_type": "openrouter",
        "connection_id": None,
        "input_cost_per_1k": 0.001,
        "output_cost_per_1k": 0.002,
        "pricing_raw": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_openrouter_provider_cost_has_priority_over_catalog():
    model = _model(
        pricing_raw=json.dumps(
            {
                "id": "provider/model",
                "pricing": {
                    "prompt": "0.000001",
                    "completion": "0.000002",
                },
            }
        )
    )
    event = capture_usage_event(
        {
            "id": "gen-123",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "cost": 0.75,
                "prompt_tokens_details": {"cached_tokens": 100},
                "completion_tokens_details": {"reasoning_tokens": 50},
            },
        },
        ai_model=model,
        provider_type="openrouter",
        service_type="llm",
        operation_name="chat_completion",
        model_id=model.external_id,
    )
    assert event.usage.upstream_request_id == "gen-123"
    assert event.usage.cached_tokens == 100
    assert event.usage.reasoning_tokens == 50
    assert event.quote.final_cost_usd == pytest.approx(0.75)
    assert event.quote.provider_cost_usd == pytest.approx(0.75)
    assert event.quote.calculated_cost_usd == pytest.approx(0.002)
    assert event.quote.cost_source == COST_SOURCE_PROVIDER
    assert event.quote.cost_confidence == CONFIDENCE_EXACT


def test_non_provider_usage_cost_is_litellm_estimate():
    usage = extract_normalized_usage(
        {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "cost": 0.012,
            }
        },
        provider_type="openai",
    )
    assert usage.provider_cost_usd is None
    assert usage.litellm_cost_usd == pytest.approx(0.012)


async def _openrouter_adapter_reads_generation_total_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/generation"
        assert request.url.params["id"] == "gen-test"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={"data": {"id": "gen-test", "total_cost": 0.1234}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cost = await OpenRouterReconciliationAdapter().fetch_actual_cost(
            client,
            connection=SimpleNamespace(base_url="https://openrouter.ai/api/v1"),
            api_key="secret",
            upstream_request_id="gen-test",
        )
    assert cost == pytest.approx(0.1234)


def test_openrouter_adapter_reads_generation_total_cost():
    asyncio.run(_openrouter_adapter_reads_generation_total_cost())


def test_automatic_reconciliation_providers_include_openai():
    assert "openrouter" in automatic_reconciliation_providers()
    assert "openai" in automatic_reconciliation_providers()


async def _openai_adapter_reads_direct_cost_from_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses/resp_abc"
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "id": "resp_abc",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_cost_usd": 0.0456,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cost = await OpenAIReconciliationAdapter().fetch_actual_cost(
            client,
            connection=SimpleNamespace(base_url="https://api.openai.com/v1"),
            api_key="secret",
            upstream_request_id="resp_abc",
        )
    assert cost == pytest.approx(0.0456)


def test_openai_adapter_reads_direct_cost_from_responses():
    asyncio.run(_openai_adapter_reads_direct_cost_from_responses())


async def _openai_adapter_quotes_catalog_from_responses_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses/resp_quote"
        return httpx.Response(
            200,
            json={
                "id": "resp_quote",
                "model": "gpt-4o-mini",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    event = SimpleNamespace(
        model_id="gpt-4o-mini",
        service_type="chat",
        quantity=None,
        unit=None,
    )
    ai_model = _model(
        external_id="gpt-4o-mini",
        provider_type="openai",
        input_cost_per_1k=0.001,
        output_cost_per_1k=0.002,
    )

    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one_or_none(self):
            return self._value

    class _FakeDb:
        async def execute(self, _stmt):
            return _FakeResult(ai_model)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cost = await OpenAIReconciliationAdapter().fetch_actual_cost(
            client,
            connection=SimpleNamespace(base_url="https://api.openai.com/v1"),
            api_key="secret",
            upstream_request_id="resp_quote",
            event=event,
            db=_FakeDb(),
        )
    # 1000 * 0.001/1000 + 500 * 0.002/1000 = 0.001 + 0.001 = 0.002
    assert cost == pytest.approx(0.002)


def test_openai_adapter_quotes_catalog_from_responses_usage():
    asyncio.run(_openai_adapter_quotes_catalog_from_responses_usage())


async def _openai_adapter_skips_chat_completion_ids() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cost = await OpenAIReconciliationAdapter().fetch_actual_cost(
            client,
            connection=SimpleNamespace(base_url="https://api.openai.com/v1"),
            api_key="secret",
            upstream_request_id="chatcmpl-xyz",
        )
    assert cost is None
    assert called is False


def test_openai_adapter_skips_chat_completion_ids():
    asyncio.run(_openai_adapter_skips_chat_completion_ids())


async def _configured_credit_pricing_is_applied() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        await create_configured_pricing_snapshot(
            db,
            provider_type="tavily",
            service_type="tool",
            unit="credit",
            unit_price_usd=0.008,
            source="contract",
        )
        pending = capture_usage_event(
            {"usage": {"credits_used": 2}},
            ai_model=None,
            provider_type="tavily",
            service_type="tool",
            operation_name="search",
            model_id=None,
        )
        summary = await persist_usage_operation(
            db,
            events=[pending],
            user_id=None,
            alpha_router_api_key_id=None,
            budget_reservation_id=None,
            request_log_id=None,
            operation_type="web_search",
            source="test",
            client_app="test",
            success=True,
        )
        await db.commit()

        event = (await db.execute(select(UsageEvent))).scalar_one()
        assert summary.total_cost_usd == pytest.approx(0.016)
        assert float(event.final_cost_usd) == pytest.approx(0.016)
        assert event.cost_source == COST_SOURCE_CONFIGURED
        assert event.quantity == pytest.approx(2)
        assert event.unit == "credit"

    await engine.dispose()


def test_configured_credit_pricing_is_applied():
    asyncio.run(_configured_credit_pricing_is_applied())


async def _ledger_accumulates_and_reconciliation_adjusts_budget() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        user = User(
            username="ledger-user",
            email="ledger@test",
            hashed_password="x",
            auth_provider="local",
            monthly_budget_usd=10,
            budget_used_usd=0,
        )
        db.add(user)
        await db.flush()

        model = _model(
            provider_type="openai",
            input_cost_per_1k=0.1,
            output_cost_per_1k=0,
        )
        event = capture_usage_event(
            {"usage": {"prompt_tokens": 1000, "completion_tokens": 0}},
            ai_model=model,
            provider_type="openai",
            service_type="llm",
            operation_name="chat_completion",
            model_id=model.external_id,
        )
        await log_usage(
            db,
            user_id=user.id,
            username=user.username,
            model_id=model.external_id,
            prompt_tokens=1000,
            completion_tokens=0,
            cached_tokens=0,
            total_cost_usd=0,
            response_time_ms=10,
            prompt_language="en",
            source_ip=None,
            source="alpha_router_chat",
            success=True,
            usage_events=[event],
            operation_type="chat",
        )
        await db.commit()

        log_row = (await db.execute(select(RequestLog))).scalar_one()
        usage_event = (await db.execute(select(UsageEvent))).scalar_one()
        operation = (await db.execute(select(UsageOperation))).scalar_one()
        await db.refresh(user)
        assert log_row.total_cost_usd == pytest.approx(0.1)
        assert float(operation.total_cost_usd) == pytest.approx(0.1)
        assert user.budget_used_usd == pytest.approx(0.1)

        run = await create_reconciliation_run(
            db,
            provider_type="openai",
            source="provider_usage_api",
        )
        delta = await reconcile_usage_event(
            db,
            event_id=usage_event.id,
            actual_cost_usd=0.25,
            reconciliation_run_id=run.id,
        )
        await finish_reconciliation_run(db, run)
        await db.commit()
        await db.refresh(user)
        await db.refresh(log_row)

        ledger_total = (await db.execute(select(func.coalesce(func.sum(LedgerEntry.amount_usd), 0)))).scalar_one()
        assert delta == pytest.approx(0.15)
        assert float(ledger_total) == pytest.approx(0.25)
        assert user.budget_used_usd == pytest.approx(0.25)
        assert log_row.total_cost_usd == pytest.approx(0.25)
        assert log_row.cost_confidence == "reconciled"

    await engine.dispose()


def test_ledger_accumulates_and_reconciliation_adjusts_budget():
    asyncio.run(_ledger_accumulates_and_reconciliation_adjusts_budget())


async def _idempotent_log_replay_does_not_charge_twice() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        user = User(
            username="idempotent-user",
            email="idempotent@test",
            hashed_password="x",
            auth_provider="local",
            monthly_budget_usd=10,
            budget_used_usd=0,
        )
        db.add(user)
        await db.flush()
        event = capture_usage_event(
            {"usage": {"prompt_tokens": 1000}},
            ai_model=_model(
                provider_type="openai",
                input_cost_per_1k=0.1,
                output_cost_per_1k=0,
            ),
            provider_type="openai",
            service_type="llm",
            operation_name="chat_completion",
            model_id="provider/model",
            idempotency_key="same-event",
        )
        kwargs = dict(
            user_id=user.id,
            username=user.username,
            model_id="provider/model",
            prompt_tokens=1000,
            completion_tokens=0,
            cached_tokens=0,
            total_cost_usd=0.1,
            response_time_ms=10,
            prompt_language="en",
            source_ip=None,
            source="test",
            success=True,
            usage_events=[event],
            operation_type="chat",
            operation_idempotency_key="same-operation",
        )
        await log_usage(db, **kwargs)
        await db.commit()
        await log_usage(db, **kwargs)
        await db.commit()
        await db.refresh(user)

        assert user.budget_used_usd == pytest.approx(0.1)
        assert (await db.execute(select(func.count()).select_from(UsageOperation))).scalar_one() == 1
        assert (await db.execute(select(func.count()).select_from(RequestLog))).scalar_one() == 1
        assert (await db.execute(select(func.count()).select_from(LedgerEntry))).scalar_one() == 1

    await engine.dispose()


def test_idempotent_log_replay_does_not_charge_twice():
    asyncio.run(_idempotent_log_replay_does_not_charge_twice())


def test_openrouter_speech_quotes_prompt_as_usd_per_character():
    """OpenRouter TTS stores USD/character in pricing.prompt (not speech/audio)."""
    model = _model(
        external_id="x-ai/grok-voice-tts-1.0",
        pricing_raw=json.dumps(
            {
                "id": "x-ai/grok-voice-tts-1.0",
                "architecture": {"output_modalities": ["speech"]},
                "pricing": {"prompt": "0.000015", "completion": "0"},
                "supported_voices": ["eve", "ara"],
            }
        ),
    )
    event = capture_usage_event(
        None,
        ai_model=model,
        provider_type="openrouter",
        service_type="speech",
        operation_name="speech:text_to_speech",
        model_id=model.external_id,
        quantity=100,
        unit="character",
    )
    assert event.quote.final_cost_usd == pytest.approx(0.0015)
    assert event.quote.cost_source == COST_SOURCE_CATALOG
    assert event.quote.cost_confidence == CONFIDENCE_CALCULATED
    assert any(item.category == "speech" for item in event.quote.line_items)


def test_openrouter_video_quotes_cents_per_second_sku():
    """OpenRouter video SKUs are cents/second and must convert to USD."""
    model = _model(
        external_id="runway/gen-4.5",
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
    event = capture_usage_event(
        None,
        ai_model=model,
        provider_type="openrouter",
        service_type="video",
        operation_name="video:generation",
        model_id=model.external_id,
        quantity=4,
        unit="second",
    )
    assert event.quote.final_cost_usd == pytest.approx(0.48)
    assert event.quote.cost_source == COST_SOURCE_CATALOG
    assert any(item.category == "video" for item in event.quote.line_items)


def test_speech_prompt_fallback_does_not_reprice_chat_tokens_as_characters():
    """Chat must keep treating pricing.prompt as USD/token, not USD/character."""
    model = _model(
        pricing_raw=json.dumps(
            {
                "id": "provider/model",
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            }
        )
    )
    quote = quote_usage(
        NormalizedUsage(prompt_tokens=1000, completion_tokens=500),
        ai_model=model,
        provider_type="openrouter",
        service_type="llm",
        model_id=model.external_id,
    )
    # Must not be 1000 characters * 0.000001 alone reinterpreted as speech.
    assert quote.cost_source == COST_SOURCE_CATALOG
    assert quote.final_cost_usd == pytest.approx(0.002)
    assert not any(item.category == "speech" for item in quote.line_items)
    assert any(item.category == "input_tokens" for item in quote.line_items)
    assert any(item.category == "output_tokens" for item in quote.line_items)


def test_image_catalog_pricing_unchanged_by_speech_video_fallbacks():
    model = _model(
        pricing_raw=json.dumps(
            {
                "id": "provider/image",
                "pricing": {
                    "prompt": "0.000015",
                    "completion": "0",
                    "image": "0.04",
                },
            }
        )
    )
    event = capture_usage_event(
        None,
        ai_model=model,
        provider_type="openrouter",
        service_type="image",
        operation_name="image:generation",
        model_id=model.external_id,
        quantity=1,
        unit="image",
    )
    assert event.quote.final_cost_usd == pytest.approx(0.04)
    assert event.quote.cost_source == COST_SOURCE_CATALOG
    assert any(item.category == "image" for item in event.quote.line_items)
    assert not any(item.category == "speech" for item in event.quote.line_items)
