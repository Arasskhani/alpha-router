"""Budget plan resolution and chat blocking without an assigned plan."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.user import User, UserGroup, user_group_members
from app.services.budget_service import (
    BUDGET_EXCEEDED_DETAIL,
    NO_PLAN_BUDGET_DETAIL,
    budget_request_blocked,
    resolve_monthly_budget,
)
from app.services.plan_assignment_service import upsert_group_plan, upsert_user_no_plan


async def _test_no_plan_assignments_yield_zero_budget() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        db.add(
            User(
                username="nobudget",
                email="nobudget@test",
                hashed_password="x",
                monthly_budget_usd=5.0,
                auth_provider="local",
            )
        )
        await db.commit()
        user = (await db.execute(select(User))).scalar_one()
        assert await resolve_monthly_budget(db, user) == 0.0


async def _test_direct_plan_assignment_sets_budget() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        plan = BudgetPlan(name="Team", monthly_budget_usd=12.5)
        db.add(plan)
        db.add(
            User(
                username="member",
                email="member@test",
                hashed_password="x",
                auth_provider="local",
            )
        )
        await db.flush()
        user = (await db.execute(select(User))).scalar_one()
        db.add(PlanAssignment(plan_id=plan.id, user_id=user.id))
        await db.commit()
        assert await resolve_monthly_budget(db, user) == 12.5


async def _test_explicit_no_plan_blocks_group_inheritance() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        plan = BudgetPlan(name="GroupPlan", monthly_budget_usd=20.0)
        group = UserGroup(name="Engineering", source="ldap")
        db.add_all([plan, group])
        await db.flush()
        user = User(
            username="blocked",
            email="blocked@test",
            hashed_password="x",
            auth_provider="local",
        )
        db.add(user)
        await db.flush()
        await db.execute(user_group_members.insert().values(user_id=user.id, group_id=group.id))
        await upsert_group_plan(db, group.id, plan.id)
        await upsert_user_no_plan(db, user.id)
        await db.commit()
        user = (await db.execute(select(User))).scalar_one()
        assert await resolve_monthly_budget(db, user) == 0.0


async def _test_inherit_group_plan_without_user_override() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        plan = BudgetPlan(name="GroupPlan", monthly_budget_usd=20.0)
        group = UserGroup(name="Engineering", source="ldap")
        db.add_all([plan, group])
        await db.flush()
        user = User(
            username="inherit",
            email="inherit@test",
            hashed_password="x",
            auth_provider="local",
        )
        db.add(user)
        await db.flush()
        await db.execute(user_group_members.insert().values(user_id=user.id, group_id=group.id))
        await upsert_group_plan(db, group.id, plan.id)
        await db.commit()
        user = (await db.execute(select(User))).scalar_one()
        assert await resolve_monthly_budget(db, user) == 20.0


async def test_no_plan_assignments_yield_zero_budget():
    await _test_no_plan_assignments_yield_zero_budget()


async def test_direct_plan_assignment_sets_budget():
    await _test_direct_plan_assignment_sets_budget()


async def test_explicit_no_plan_blocks_group_inheritance():
    await _test_explicit_no_plan_blocks_group_inheritance()


async def test_inherit_group_plan_without_user_override():
    await _test_inherit_group_plan_without_user_override()


def test_budget_request_blocked_without_plan():
    assert budget_request_blocked(0.0, 0.0) == NO_PLAN_BUDGET_DETAIL
    assert budget_request_blocked(0.0, 3.0) == NO_PLAN_BUDGET_DETAIL


def test_budget_request_blocked_when_exceeded():
    assert budget_request_blocked(5.0, 5.0) == BUDGET_EXCEEDED_DETAIL
    assert budget_request_blocked(5.0, 6.0) == BUDGET_EXCEEDED_DETAIL


def test_budget_request_allowed_under_cap():
    assert budget_request_blocked(5.0, 4.99) is None
    assert budget_request_blocked(5.0, 0.0) is None
