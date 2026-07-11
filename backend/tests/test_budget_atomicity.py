"""Phase 4: atomic budget/credit increments must not lose updates under concurrency.

The previous ORM read-modify-write pattern (`obj.col = obj.col + cost`) loses
updates when two concurrent transactions both read the old value. The fix uses
a single SQL `UPDATE ... SET col = col + :cost` which is atomic at the row
level. These tests verify the atomic increment path for both user budget and
alpha-router API key usage counters, including NULL handling and concurrent runs.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import AlphaRouterApiKey
from app.models.user import User
from app.services.alpha_router_api_key_service import record_key_usage
from app.services.proxy_service import _apply_cost_to_user


def _make_engine():
    return create_async_engine("sqlite+aiosqlite:///:memory:")


async def _bootstrap():
    engine = _make_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        db.add(
            User(
                username="atomic",
                email="atomic@test",
                hashed_password="x",
                role="user",
                auth_provider="local",
                monthly_budget_usd=100.0,
                budget_used_usd=0.0,
            )
        )
        db.add(
            AlphaRouterApiKey(
                name="K",
                key_prefix="sk-",
                key_hash="h1",
                is_active=True,
                credit_limit_usd=1000.0,
                reset_period="monthly",
                period_used_usd=0.0,
                total_used_usd=0.0,
            )
        )
        await db.commit()
        user = (await db.execute(select(User))).scalar_one()
        key = (await db.execute(select(AlphaRouterApiKey))).scalar_one()
    return engine, factory, user.id, key.id


async def _test_atomic_user_increment_sums_correctly() -> None:
    engine, factory, uid, _ = await _bootstrap()
    # 10 concurrent sessions each add 1.0 — must total exactly 10.0, not less.
    async def add_one():
        async with factory() as db:
            await _apply_cost_to_user(db, uid, 1.0)
            await db.commit()

    await asyncio.gather(*[add_one() for _ in range(10)])
    async with factory() as db:
        user = await db.get(User, uid)
        assert user.budget_used_usd == 10.0
    await engine.dispose()


async def _test_atomic_user_increment_handles_null() -> None:
    engine, factory, uid, _ = await _bootstrap()
    async with factory() as db:
        await db.execute(
            __import__("sqlalchemy").text("UPDATE users SET budget_used_usd = NULL WHERE id = :uid"),
            {"uid": uid},
        )
        await db.commit()
    async with factory() as db:
        await _apply_cost_to_user(db, uid, 2.5)
        await db.commit()
    async with factory() as db:
        user = await db.get(User, uid)
        assert user.budget_used_usd == 2.5
    await engine.dispose()


async def _test_atomic_key_increment_sums_correctly() -> None:
    engine, factory, _, kid = await _bootstrap()
    async def add_cost():
        async with factory() as db:
            key = await db.get(AlphaRouterApiKey, kid)
            await record_key_usage(db, key, 0.3)
            await db.commit()

    await asyncio.gather(*[add_cost() for _ in range(10)])
    async with factory() as db:
        key = await db.get(AlphaRouterApiKey, kid)
        # period and total both reflect all 10 increments (3.0)
        assert abs(key.period_used_usd - 3.0) < 1e-6
        assert abs(key.total_used_usd - 3.0) < 1e-6
        assert key.last_used_at is not None
    await engine.dispose()


async def _test_atomic_key_increment_handles_null() -> None:
    engine, factory, _, kid = await _bootstrap()
    async with factory() as db:
        await db.execute(
            __import__("sqlalchemy").text(
                "UPDATE alpha_router_api_keys SET period_used_usd = NULL, total_used_usd = NULL WHERE id = :kid"
            ),
            {"kid": kid},
        )
        await db.commit()
    async with factory() as db:
        key = await db.get(AlphaRouterApiKey, kid)
        await record_key_usage(db, key, 1.0)
        await db.commit()
    async with factory() as db:
        key = await db.get(AlphaRouterApiKey, kid)
        assert abs(key.period_used_usd - 1.0) < 1e-6
        assert abs(key.total_used_usd - 1.0) < 1e-6
    await engine.dispose()


async def _test_atomic_user_increment_zero_is_noop() -> None:
    engine, factory, uid, _ = await _bootstrap()
    async with factory() as db:
        await _apply_cost_to_user(db, uid, 0.0)
        await db.commit()
    async with factory() as db:
        user = await db.get(User, uid)
        assert user.budget_used_usd == 0.0
    await engine.dispose()


async def _test_atomic_key_increment_zero_is_noop() -> None:
    engine, factory, _, kid = await _bootstrap()
    async with factory() as db:
        key = await db.get(AlphaRouterApiKey, kid)
        await record_key_usage(db, key, 0.0)
        await db.commit()
    async with factory() as db:
        key = await db.get(AlphaRouterApiKey, kid)
        assert key.period_used_usd == 0.0
        assert key.total_used_usd == 0.0
    await engine.dispose()


def test_atomic_user_increment_sums_correctly():
    asyncio.run(_test_atomic_user_increment_sums_correctly())


def test_atomic_user_increment_handles_null():
    asyncio.run(_test_atomic_user_increment_handles_null())


def test_atomic_key_increment_sums_correctly():
    asyncio.run(_test_atomic_key_increment_sums_correctly())


def test_atomic_key_increment_handles_null():
    asyncio.run(_test_atomic_key_increment_handles_null())


def test_atomic_user_increment_zero_is_noop():
    asyncio.run(_test_atomic_user_increment_zero_is_noop())


def test_atomic_key_increment_zero_is_noop():
    asyncio.run(_test_atomic_key_increment_zero_is_noop())
