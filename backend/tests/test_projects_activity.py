"""Access control for project Activity."""

import asyncio

import app.models  # noqa: F401
from app.database import Base
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMember,
)
from app.models.user import User, UserRoleAssignment
from app.services.project_access_service import can_view_project_activity
from app.services.rbac import REPORTS_ACCESS_SLUG, USER_SLUG
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJ_ID = "proj-activity-1"


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username, *roles: str):
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    slugs = roles or (USER_SLUG,)
    for slug in slugs:
        db.add(UserRoleAssignment(user_id=user.id, role_slug=slug))
    await db.flush()
    return user


async def _project(db, owner):
    project = Project(
        id=PROJ_ID,
        name="Act",
        status="active",
        visibility="private",
        created_by_user_id=owner.id,
        revision=1,
        acl_version=1,
    )
    db.add(project)
    db.add(ProjectMember(project_id=PROJ_ID, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    await db.flush()
    return project


def test_owner_can_view_activity():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                await _project(db, owner)
                assert await can_view_project_activity(db, project_id=PROJ_ID, user=owner) is True
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_contributor_cannot_view_activity():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                contrib = await _user(db, "contrib")
                await _project(db, owner)
                db.add(
                    ProjectMember(
                        project_id=PROJ_ID,
                        user_id=contrib.id,
                        role=PROJECT_ROLE_CONTRIBUTOR,
                    )
                )
                await db.flush()
                assert await can_view_project_activity(db, project_id=PROJ_ID, user=contrib) is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_viewer_cannot_view_activity():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                viewer = await _user(db, "viewer")
                await _project(db, owner)
                db.add(
                    ProjectMember(
                        project_id=PROJ_ID,
                        user_id=viewer.id,
                        role=PROJECT_ROLE_VIEWER,
                    )
                )
                await db.flush()
                assert await can_view_project_activity(db, project_id=PROJ_ID, user=viewer) is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_reports_admin_can_view_activity_without_membership():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                admin = await _user(db, "reports-admin", REPORTS_ACCESS_SLUG)
                await _project(db, owner)
                assert await can_view_project_activity(db, project_id=PROJ_ID, user=admin) is True
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_outsider_cannot_view_activity():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                stranger = await _user(db, "stranger")
                await _project(db, owner)
                assert await can_view_project_activity(db, project_id=PROJ_ID, user=stranger) is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_project_activity_routes_import():
    from app.api.projects import project_activity, project_activity_export

    assert project_activity.__name__ == "project_activity"
    assert project_activity_export.__name__ == "project_activity_export"
