"""Admin Users list: effective plan filter and CSV export."""

from __future__ import annotations

import csv
import io

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.admin import router as admin_router
from app.api.deps import require_users
from app.database import Base, get_db, get_read_db
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.user import User, UserGroup, user_group_members


def _names(payload: list[dict]) -> set[str]:
    return {row["username"] for row in payload}


async def _setup():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        gold = BudgetPlan(name="Gold", monthly_budget_usd=100.0)
        silver = BudgetPlan(name="Silver", monthly_budget_usd=40.0)
        eng = UserGroup(name="Engineering", source="local")
        admin = User(
            username="admin-viewer",
            email="admin@alpha-router.local",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        assigned_gold = User(
            username="assigned-gold",
            email="assigned-gold@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        inherit_group = User(
            username="inherit-group-gold",
            email="inherit-group@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        inherit_dept = User(
            username="inherit-dept-gold",
            email="inherit-dept@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
            department="IT",
        )
        assigned_silver = User(
            username="assigned-silver",
            email="assigned-silver@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        override_silver = User(
            username="group-gold-assigned-silver",
            email="override-silver@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        blocked_none = User(
            username="group-gold-no-plan",
            email="blocked-none@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        leftover = User(
            username="no-effective-plan",
            email="leftover@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        db.add_all(
            [
                gold,
                silver,
                eng,
                admin,
                assigned_gold,
                inherit_group,
                inherit_dept,
                assigned_silver,
                override_silver,
                blocked_none,
                leftover,
            ]
        )
        await db.flush()
        db.add_all(
            [
                PlanAssignment(plan_id=gold.id, user_id=assigned_gold.id),
                PlanAssignment(plan_id=silver.id, user_id=assigned_silver.id),
                PlanAssignment(plan_id=silver.id, user_id=override_silver.id),
                PlanAssignment(plan_id=None, user_id=blocked_none.id),
                PlanAssignment(plan_id=gold.id, group_id=eng.id),
                PlanAssignment(plan_id=gold.id, department="IT"),
            ]
        )
        await db.execute(
            user_group_members.insert().values(
                [
                    {"user_id": inherit_group.id, "group_id": eng.id},
                    {"user_id": override_silver.id, "group_id": eng.id},
                    {"user_id": blocked_none.id, "group_id": eng.id},
                ]
            )
        )
        await db.commit()
        ids = {
            "admin": admin.id,
            "gold": gold.id,
            "silver": silver.id,
        }

    async def override_db():
        async with factory() as session:
            yield session

    async def override_user():
        async with factory() as session:
            return await session.get(User, ids["admin"])

    api = FastAPI()
    api.include_router(admin_router)
    api.dependency_overrides[get_db] = override_db
    api.dependency_overrides[get_read_db] = override_db
    api.dependency_overrides[require_users] = override_user
    return engine, api, ids


async def _flow() -> None:
    engine, api, ids = await _setup()
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        gold = await client.get(f"/api/admin/users?plan_id={ids['gold']}")
        assert gold.status_code == 200
        assert _names(gold.json()) == {
            "assigned-gold",
            "inherit-group-gold",
            "inherit-dept-gold",
        }

        silver = await client.get(f"/api/admin/users?plan_id={ids['silver']}")
        assert silver.status_code == 200
        assert _names(silver.json()) == {
            "assigned-silver",
            "group-gold-assigned-silver",
        }

        none = await client.get("/api/admin/users?no_plan=true")
        assert none.status_code == 200
        assert _names(none.json()) == {
            "admin-viewer",
            "group-gold-no-plan",
            "no-effective-plan",
        }

        combined = await client.get(f"/api/admin/users?plan_id={ids['gold']}&department=IT")
        assert combined.status_code == 200
        assert _names(combined.json()) == {"inherit-dept-gold"}

        conflict = await client.get(f"/api/admin/users?plan_id={ids['gold']}&no_plan=true")
        assert conflict.status_code == 400

        exported = await client.get(f"/api/admin/users/export?plan_id={ids['gold']}")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("text/csv")
        raw = exported.content
        assert raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        assert [row["Username"] for row in rows] == [
            "assigned-gold",
            "inherit-dept-gold",
            "inherit-group-gold",
        ]
        by_name = {row["Username"]: row for row in rows}
        assert by_name["assigned-gold"]["User Plan"] == "Gold"
        assert by_name["assigned-gold"]["Plan Source"] == "assigned"
        assert by_name["inherit-group-gold"]["User Plan"] == "Gold"
        assert by_name["inherit-group-gold"]["Plan Source"] == "group"
        assert by_name["inherit-dept-gold"]["User Plan"] == "Gold"
        assert by_name["inherit-dept-gold"]["Plan Source"] == "department"

    await engine.dispose()


async def test_users_effective_plan_filter_and_csv_export():
    await _flow()
