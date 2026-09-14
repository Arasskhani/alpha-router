"""Step 2 tests: project media access capabilities."""

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
from app.models.user import User
from app.services.project_access_service import (
    require_capability,
    resolve_project_access,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROJ = "media-acl-1"


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username, *, active=True):
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=active,
    )
    db.add(u)
    await db.flush()
    return u


async def _setup(db):
    owner = await _user(db, "owner")
    contrib = await _user(db, "contrib")
    viewer = await _user(db, "viewer")
    db.add(Project(id=PROJ, name="P", status="active", visibility="private",
                   created_by_user_id=owner.id, revision=1, acl_version=1))
    db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=PROJ, user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
    db.add(ProjectMember(project_id=PROJ, user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
    await db.flush()
    return owner, contrib, viewer


def test_viewer_cannot_upload_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup(db)
                from fastapi import HTTPException

                try:
                    await require_capability(db, project_id=PROJ, user=viewer, capability="media.upload")
                    assert False, "viewer should not upload"
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_contributor_can_upload_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup(db)
                access = await require_capability(db, project_id=PROJ, user=contrib, capability="media.upload")
                assert access is not None
                assert access.can("media.upload")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_owner_can_upload_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup(db)
                access = await require_capability(db, project_id=PROJ, user=owner, capability="media.upload")
                assert access is not None
                assert access.can("media.upload")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_contributor_has_media_delete_capability():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup(db)
                access = await require_capability(db, project_id=PROJ, user=contrib, capability="media.delete")
                assert access is not None
                assert access.can("media.delete")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_viewer_cannot_delete_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup(db)
                from fastapi import HTTPException

                try:
                    await require_capability(db, project_id=PROJ, user=viewer, capability="media.delete")
                    assert False
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_owner_can_delete_any_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup(db)
                access = await require_capability(db, project_id=PROJ, user=owner, capability="media.delete")
                assert access.can("media.delete")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_public_viewer_can_read_but_not_upload():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                db.add(Project(id=PROJ, name="P", status="active", visibility="public",
                               created_by_user_id=owner.id, revision=1, acl_version=1))
                db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                await db.flush()
                outsider = await _user(db, "outsider")
                access = await resolve_project_access(db, project_id=PROJ, user=outsider)
                assert access is not None
                assert access.role == "viewer"
                assert access.is_public_viewer is True
                assert not access.can("media.upload")
                assert not access.can("media.delete")
                # read is implicit via project.view
                assert access.can("project.view")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_inactive_user_denied_media_access():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup(db)
                contrib.is_active = False
                await db.flush()
                from fastapi import HTTPException

                try:
                    await require_capability(db, project_id=PROJ, user=contrib, capability="media.upload")
                    assert False
                except HTTPException as e:
                    assert e.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())
