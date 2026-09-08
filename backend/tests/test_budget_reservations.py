"""Atomic reservation, settlement, release, expiry, and idempotency tests."""

import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import AlphaRouterApiKey
from app.models.budget_reservation import BudgetReservation
from app.models.logging import RequestLog
from app.models.user import User
from app.services import budget_reservation_service as reservations
from app.api import images
from app.services.budget_service import ensure_budget_period
from app.services.alpha_router_api_key_service import maybe_reset_key_period
from app.services import proxy_service
from app.services.proxy_service import log_usage


def test_chat_hold_estimate_does_not_call_provider_tokenizer() -> None:
    model = SimpleNamespace(
        input_cost_per_1k=0.001,
        output_cost_per_1k=0.002,
    )
    with patch.object(
        reservations.litellm,
        "token_counter",
        side_effect=AssertionError("stream preflight must not tokenize"),
    ):
        estimate = reservations.estimate_chat_hold(
            model,
            {
                "messages": [{"role": "user", "content": "سلام" * 100}],
                "max_tokens": 1000,
            },
        )
    assert estimate >= 0.0025


def test_image_request_transaction_closes_before_billing() -> None:
    async def run() -> None:
        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        await images._close_image_request_transaction(db, success=True)
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

        db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
        await images._close_image_request_transaction(db, success=False)
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    asyncio.run(run())


async def _bootstrap():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        user = User(
            username="reserve-user",
            email="reserve@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
            monthly_budget_usd=1.0,
            budget_used_usd=0.0,
            budget_reserved_usd=0.0,
            budget_period_start=datetime.datetime.utcnow().replace(day=1),
        )
        key = AlphaRouterApiKey(
            name="reserve-key",
            key_prefix="sk-",
            key_hash="reserve-hash",
            is_active=True,
            credit_limit_usd=1.0,
            reset_period="monthly",
            period_used_usd=0.0,
            period_reserved_usd=0.0,
            total_used_usd=0.0,
            period_started_at=datetime.datetime.utcnow(),
        )
        db.add_all([user, key])
        await db.commit()
        return engine, factory, user.id, key.id


async def _reserve_user(db, user_id, amount, key):
    with patch.object(reservations, "ensure_budget_period", AsyncMock(return_value=None)):
        return await reservations.reserve(
            db,
            user_id=user_id,
            alpha_router_api_key_id=None,
            amount_usd=amount,
            operation="chat",
            model_id="test/model",
            idempotency_key=key,
        )


def test_user_reserve_settle_and_limit_enforcement() -> None:
    async def run():
        engine, factory, user_id, _ = await _bootstrap()
        async with factory() as db:
            hold = await _reserve_user(db, user_id, 0.6, "first")
            await db.commit()
        async with factory() as db:
            # $1.00 limit with $0.60 held: the whole $0.50 estimate does not fit,
            # so the request is refused rather than admitted on a smaller hold.
            with pytest.raises(HTTPException) as exc:
                await _reserve_user(db, user_id, 0.5, "second")
            assert exc.value.status_code == 402
            await db.rollback()
        async with factory() as db:
            assert await reservations.settle(db, hold.id, actual_usd=0.4)
            await db.commit()
        async with factory() as db:
            user = await db.get(User, user_id)
            row = await db.get(BudgetReservation, hold.id)
            assert user.budget_reserved_usd == 0
            assert user.budget_used_usd == pytest.approx(0.4)
            assert row.status == reservations.STATUS_SETTLED
        await engine.dispose()

    asyncio.run(run())


def test_release_expiry_and_duplicate_idempotency() -> None:
    async def run():
        engine, factory, user_id, _ = await _bootstrap()
        async with factory() as db:
            first = await _reserve_user(db, user_id, 0.2, "duplicate")
            await db.commit()
        async with factory() as db:
            with pytest.raises(HTTPException) as exc:
                await _reserve_user(db, user_id, 0.2, "duplicate")
            assert exc.value.status_code == 409
            await db.rollback()
        async with factory() as db:
            row = await db.get(BudgetReservation, first.id)
            row.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
            await db.commit()
        async with factory() as db:
            assert await reservations.expire_stale_reservations(db) == 1
            await db.commit()
        async with factory() as db:
            user = await db.get(User, user_id)
            row = await db.get(BudgetReservation, first.id)
            assert user.budget_reserved_usd == 0
            assert row.status == reservations.STATUS_EXPIRED
        await engine.dispose()

    asyncio.run(run())


def test_alpha_router_key_reservation_and_log_settlement_are_atomic() -> None:
    async def run():
        engine, factory, _, key_id = await _bootstrap()
        async with factory() as db:
            hold = await reservations.reserve(
                db,
                user_id=None,
                alpha_router_api_key_id=key_id,
                amount_usd=0.7,
                operation="embedding",
                model_id="embed/model",
                idempotency_key="key-hold",
            )
            await db.commit()
        async with factory() as db:
            # $1.00 credit with $0.70 held: the $0.40 estimate does not fit, so
            # admission is refused (see _hold_fits_balance).
            with pytest.raises(HTTPException) as exc:
                await reservations.reserve(
                    db,
                    user_id=None,
                    alpha_router_api_key_id=key_id,
                    amount_usd=0.4,
                    operation="embedding",
                    model_id="embed/model",
                    idempotency_key="key-over",
                )
            assert exc.value.status_code == 402
            await db.rollback()
        async with factory() as db:
            await log_usage(
                db,
                user_id=None,
                username="router-key",
                model_id="embed/model",
                prompt_tokens=10,
                completion_tokens=0,
                cached_tokens=0,
                total_cost_usd=0.3,
                response_time_ms=1,
                prompt_language="en",
                source_ip=None,
                source="alpha_router_key",
                success=True,
                alpha_router_api_key_id=key_id,
                budget_reservation_id=hold.id,
            )
            await db.commit()
        async with factory() as db:
            key = await db.get(AlphaRouterApiKey, key_id)
            logs = (await db.execute(select(RequestLog))).scalars().all()
            assert key.period_reserved_usd == 0
            assert key.period_used_usd == pytest.approx(0.3)
            assert key.total_used_usd == pytest.approx(0.3)
            assert len(logs) == 1
            assert logs[0].budget_reservation_id == hold.id
        await engine.dispose()

    asyncio.run(run())


def test_period_rollover_releases_inflight_holds() -> None:
    """F-20: month/key period reset must expire open holds and clear reserved."""
    async def run():
        engine, factory, user_id, key_id = await _bootstrap()
        async with factory() as db:
            user_hold = await _reserve_user(db, user_id, 0.2, "rollover-user")
            key_hold = await reservations.reserve(
                db,
                user_id=None,
                alpha_router_api_key_id=key_id,
                amount_usd=0.3,
                operation="embedding",
                model_id="embed/model",
                idempotency_key="rollover-key",
            )
            user = await db.get(User, user_id)
            key = await db.get(AlphaRouterApiKey, key_id)
            user.budget_period_start = datetime.datetime.utcnow() - datetime.timedelta(days=40)
            key.period_started_at = datetime.datetime.utcnow() - datetime.timedelta(days=31)
            await db.commit()
        async with factory() as db:
            user = await db.get(User, user_id)
            key = await db.get(AlphaRouterApiKey, key_id)
            await ensure_budget_period(db, user)
            await maybe_reset_key_period(db, key)
            await db.commit()
        async with factory() as db:
            user = await db.get(User, user_id)
            key = await db.get(AlphaRouterApiKey, key_id)
            assert user.budget_reserved_usd == pytest.approx(0.0)
            assert key.period_reserved_usd == pytest.approx(0.0)
            assert (await db.get(BudgetReservation, user_hold.id)).status == reservations.STATUS_EXPIRED
            assert (await db.get(BudgetReservation, key_hold.id)).status == reservations.STATUS_EXPIRED
        await engine.dispose()

    asyncio.run(run())


def test_settle_after_rollover_charges_new_period_via_fallback() -> None:
    """After rollover expires a hold, log_usage still applies cost once."""
    async def run():
        engine, factory, user_id, _ = await _bootstrap()
        async with factory() as db:
            hold = await _reserve_user(db, user_id, 0.25, "rollover-settle")
            user = await db.get(User, user_id)
            user.budget_period_start = datetime.datetime.utcnow() - datetime.timedelta(days=40)
            await db.commit()
            hold_id = hold.id
        async with factory() as db:
            user = await db.get(User, user_id)
            await ensure_budget_period(db, user)
            await db.commit()
            assert user.budget_reserved_usd == pytest.approx(0.0)
            assert (await db.get(BudgetReservation, hold_id)).status == reservations.STATUS_EXPIRED
        async with factory() as db:
            await log_usage(
                db,
                user_id=user_id,
                username="reserve-user",
                model_id="chat/model",
                prompt_tokens=10,
                completion_tokens=20,
                cached_tokens=0,
                total_cost_usd=0.11,
                response_time_ms=1,
                prompt_language="en",
                source_ip=None,
                source="user_key",
                success=True,
                budget_reservation_id=hold_id,
            )
            await db.commit()
        async with factory() as db:
            user = await db.get(User, user_id)
            row = await db.get(BudgetReservation, hold_id)
            log = (
                await db.execute(
                    select(RequestLog).where(RequestLog.budget_reservation_id == hold_id)
                )
            ).scalar_one()
            assert row.status == reservations.STATUS_EXPIRED
            assert user.budget_reserved_usd == pytest.approx(0.0)
            assert user.budget_used_usd == pytest.approx(0.11)
            assert float(log.total_cost_usd) == pytest.approx(0.11)
        await engine.dispose()

    asyncio.run(run())


def test_embedding_failure_settles_committed_hold_independently() -> None:
    async def run():
        engine, factory, user_id, _ = await _bootstrap()
        async with factory() as db:
            hold = await _reserve_user(db, user_id, 0.2, "embedding-failure")
            await db.commit()
        resolved = SimpleNamespace(
            ai_model=SimpleNamespace(provider_type="openai", input_cost_per_1k=0.001),
            api_key="test",
            base_url="https://example.invalid",
            provider_type="openai",
            model_id="embed/model",
            budget_reservation_id=hold.id,
        )
        async with factory() as db:
            with (
                patch.object(
                    proxy_service,
                    "preflight_stream_chat",
                    AsyncMock(return_value=resolved),
                ),
                patch.object(
                    proxy_service,
                    "aembedding",
                    AsyncMock(side_effect=RuntimeError("provider failed")),
                ),
                patch.object(proxy_service, "AsyncSessionLocal", factory),
                pytest.raises(HTTPException) as exc,
            ):
                await proxy_service.create_embedding(
                    db,
                    {"model": "embed/model", "input": "hello"},
                    user_id=user_id,
                    username="reserve-user",
                    source="user_key",
                    skip_budget=False,
                    alpha_router_api_key_id=None,
                    client_app="test",
                    source_ip=None,
                )
            assert exc.value.status_code == 502
            await db.rollback()
        async with factory() as db:
            user = await db.get(User, user_id)
            row = await db.get(BudgetReservation, hold.id)
            log = (
                await db.execute(
                    select(RequestLog).where(
                        RequestLog.budget_reservation_id == hold.id
                    )
                )
            ).scalar_one()
            assert user.budget_reserved_usd == 0
            assert row.status == reservations.STATUS_SETTLED
            assert log.success is False
        await engine.dispose()

    asyncio.run(run())


def test_image_failure_settles_committed_hold_independently() -> None:
    async def run():
        engine, factory, user_id, _ = await _bootstrap()
        ai_model = SimpleNamespace(
            external_id="image/model",
            provider_type="openai",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
        )
        request = MagicMock()
        request.client = SimpleNamespace(host="127.0.0.1")
        request.headers = {}
        async with factory() as db:
            user = await db.get(User, user_id)
            with (
                patch.object(
                    images,
                    "_resolve_image_model",
                    AsyncMock(
                        return_value=(
                            "image/model",
                            "test-key",
                            "https://example.invalid",
                            "openai",
                            ai_model,
                        )
                    ),
                ),
                patch.object(
                    images,
                    "resolve_reference_image_for_upstream",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    images.litellm,
                    "aimage_generation",
                    AsyncMock(side_effect=RuntimeError("provider failed")),
                ),
                patch.object(images, "AsyncSessionLocal", factory),
                patch.object(
                    reservations,
                    "ensure_budget_period",
                    AsyncMock(return_value=None),
                ),
                pytest.raises(HTTPException) as exc,
            ):
                await images.generate_image(
                    request,
                    images.ImageRequest(
                        model="image/model",
                        prompt="test",
                        persist=False,
                    ),
                    user,
                    db,
                )
            assert exc.value.status_code == 500
            await db.rollback()
        async with factory() as db:
            row = (
                await db.execute(
                    select(BudgetReservation).where(
                        BudgetReservation.operation == "image"
                    )
                )
            ).scalar_one()
            user = await db.get(User, user_id)
            log = (
                await db.execute(
                    select(RequestLog).where(
                        RequestLog.budget_reservation_id == row.id
                    )
                )
            ).scalar_one()
            assert row.status == reservations.STATUS_SETTLED
            assert user.budget_reserved_usd == 0
            assert log.success is False
        await engine.dispose()

    asyncio.run(run())
