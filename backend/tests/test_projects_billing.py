"""Tests for project cost attribution and admin usage reports."""

import asyncio
import datetime

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.logging import RequestLog
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMember,
)
from app.models.user import User
from app.services.project_billing_service import (
    list_projects_usage_overview,
    report_all_projects_usage,
    report_project_usage_by_member,
    report_project_usage_by_model,
    report_project_usage_summary,
)

PROJ_ID = "proj-bill-1"
PROJ_ID_2 = "proj-bill-2"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username):
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _setup(db):
    owner = await _user(db, "owner")
    contrib = await _user(db, "contrib")
    viewer = await _user(db, "viewer")
    db.add(
        Project(
            id=PROJ_ID,
            name="Alpha Project",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ_ID, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=PROJ_ID, user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
    db.add(ProjectMember(project_id=PROJ_ID, user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
    await db.flush()
    return owner, contrib, viewer


async def _log(db, *, project_id, user, model, cost, prompt=10, completion=20, cached=0):
    db.add(
        RequestLog(
            user_id=user.id if user else None,
            username=user.username if user else None,
            model_id=model,
            project_id=project_id,
            total_cost_usd=cost,
            prompt_tokens=prompt,
            completion_tokens=completion,
            cached_tokens=cached,
            request_time=datetime.datetime.utcnow(),
            success=True,
        )
    )
    await db.flush()


def _window():
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=30)
    return start, end


def test_project_usage_summary_aggregates():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                await _log(db, project_id=PROJ_ID, user=owner, model="gpt-4", cost=0.5)
                await _log(db, project_id=PROJ_ID, user=contrib, model="gpt-4", cost=0.3)
                await _log(db, project_id=PROJ_ID, user=contrib, model="claude", cost=0.2)
                start, end = _window()
                df = await report_project_usage_summary(db, PROJ_ID, start, end)
                assert isinstance(df, pd.DataFrame)
                assert len(df) == 1
                row = df.iloc[0]
                assert row["project_id"] == PROJ_ID
                assert row["requests"] == 3
                assert row["total_cost_usd"] == round(0.5 + 0.3 + 0.2, 4)
                assert row["prompt_tokens"] == 30
                assert row["completion_tokens"] == 60
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_project_usage_summary_excludes_other_projects():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                db.add(
                    Project(
                        id=PROJ_ID_2,
                        name="Other",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                await db.flush()
                await _log(db, project_id=PROJ_ID, user=owner, model="gpt-4", cost=0.5)
                await _log(db, project_id=PROJ_ID_2, user=contrib, model="gpt-4", cost=9.9)
                start, end = _window()
                df = await report_project_usage_summary(db, PROJ_ID, start, end)
                assert df.iloc[0]["requests"] == 1
                assert df.iloc[0]["total_cost_usd"] == 0.5
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_project_usage_by_model_breakdown():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                await _log(db, project_id=PROJ_ID, user=owner, model="gpt-4", cost=0.5)
                await _log(db, project_id=PROJ_ID, user=contrib, model="gpt-4", cost=0.3)
                await _log(db, project_id=PROJ_ID, user=contrib, model="claude", cost=0.2)
                start, end = _window()
                df = await report_project_usage_by_model(db, PROJ_ID, start, end)
                assert len(df) == 2
                gpt_row = df[df["model"] == "gpt-4"].iloc[0]
                assert gpt_row["cost_usd"] == round(0.5 + 0.3, 4)
                assert gpt_row["requests"] == 2
                claude_row = df[df["model"] == "claude"].iloc[0]
                assert claude_row["cost_usd"] == 0.2
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_project_usage_by_member_marks_revoked():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup(db)
                await _log(db, project_id=PROJ_ID, user=owner, model="gpt-4", cost=0.5)
                await _log(db, project_id=PROJ_ID, user=contrib, model="gpt-4", cost=0.3)
                # viewer made a request but is later removed
                await _log(db, project_id=PROJ_ID, user=viewer, model="gpt-4", cost=0.1)
                await db.execute(
                    ProjectMember.__table__.delete().where(
                        ProjectMember.project_id == PROJ_ID,
                        ProjectMember.user_id == viewer.id,
                    )
                )
                await db.flush()
                start, end = _window()
                df = await report_project_usage_by_member(db, PROJ_ID, start, end)
                assert len(df) == 3
                revoked_rows = df[df["is_member"] == False]
                assert len(revoked_rows) == 1
                assert revoked_rows.iloc[0]["username"] == "<revoked>"
                assert pd.isna(revoked_rows.iloc[0]["user_id"])
                member_rows = df[df["is_member"] == True]
                assert set(member_rows["username"]) == {"owner", "contrib"}
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_all_projects_usage_summary():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                db.add(
                    Project(
                        id=PROJ_ID_2,
                        name="Beta Project",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                await db.flush()
                await _log(db, project_id=PROJ_ID, user=owner, model="gpt-4", cost=0.5)
                await _log(db, project_id=PROJ_ID_2, user=contrib, model="gpt-4", cost=1.2)
                start, end = _window()
                df = await report_all_projects_usage(db, start, end)
                assert len(df) == 2
                by_id = df.set_index("project_id")
                assert by_id.loc[PROJ_ID, "project_name"] == "Alpha Project"
                assert by_id.loc[PROJ_ID, "cost_usd"] == 0.5
                assert by_id.loc[PROJ_ID_2, "project_name"] == "Beta Project"
                assert by_id.loc[PROJ_ID_2, "cost_usd"] == 1.2
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_projects_usage_overview_includes_zero_spend():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                db.add(
                    Project(
                        id=PROJ_ID_2,
                        name="Beta Project",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                await db.flush()
                await _log(db, project_id=PROJ_ID, user=owner, model="gpt-4", cost=0.5)
                start, end = _window()
                rows = await list_projects_usage_overview(db, start, end)
                by_id = {r["id"]: r for r in rows}
                assert PROJ_ID in by_id
                assert PROJ_ID_2 in by_id
                assert by_id[PROJ_ID]["costUsd"] == 0.5
                assert by_id[PROJ_ID_2]["costUsd"] == 0
                assert by_id[PROJ_ID_2]["requests"] == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_project_usage_summary_unknown_project_raises():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                start, end = _window()
                try:
                    await report_project_usage_summary(db, "no-such-proj", start, end)
                    assert False, "expected ValueError"
                except ValueError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_unattributed_logs_excluded_from_all_projects():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                # A regular (non-project) request log
                await _log(db, project_id=None, user=owner, model="gpt-4", cost=99.0)
                start, end = _window()
                df = await report_all_projects_usage(db, start, end)
                assert df.empty
        finally:
            await engine.dispose()

    asyncio.run(run())
