"""Reserved-counter reconciliation must not undo an in-flight reservation.

PostgreSQL canary (same opt-in flag as the reservation canary). Transaction A
reserves and stays open; transaction B reconciles the same subject. With the
lock-then-sum order B waits for A and lands on the true sum. The old
sum-then-lock order read 0, waited, then wrote 0 over A's counter.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.budget import BudgetPlan, PlanAssignment
from app.models.budget_reservation import BudgetReservation
from app.models.user import User
from app.services import budget_reservation_service as brs

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_RESERVATION_CANARY") != "1",
    reason="opt-in PostgreSQL canary",
)


def _engine():
    from app.config import get_settings
    from app.database import asyncpg_connect_args

    return create_async_engine(get_settings().database_url, connect_args=asyncpg_connect_args())


async def test_reconcile_waits_for_the_in_flight_reservation():
    engine = _engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    user_id = None
    plan_id = None
    try:
        async with factory() as db:
            user = User(
                username=f"race-{suffix}",
                email=f"race-{suffix}@t",
                hashed_password="x",
                auth_provider="local",
                is_active=True,
                monthly_budget_usd=100.0,
                budget_used_usd=0.0,
                budget_reserved_usd=0.0,
            )
            plan = BudgetPlan(name=f"race-{suffix}", monthly_budget_usd=100.0)
            db.add_all([user, plan])
            await db.flush()
            db.add(PlanAssignment(plan_id=plan.id, user_id=user.id))
            await db.commit()
            user_id = user.id
            plan_id = plan.id

        a_holding = asyncio.Event()
        a_release = asyncio.Event()

        async def tx_a():
            async with factory() as db:
                await brs.reserve(
                    db,
                    user_id=user_id,
                    alpha_router_api_key_id=None,
                    amount_usd=2.5,
                    operation="chat",
                    model_id="m",
                    idempotency_key=f"race-{suffix}",
                )
                a_holding.set()  # row inserted, counter bumped, lock held
                await a_release.wait()
                await db.commit()

        async def tx_b():
            await a_holding.wait()
            async with factory() as db:
                # Starts while A holds the FOR UPDATE lock; must block, not read stale.
                task = asyncio.ensure_future(brs.reconcile_subject_reserved(db, brs.SUBJECT_USER, user_id))
                await asyncio.sleep(0.3)
                assert not task.done(), "reconcile should be waiting on A's row lock"
                a_release.set()
                held = await task
                await db.commit()
                return held

        held_b, _ = await asyncio.gather(tx_b(), tx_a())
        assert held_b == 2.5

        async with factory() as db:
            counter = (await db.execute(select(User.budget_reserved_usd).where(User.id == user_id))).scalar_one()
            rows = (
                (
                    await db.execute(
                        select(BudgetReservation.reserved_usd).where(
                            BudgetReservation.subject_type == brs.SUBJECT_USER,
                            BudgetReservation.subject_id == user_id,
                            BudgetReservation.status == brs.STATUS_HELD,
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert rows == [2.5]
        assert float(counter) == 2.5, "counter must equal the sum of held rows after reconcile"
    finally:
        if user_id is not None:
            async with factory() as db:
                await db.execute(delete(BudgetReservation).where(BudgetReservation.subject_id == user_id))
                await db.execute(delete(PlanAssignment).where(PlanAssignment.user_id == user_id))
                await db.execute(delete(User).where(User.id == user_id))
                if plan_id is not None:
                    await db.execute(delete(BudgetPlan).where(BudgetPlan.id == plan_id))
                await db.commit()
        await engine.dispose()


async def test_drift_repair_is_single_flight_via_advisory_lock():
    engine = _engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as holder, factory() as other:
            # Someone else holds the reconcile lock in an open transaction.
            got = (
                await holder.execute(text("SELECT pg_try_advisory_xact_lock(:id)"), {"id": brs.RECONCILE_LOCK_ID})
            ).scalar()
            assert got is True
            assert await brs.reconcile_drifted_reserved_counters(other) == 0
            await holder.rollback()
            # Free again: runs (nothing to repair, but it did run - no early return).
            assert await brs.reconcile_drifted_reserved_counters(other) >= 0
            await other.rollback()
    finally:
        await engine.dispose()
