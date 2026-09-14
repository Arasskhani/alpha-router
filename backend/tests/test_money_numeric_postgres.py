"""Money columns are exact decimals (Phase 4.2). PostgreSQL canary.

With ``double precision`` a thousand SQL-side increments of 0.001 landed on
1.0000000000000007 and the reconciliation job had to repair the counter. With
``NUMERIC(20, 12)`` the sum is exactly 1.000000000000 and the drift gauge
reads 0.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


async def test_thousand_increments_are_exact_and_reconcile_finds_no_drift(monkeypatch):
    engine = _engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    user_id = None
    observed: list[float] = []
    monkeypatch.setattr(brs, "observe_budget_reserved_drift", observed.append)
    try:
        async with factory() as db:
            column_type = (
                await db.execute(
                    text(
                        "SELECT data_type, numeric_scale FROM information_schema.columns "
                        "WHERE table_name = 'users' AND column_name = 'budget_used_usd'"
                    )
                )
            ).one()
            assert tuple(column_type) == ("numeric", 12)

            user = User(
                username=f"numeric-{suffix}",
                email=f"numeric-{suffix}@t",
                hashed_password="x",
                auth_provider="local",
                is_active=True,
                monthly_budget_usd=100.0,
                budget_used_usd=0.0,
                budget_reserved_usd=0.0,
            )
            db.add(user)
            await db.commit()
            user_id = user.id

            for _ in range(1000):
                await db.execute(
                    text("UPDATE users SET budget_used_usd = budget_used_usd + :x WHERE id = :id"),
                    {"x": 0.001, "id": user_id},
                )
            await db.commit()

            exact = (
                await db.execute(text("SELECT budget_used_usd::text FROM users WHERE id = :id"), {"id": user_id})
            ).scalar_one()
            assert exact == "1.000000000000"
            loaded = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            await db.refresh(loaded)  # identity map still holds the pre-update value
            assert isinstance(loaded.budget_used_usd, float)
            assert loaded.budget_used_usd == 1.0

            repaired = await brs.reconcile_drifted_reserved_counters(db)
            await db.commit()
            assert repaired == 0
            assert observed and observed[-1] == 0.0
    finally:
        if user_id is not None:
            async with factory() as db:
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()
        await engine.dispose()
