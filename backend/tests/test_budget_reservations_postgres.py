"""Opt-in PostgreSQL concurrency canary for production-like reservation semantics."""

import asyncio
import datetime
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.database import AsyncSessionLocal, engine
from app.api import images
from app.models.api_key import AlphaRouterApiKey
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.budget_reservation import BudgetReservation
from app.models.logging import RequestLog
from app.models.user import User
from app.services.budget_reservation_service import expire_stale_reservations, release, reserve
from app.services.proxy_service import log_usage

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_RESERVATION_CANARY") != "1",
    reason="opt-in PostgreSQL reservation canary",
)


def test_image_transaction_releases_user_lock_before_settlement() -> None:
    async def run() -> None:
        suffix = uuid.uuid4().hex
        user_id: int | None = None
        plan_id: int | None = None
        hold_id: str | None = None
        try:
            async with AsyncSessionLocal() as db:
                plan = BudgetPlan(
                    name=f"image-lock-canary-{suffix}",
                    monthly_budget_usd=1.0,
                )
                user = User(
                    username=f"image-lock-canary-{suffix}",
                    email=f"image-lock-{suffix}@test.invalid",
                    hashed_password="disabled",
                    role="user",
                    auth_provider="local",
                    is_active=True,
                    monthly_budget_usd=1.0,
                    budget_used_usd=0.0,
                    budget_reserved_usd=0.0,
                )
                db.add_all([plan, user])
                await db.flush()
                db.add(PlanAssignment(plan_id=plan.id, user_id=user.id))
                await db.commit()
                user_id = user.id
                plan_id = plan.id

            async with AsyncSessionLocal() as request_db:
                await request_db.execute(
                    select(User).where(User.id == user_id).with_for_update()
                )
                await images._close_image_request_transaction(request_db, success=True)

                async def independent_billing() -> str:
                    async with AsyncSessionLocal() as billing_db:
                        hold = await reserve(
                            billing_db,
                            user_id=user_id,
                            alpha_router_api_key_id=None,
                            amount_usd=0.1,
                            operation="image",
                            model_id="canary/image",
                            idempotency_key=f"image-lock-{suffix}",
                        )
                        await billing_db.commit()
                        return hold.id

                hold_id = await asyncio.wait_for(independent_billing(), timeout=3)
        finally:
            async with AsyncSessionLocal() as db:
                if hold_id:
                    await release(db, hold_id)
                if user_id is not None:
                    await db.execute(
                        delete(BudgetReservation).where(
                            BudgetReservation.subject_type == "user",
                            BudgetReservation.subject_id == user_id,
                        )
                    )
                    await db.execute(
                        delete(PlanAssignment).where(PlanAssignment.user_id == user_id)
                    )
                    await db.execute(delete(User).where(User.id == user_id))
                if plan_id is not None:
                    await db.execute(delete(BudgetPlan).where(BudgetPlan.id == plan_id))
                await db.commit()
            await engine.dispose()

    asyncio.run(run())


def test_postgres_concurrent_user_and_key_reservations() -> None:
    async def run() -> None:
        suffix = uuid.uuid4().hex
        user_id = plan_id = key_id = None
        hold_ids: list[str] = []
        try:
            async with AsyncSessionLocal() as db:
                plan = BudgetPlan(name=f"reservation-canary-{suffix}", monthly_budget_usd=1.0)
                user = User(
                    username=f"reservation-canary-{suffix}",
                    email=f"{suffix}@test.invalid",
                    hashed_password="disabled",
                    role="user",
                    auth_provider="local",
                    is_active=True,
                    budget_used_usd=0.0,
                    budget_reserved_usd=0.0,
                )
                key = AlphaRouterApiKey(
                    name=f"reservation-canary-{suffix}",
                    key_prefix="sk-test",
                    key_hash=suffix,
                    is_active=True,
                    credit_limit_usd=1.0,
                    reset_period="monthly",
                    period_used_usd=0.0,
                    period_reserved_usd=0.0,
                    total_used_usd=0.0,
                    period_started_at=datetime.datetime.utcnow(),
                )
                db.add_all([plan, user, key])
                await db.flush()
                db.add(PlanAssignment(plan_id=plan.id, user_id=user.id))
                await db.commit()
                user_id, plan_id, key_id = user.id, plan.id, key.id

            async def reserve_user(index: int) -> str | None:
                async with AsyncSessionLocal() as db:
                    try:
                        row = await reserve(
                            db,
                            user_id=user_id,
                            alpha_router_api_key_id=None,
                            amount_usd=0.2,
                            operation="chat",
                            model_id="canary/model",
                            idempotency_key=f"user-{suffix}-{index}",
                        )
                        await db.commit()
                        return row.id
                    except HTTPException as exc:
                        await db.rollback()
                        assert exc.status_code == 402
                        return None

            results = await asyncio.gather(*(reserve_user(i) for i in range(10)))
            hold_ids = [item for item in results if item]
            assert len(hold_ids) == 5

            for hold_id in hold_ids:
                async with AsyncSessionLocal() as db:
                    await log_usage(
                        db,
                        user_id=user_id,
                        username=f"reservation-canary-{suffix}",
                        model_id="canary/model",
                        prompt_tokens=1,
                        completion_tokens=1,
                        cached_tokens=0,
                        total_cost_usd=0.1,
                        response_time_ms=1,
                        prompt_language="en",
                        source_ip=None,
                        source="canary",
                        success=True,
                        budget_reservation_id=hold_id,
                    )
                    await db.commit()

            async with AsyncSessionLocal() as db:
                user = await db.get(User, user_id)
                log_total = (
                    await db.execute(
                        select(func.coalesce(func.sum(RequestLog.total_cost_usd), 0)).where(
                            RequestLog.user_id == user_id
                        )
                    )
                ).scalar_one()
                assert float(user.budget_reserved_usd or 0) == 0
                assert float(user.budget_used_usd or 0) == pytest.approx(0.5)
                assert float(log_total) == pytest.approx(0.5)

            async with AsyncSessionLocal() as db:
                stale = await reserve(
                    db,
                    user_id=user_id,
                    alpha_router_api_key_id=None,
                    amount_usd=0.2,
                    operation="chat",
                    model_id="canary/model",
                    idempotency_key=f"stale-{suffix}",
                )
                stale.expires_at = datetime.datetime.utcnow() - datetime.timedelta(seconds=1)
                await db.commit()
            async with AsyncSessionLocal() as db:
                assert await expire_stale_reservations(db) == 1
                await db.commit()
            async with AsyncSessionLocal() as db:
                user = await db.get(User, user_id)
                assert float(user.budget_reserved_usd or 0) == 0

            async def reserve_duplicate() -> tuple[str | None, int | None]:
                async with AsyncSessionLocal() as db:
                    try:
                        row = await reserve(
                            db,
                            user_id=user_id,
                            alpha_router_api_key_id=None,
                            amount_usd=0.1,
                            operation="chat",
                            model_id="canary/model",
                            idempotency_key=f"same-{suffix}",
                        )
                        await db.commit()
                        return row.id, None
                    except HTTPException as exc:
                        await db.rollback()
                        return None, exc.status_code

            duplicate_results = await asyncio.gather(*(reserve_duplicate() for _ in range(10)))
            duplicate_holds = [hold for hold, _ in duplicate_results if hold]
            assert len(duplicate_holds) == 1
            assert [status for _, status in duplicate_results if status] == [409] * 9
            async with AsyncSessionLocal() as db:
                assert await release(db, duplicate_holds[0])
                await db.commit()

            async def reserve_key(index: int) -> str | None:
                async with AsyncSessionLocal() as db:
                    try:
                        row = await reserve(
                            db,
                            user_id=None,
                            alpha_router_api_key_id=key_id,
                            amount_usd=0.2,
                            operation="embedding",
                            model_id="canary/embed",
                            idempotency_key=f"key-{suffix}-{index}",
                        )
                        await db.commit()
                        return row.id
                    except HTTPException as exc:
                        await db.rollback()
                        assert exc.status_code == 402
                        return None

            key_results = await asyncio.gather(*(reserve_key(i) for i in range(10)))
            key_hold_ids = [item for item in key_results if item]
            assert len(key_hold_ids) == 5
            for hold_id in key_hold_ids:
                async with AsyncSessionLocal() as db:
                    await log_usage(
                        db,
                        user_id=None,
                        username="router-key-canary",
                        model_id="canary/embed",
                        prompt_tokens=1,
                        completion_tokens=0,
                        cached_tokens=0,
                        total_cost_usd=0.1,
                        response_time_ms=1,
                        prompt_language="en",
                        source_ip=None,
                        source="alpha_router_key",
                        success=True,
                        alpha_router_api_key_id=key_id,
                        budget_reservation_id=hold_id,
                    )
                    await db.commit()
            async with AsyncSessionLocal() as db:
                key = await db.get(AlphaRouterApiKey, key_id)
                assert float(key.period_reserved_usd or 0) == 0
                assert float(key.period_used_usd or 0) == pytest.approx(0.5)
                assert float(key.total_used_usd or 0) == pytest.approx(0.5)

                key.period_started_at = datetime.datetime.utcnow() - datetime.timedelta(days=31)
                key.period_used_usd = 0.9
                await db.commit()
            async with AsyncSessionLocal() as db:
                rollover = await reserve(
                    db,
                    user_id=None,
                    alpha_router_api_key_id=key_id,
                    amount_usd=0.6,
                    operation="embedding",
                    model_id="canary/embed",
                    idempotency_key=f"rollover-{suffix}",
                )
                await db.commit()
                key = await db.get(AlphaRouterApiKey, key_id)
                assert rollover is not None
                assert float(key.period_used_usd or 0) == 0
                assert float(key.period_reserved_usd or 0) == pytest.approx(0.6)
        finally:
            if user_id is not None or key_id is not None:
                async with AsyncSessionLocal() as db:
                    subjects = []
                    if user_id is not None:
                        subjects.append(("user", user_id))
                    if key_id is not None:
                        subjects.append(("alpha_router_key", key_id))
                    for subject_type, subject_id in subjects:
                        await db.execute(
                            delete(BudgetReservation).where(
                                BudgetReservation.subject_type == subject_type,
                                BudgetReservation.subject_id == subject_id,
                            )
                        )
                    if user_id is not None:
                        await db.execute(delete(RequestLog).where(RequestLog.user_id == user_id))
                        await db.execute(delete(PlanAssignment).where(PlanAssignment.user_id == user_id))
                        await db.execute(delete(User).where(User.id == user_id))
                    if key_id is not None:
                        await db.execute(
                            delete(RequestLog).where(
                                RequestLog.alpha_router_api_key_id == key_id
                            )
                        )
                        await db.execute(
                            delete(AlphaRouterApiKey).where(
                                AlphaRouterApiKey.id == key_id
                            )
                        )
                    if plan_id is not None:
                        await db.execute(delete(BudgetPlan).where(BudgetPlan.id == plan_id))
                    await db.commit()

    asyncio.run(run())
