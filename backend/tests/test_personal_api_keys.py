"""Personal API keys — self-service, one per user, budget debited."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_api_key
from app.database import Base
from app.models.api_key import UserApiKey
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.logging import RequestLog
from app.models.user import User
from app.services.user_api_key_service import ensure_can_create_personal_key
from app.services.user_service import get_user_by_api_key


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _seed_user_with_plan(session_factory, *, budget: float = 50.0):
    async with session_factory() as db:
        plan = BudgetPlan(name="starter", monthly_budget_usd=budget)
        db.add(plan)
        await db.flush()
        user = User(
            username="bob",
            email="bob@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        db.add(PlanAssignment(user_id=user.id, plan_id=plan.id))
        await db.commit()
        return user.id


async def _test_one_key_limit():
    _, sf = await _setup_db()
    user_id = await _seed_user_with_plan(sf)
    async with sf() as db:
        user = await db.get(User, user_id)
        await ensure_can_create_personal_key(db, user)
        db.add(
            UserApiKey(
                user_id=user.id,
                name="Personal API Key",
                key_prefix="alpha_router_bob",
                key_hash=hash_api_key("alpha_router_bob_test"),
            )
        )
        await db.commit()
    async with sf() as db:
        user = await db.get(User, user_id)
        with pytest.raises(HTTPException) as exc:
            await ensure_can_create_personal_key(db, user)
        assert exc.value.status_code == 409


async def _test_get_user_by_api_key_returns_user_key():
    _, sf = await _setup_db()
    raw = "alpha_router_bob_secret"
    async with sf() as db:
        user = User(
            username="bob",
            email="bob@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        key = UserApiKey(
            user_id=user.id,
            name="Personal API Key",
            key_prefix=raw[:16],
            key_hash=hash_api_key(raw),
        )
        db.add(key)
        await db.commit()
        key_id = key.id
    async with sf() as db:
        user, source, router_key, user_key = await get_user_by_api_key(db, raw)
        assert source == "user_key"
        assert router_key is None
        assert user is not None
        assert user_key is not None
        assert user_key.id == key_id


async def _test_request_log_stores_user_api_key_id():
    _, sf = await _setup_db()
    async with sf() as db:
        user = User(username="bob", email="bob@test", hashed_password="x", auth_provider="local")
        db.add(user)
        await db.flush()
        key = UserApiKey(
            user_id=user.id,
            name="Personal API Key",
            key_prefix="alpha_router_bob",
            key_hash=hash_api_key("alpha_router_bob_x"),
        )
        db.add(key)
        await db.flush()
        db.add(
            RequestLog(
                user_id=user.id,
                username=user.username,
                model_id="gpt-4o-mini",
                source="user_key",
                user_api_key_id=key.id,
                total_cost_usd=0.01,
            )
        )
        await db.commit()
        row = (await db.execute(select(RequestLog))).scalars().first()
        assert row.user_api_key_id == key.id


async def test_one_key_limit():
    await _test_one_key_limit()


async def test_get_user_by_api_key_returns_user_key():
    await _test_get_user_by_api_key_returns_user_key()


async def test_request_log_stores_user_api_key_id():
    await _test_request_log_stores_user_api_key_id()
