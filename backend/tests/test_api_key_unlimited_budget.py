"""A gateway key with no positive credit limit is blocked unless explicitly unlimited."""

from __future__ import annotations

import asyncio
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.api_key import AlphaRouterApiKey
from app.models.user import User
from app.services.alpha_router_api_key_service import ensure_key_usable, key_to_dict


async def _db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


def _key(name, *, limit, unlimited):
    return AlphaRouterApiKey(
        name=name, key_prefix=f"ar_{name}"[:16], key_hash=f"h_{name}" + "0" * 20, is_active=True,
        credit_limit_usd=limit, unlimited_budget=unlimited, reset_period="monthly",
        period_used_usd=0.0, period_started_at=datetime.datetime.utcnow(),
    )


def test_zero_limit_blocks_unless_unlimited():
    async def run():
        factory, engine = await _db()
        try:
            async with factory() as db:
                owner = User(username="o", email="o@t", hashed_password="x", auth_provider="local", is_active=True)
                db.add(owner)
                await db.flush()
                blocked = _key("blocked", limit=0.0, unlimited=False)
                unlimited = _key("unlimited", limit=0.0, unlimited=True)
                capped = _key("capped", limit=5.0, unlimited=False)
                for k in (blocked, unlimited, capped):
                    k.owner_user_id = owner.id
                db.add_all([blocked, unlimited, capped])
                await db.commit()

                with pytest.raises(HTTPException) as exc:
                    await ensure_key_usable(db, blocked)
                assert exc.value.status_code == 402
                assert "no credit limit" in exc.value.detail

                await ensure_key_usable(db, unlimited)
                await ensure_key_usable(db, capped)

                capped.period_used_usd = 5.0
                with pytest.raises(HTTPException) as exc2:
                    await ensure_key_usable(db, capped)
                assert exc2.value.status_code == 402

                payload = key_to_dict(unlimited)
                assert payload["unlimited_budget"] is True and payload["credit_limit_usd"] == 0.0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_admin_api_refuses_a_key_with_neither_limit_nor_unlimited():
    from app.api.admin import ApiKeyCreate, ApiKeyPatch, create_alpha_router_key, patch_alpha_router_key

    async def run():
        factory, engine = await _db()
        try:
            async with factory() as db:
                admin = User(username="a", email="a@t", hashed_password="x", auth_provider="local", is_active=True)
                db.add(admin)
                await db.commit()

                with pytest.raises(HTTPException) as exc:
                    await create_alpha_router_key(
                        ApiKeyCreate(name="k", owner_user_id=admin.id, credit_limit_usd=0), db, admin
                    )
                assert exc.value.status_code == 400

                created = await create_alpha_router_key(
                    ApiKeyCreate(name="k", owner_user_id=admin.id, credit_limit_usd=0, unlimited_budget=True), db, admin
                )
                key_id = created["id"] if isinstance(created, dict) and "id" in created else None
                if key_id is None:
                    row = (await db.execute(text("SELECT id FROM alpha_router_api_keys WHERE name='k'"))).scalar_one()
                    key_id = int(row)

                # Turning the flag off without giving a limit is refused.
                with pytest.raises(HTTPException) as exc2:
                    await patch_alpha_router_key(key_id, ApiKeyPatch(unlimited_budget=False), db, admin)
                assert exc2.value.status_code == 400
                # Off + a real limit is fine.
                await patch_alpha_router_key(key_id, ApiKeyPatch(unlimited_budget=False, credit_limit_usd=10), db, admin)
                row = await db.get(AlphaRouterApiKey, key_id)
                assert row.unlimited_budget is False and row.credit_limit_usd == 10.0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_backfill_keeps_existing_keys_working():
    """Rows created before the column existed have NULL; the backfill maps old semantics."""
    from app import db_migrate

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                text(
                    "INSERT INTO alpha_router_api_keys (name, key_prefix, key_hash, is_active, credit_limit_usd, unlimited_budget, period_reserved_usd, restrict_connections, restrict_models) "
                    "VALUES ('old-nocap','p1','h1',1,0,NULL,0,0,0), ('old-cap','p2','h2',1,3.5,NULL,0,0,0), ('new','p3','h3',1,0,0,0,0,0)"
                )
            )
        original = db_migrate.engine
        db_migrate.engine = engine
        try:
            await db_migrate.backfill_api_key_unlimited_budget()
            async with engine.connect() as conn:
                rows = dict(
                    (await conn.execute(text("SELECT name, unlimited_budget FROM alpha_router_api_keys"))).all()
                )
            assert bool(rows["old-nocap"]) is True   # kept working, now explicit
            assert bool(rows["old-cap"]) is False
            assert bool(rows["new"]) is False        # explicit values are never touched
        finally:
            db_migrate.engine = original
            await engine.dispose()

    asyncio.run(run())
