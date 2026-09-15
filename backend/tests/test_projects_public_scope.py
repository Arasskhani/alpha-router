"""Public projects share chats and knowledge, nothing else.

A non-member of a public project (implicit viewer) may list chats and
resources; memory, media, the member roster, invitations and the active
config (custom prompt) answer 403. Explicit *viewer members* keep all read
access. Switching a project to public requires echoing its name back.
"""

from __future__ import annotations


import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.project import (
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectAuditEvent,
    ProjectMember,
)
from app.models.user import User
from app.services.project_access_service import (
    MEMBER_READ_CAPABILITIES,
    PUBLIC_VIEWER_CAPABILITIES,
    resolve_project_access,
)
from app.services.project_chat_service import list_project_chat_sessions
from app.services.project_config_service import get_active_config
from app.services.project_media_service import list_project_media
from app.services.project_memory_service import create_project_memory, list_project_memories
from app.services.project_resource_service import list_project_resources
from app.services.project_service import (
    ProjectValidationError,
    list_invitable_users,
    list_invitations,
    list_members,
    update_project,
)

PROJ = "pub-scope-1"


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username):
    u = User(username=username, email=f"{username}@test", hashed_password="x", auth_provider="local", is_active=True)
    db.add(u)
    await db.flush()
    return u


async def _public_project(db):
    owner = await _user(db, "owner")
    viewer = await _user(db, "viewer_member")
    outsider = await _user(db, "outsider")
    db.add(
        Project(
            id=PROJ,
            name="Shared notes",
            status="active",
            visibility="public",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=PROJ, user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
    await db.flush()
    await create_project_memory(db, project_id=PROJ, user=owner, content="Budget code is 4711")
    return owner, viewer, outsider


async def _expect_403(coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    assert exc.value.status_code == 403


def test_capability_sets_are_consistent():
    assert PUBLIC_VIEWER_CAPABILITIES < MEMBER_READ_CAPABILITIES
    assert {"project.view", "chat.read", "resource.read"} == set(PUBLIC_VIEWER_CAPABILITIES)


async def test_public_viewer_reads_chats_and_resources_only():
    factory, engine = await _factory()
    try:
        async with factory() as db:
            owner, viewer, outsider = await _public_project(db)

            access = await resolve_project_access(db, project_id=PROJ, user=outsider)
            assert access is not None and access.is_public_viewer
            assert access.can("chat.read") and access.can("resource.read")
            for cap in ("memory.read", "media.read", "members.read", "config.read"):
                assert not access.can(cap), cap

            # Allowed.
            assert await list_project_chat_sessions(db, project_id=PROJ, user=outsider) is not None
            assert await list_project_resources(db, project_id=PROJ, user=outsider) is not None

            # Members-only.
            await _expect_403(list_project_memories(db, project_id=PROJ, user=outsider))
            await _expect_403(list_project_media(db, project_id=PROJ, user=outsider))
            await _expect_403(list_members(db, project_id=PROJ, user=outsider))
            await _expect_403(get_active_config(db, project_id=PROJ, user=outsider))
            await _expect_403(list_invitations(db, project_id=PROJ, user=outsider))
            await _expect_403(list_invitable_users(db, project_id=PROJ, user=outsider))

            # An explicit viewer *member* still reads everything.
            items, total = await list_project_memories(db, project_id=PROJ, user=viewer)
            assert total == 1 and "4711" in items[0]["content"]
            assert await list_project_media(db, project_id=PROJ, user=viewer) is not None
            assert len(await list_members(db, project_id=PROJ, user=viewer)) == 2
            assert await get_active_config(db, project_id=PROJ, user=viewer) is not None
            # ...but does not manage members: invitations stay with owners.
            await _expect_403(list_invitations(db, project_id=PROJ, user=viewer))
    finally:
        await engine.dispose()


async def test_public_viewer_chat_does_not_receive_project_memory():
    factory, engine = await _factory()
    try:
        async with factory() as db:
            owner, viewer, outsider = await _public_project(db)
            from app.models.chat import ChatSession
            from app.services.project_turn_planner import plan_project_turn

            sess = ChatSession(
                id="pub-scope-sess",
                user_id=outsider.id,
                project_id=PROJ,
                title="t",
            )
            db.add(sess)
            await db.flush()
            msgs = [{"role": "user", "content": "what is the budget code?"}]

            as_outsider = await plan_project_turn(db, msgs, user_id=outsider.id, chat_session_id=sess.id)
            assert "4711" not in "\n".join(str(m.get("content", "")) for m in as_outsider)

            sess_member = ChatSession(
                id="pub-scope-sess-2",
                user_id=viewer.id,
                project_id=PROJ,
                title="t",
            )
            db.add(sess_member)
            await db.flush()
            as_member = await plan_project_turn(db, msgs, user_id=viewer.id, chat_session_id=sess_member.id)
            assert "4711" in "\n".join(str(m.get("content", "")) for m in as_member)
    finally:
        await engine.dispose()


async def test_going_public_requires_typed_name_and_is_audited():
    factory, engine = await _factory()
    try:
        async with factory() as db:
            owner = await _user(db, "o2")
            db.add(
                Project(
                    id="priv-1",
                    name="Quarterly plan",
                    status="active",
                    visibility="private",
                    created_by_user_id=owner.id,
                    revision=1,
                    acl_version=1,
                )
            )
            db.add(ProjectMember(project_id="priv-1", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            await db.flush()

            with pytest.raises(ProjectValidationError, match="confirm_public_name"):
                await update_project(db, project_id="priv-1", user=owner, visibility="public")
            with pytest.raises(ProjectValidationError):
                await update_project(
                    db,
                    project_id="priv-1",
                    user=owner,
                    visibility="public",
                    confirm_public_name="quarterly plan",  # case matters: it is a typed confirmation
                )
            assert (await db.get(Project, "priv-1")).visibility == "private"

            out = await update_project(
                db,
                project_id="priv-1",
                user=owner,
                visibility="public",
                confirm_public_name="Quarterly plan",
            )
            assert out["visibility"] == "public"
            events = (
                (await db.execute(select(ProjectAuditEvent.event_type).where(ProjectAuditEvent.project_id == "priv-1")))
                .scalars()
                .all()
            )
            assert "project.visibility.public" in events

            # Back to private and other edits never need the confirmation.
            await update_project(db, project_id="priv-1", user=owner, visibility="private")
            await update_project(db, project_id="priv-1", user=owner, description="notes")
    finally:
        await engine.dispose()
