"""Tests for project lifecycle, membership, and invitation management."""

import asyncio

import app.models  # noqa: F401
from app.database import Base
from app.models.project import (
    PROJECT_STATUS_DELETION_PENDING,
    Project,
    ProjectMember,
)
from app.models.user import User
from app.services.project_access_service import ProjectAccessError
from app.services.project_service import (
    ProjectValidationError,
    add_member,
    claim_invitation,
    create_invitation,
    create_project,
    delete_project,
    get_project,
    leave_project,
    list_invitable_users,
    list_members,
    list_my_projects,
    list_public_projects,
    remove_member,
    revoke_invitation,
    update_member_role,
    update_project,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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


def test_create_project_makes_creator_owner():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                proj = await create_project(db, user=owner, name="Alpha")
                # The creator becomes the (single, non-assignable) Primary Owner.
                assert proj["myRole"] == "primary_owner"
                assert proj["isMember"] is True
                assert proj["visibility"] == "private"
                members = await db.execute(
                    ProjectMember.__table__.select()
                )
                rows = members.all()
                assert len(rows) == 1
                assert rows[0].role == "primary_owner"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_create_project_rejects_empty_name():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                try:
                    await create_project(db, user=owner, name="  ")
                    assert False, "expected error"
                except ProjectValidationError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_get_project_hidden_from_non_member_when_private():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                other = await _user(db, "other")
                await create_project(db, user=owner, name="Alpha")
                proj = await get_project(db, project_id="nope", user=other)
                assert proj is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_my_projects_only_returns_memberships():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                other = await _user(db, "other")
                await create_project(db, user=owner, name="Alpha")
                await create_project(db, user=owner, name="Beta")
                mine, total = await list_my_projects(db, user=owner)
                assert total == 2
                assert {p["name"] for p in mine} == {"Alpha", "Beta"}
                other_mine, other_total = await list_my_projects(db, user=other)
                assert other_total == 0
                assert other_mine == []
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_public_projects_excludes_members():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                other = await _user(db, "other")
                await create_project(db, user=owner, name="Pub", visibility="public")
                await create_project(db, user=owner, name="Priv", visibility="private")
                rows, total = await list_public_projects(db, user=other)
                assert total == 1
                assert rows[0]["name"] == "Pub"
                # owner is a member, so Pub should not appear in owner's explore
                owner_rows, owner_total = await list_public_projects(db, user=owner)
                assert owner_total == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_update_project_owner_only():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                contrib = await _user(db, "contrib")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                await add_member(db, project_id=pid, user=owner, target_user_id=contrib.id, role="contributor")
                updated = await update_project(db, project_id=pid, user=owner, name="Alpha2", visibility="public")
                assert updated["name"] == "Alpha2"
                assert updated["visibility"] == "public"
                # contributor cannot edit
                from fastapi import HTTPException
                try:
                    await update_project(db, project_id=pid, user=contrib, name="Hack")
                    assert False
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_project_soft_deletes():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                ok = await delete_project(db, project_id=pid, user=owner)
                assert ok is True
                row = await db.get(Project, pid)
                assert row.status == PROJECT_STATUS_DELETION_PENDING
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_leave_project_blocks_last_owner():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                try:
                    await leave_project(db, project_id=pid, user=owner)
                    assert False, "expected block"
                except ProjectAccessError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_leave_project_allows_non_owner():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                contrib = await _user(db, "contrib")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                await add_member(db, project_id=pid, user=owner, target_user_id=contrib.id, role="contributor")
                left = await leave_project(db, project_id=pid, user=contrib)
                assert left is True
                member = await db.get(ProjectMember, (pid, contrib.id))
                assert member is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_add_member_and_update_role():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                contrib = await _user(db, "contrib")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                m = await add_member(db, project_id=pid, user=owner, target_user_id=contrib.id, role="viewer")
                assert m["role"] == "viewer"
                m2 = await update_member_role(db, project_id=pid, user=owner, target_user_id=contrib.id, role="contributor")
                assert m2["role"] == "contributor"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_update_member_role_blocks_demote_last_owner():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                try:
                    await update_member_role(db, project_id=pid, user=owner, target_user_id=owner.id, role="viewer")
                    assert False
                except ProjectAccessError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_remove_member_blocks_last_owner():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                try:
                    await remove_member(db, project_id=pid, user=owner, target_user_id=owner.id)
                    assert False
                except ProjectAccessError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_invitable_users_excludes_members():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                contrib = await _user(db, "contrib")
                outsider = await _user(db, "outsider")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                await add_member(db, project_id=pid, user=owner, target_user_id=contrib.id, role="contributor")
                users = await list_invitable_users(db, project_id=pid, user=owner)
                ids = [u["id"] for u in users]
                assert owner.id not in ids
                assert contrib.id not in ids
                assert outsider.id in ids
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_invitation_create_claim_revoke():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                invitee = await _user(db, "invitee")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                inv = await create_invitation(db, project_id=pid, user=owner, role="contributor")
                assert "token" in inv
                token = inv["token"]
                # claim
                claimed = await claim_invitation(db, token=token, user=invitee)
                assert claimed is not None
                assert claimed["myRole"] == "contributor"
                assert claimed["isMember"] is True
                # re-claim idempotent (already member) but exhausts
                again = await claim_invitation(db, token=token, user=invitee)
                assert again is not None
                # exhausted for a new user
                user3 = await _user(db, "user3")
                try:
                    await claim_invitation(db, token=token, user=user3)
                    assert False
                except ProjectValidationError:
                    pass
                # revoke
                inv2 = await create_invitation(db, project_id=pid, user=owner, role="viewer")
                ok = await revoke_invitation(db, project_id=pid, invitation_id=inv2["id"], user=owner)
                assert ok is True
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_invitation_rejects_owner_role():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                try:
                    await create_invitation(db, project_id=pid, user=owner, role="owner")
                    assert False
                except ValueError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_members_returns_all():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                contrib = await _user(db, "contrib")
                proj = await create_project(db, user=owner, name="Alpha")
                pid = proj["id"]
                await add_member(db, project_id=pid, user=owner, target_user_id=contrib.id, role="viewer")
                members = await list_members(db, project_id=pid, user=owner)
                assert len(members) == 2
                roles = {m["role"] for m in members}
                assert roles == {"primary_owner", "viewer"}
        finally:
            await engine.dispose()

    asyncio.run(run())
