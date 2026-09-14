"""GET /api/user/budget uses the live period counter, not the ledger month sum."""

from __future__ import annotations

import datetime

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.deps import get_current_user
from app.api.user_routes import router as user_router
from app.database import Base, get_db
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.logging import RequestLog
from app.models.user import User, UserGroup, user_group_members
from app.services.budget_service import get_month_usage


def _month_start() -> datetime.datetime:
    now = datetime.datetime.utcnow()
    return datetime.datetime(now.year, now.month, 1)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _client_for(factory, user_id: int) -> AsyncClient:
    async def override_db():
        async with factory() as session:
            yield session

    async def override_user():
        async with factory() as session:
            return await session.get(User, user_id)

    api = FastAPI()
    api.include_router(user_router)
    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_current_user] = override_user
    transport = ASGITransport(app=api)
    return AsyncClient(transport=transport, base_url="http://test")


async def _flow() -> None:
    factory, engine = await _session_factory()
    period_start = _month_start()
    async with factory() as db:
        plan = BudgetPlan(name="AGP-15", monthly_budget_usd=15.0)
        group_plan = BudgetPlan(name="Group-20", monthly_budget_usd=20.0)
        group = UserGroup(name="Engineering", source="local")
        majid = User(
            username="majid",
            email="majid@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
            budget_used_usd=9.0,
            budget_reserved_usd=1.5,
            budget_period_start=period_start,
        )
        inheritor = User(
            username="inherit-group",
            email="inherit@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
            budget_used_usd=1.25,
            budget_reserved_usd=0.0,
            budget_period_start=period_start,
        )
        reset_user = User(
            username="reset-user",
            email="reset@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
            budget_used_usd=0.0,
            budget_reserved_usd=0.0,
            budget_period_start=datetime.datetime.utcnow(),
        )
        db.add_all([plan, group_plan, group, majid, inheritor, reset_user])
        await db.flush()
        db.add_all(
            [
                PlanAssignment(plan_id=plan.id, user_id=majid.id),
                PlanAssignment(plan_id=plan.id, user_id=reset_user.id),
                PlanAssignment(plan_id=group_plan.id, group_id=group.id),
            ]
        )
        await db.execute(user_group_members.insert().values(user_id=inheritor.id, group_id=group.id))
        db.add_all(
            [
                RequestLog(
                    user_id=majid.id,
                    username=majid.username,
                    model_id="test/model",
                    total_cost_usd=7.02,
                    usage_operation_id=None,
                    request_time=period_start + datetime.timedelta(days=1),
                    success=True,
                ),
                RequestLog(
                    user_id=reset_user.id,
                    username=reset_user.username,
                    model_id="test/model",
                    total_cost_usd=2.78,
                    usage_operation_id=None,
                    request_time=period_start + datetime.timedelta(hours=1),
                    success=True,
                ),
            ]
        )
        await db.commit()
        ids = {
            "majid": majid.id,
            "inherit": inheritor.id,
            "reset": reset_user.id,
        }

    async with await _client_for(factory, ids["majid"]) as client:
        payload = (await client.get("/api/user/budget")).json()
    assert payload["monthly_budget_usd"] == 15.0
    assert payload["used_usd"] == 9.0
    assert payload["reserved_usd"] == 1.5
    assert payload["remaining_usd"] == 4.5

    async with factory() as db:
        ledger_month = await get_month_usage(db, ids["majid"])
    assert ledger_month == 7.02
    assert payload["used_usd"] != ledger_month

    async with await _client_for(factory, ids["inherit"]) as client:
        inherited = (await client.get("/api/user/budget")).json()
    assert inherited["monthly_budget_usd"] == 20.0
    assert inherited["used_usd"] == 1.25
    assert inherited["remaining_usd"] == 18.75

    async with await _client_for(factory, ids["reset"]) as client:
        after_reset = (await client.get("/api/user/budget")).json()
    assert after_reset["monthly_budget_usd"] == 15.0
    assert after_reset["used_usd"] == 0.0
    assert after_reset["remaining_usd"] == 15.0

    await engine.dispose()


async def test_user_budget_matches_period_counter_not_ledger_sum() -> None:
    await _flow()
