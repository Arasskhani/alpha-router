"""Isolation, ACL, and brief-only handoff for project Rooms."""

import asyncio

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import CHANNEL_KIND_MEMBER, ChatMessage, ChatSession
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    PROJECT_VISIBILITY_PRIVATE,
    PROJECT_VISIBILITY_PUBLIC,
    Project,
    ProjectMember,
    ProjectMemory,
    ProjectRoomHandoff,
)
from app.models.user import User
from app.services.chat_channel_guard import (
    ROOM_SESSION_NOT_ALLOWED,
    assert_session_allows_model_generation,
)
from app.services.project_chat_service import (
    get_project_chat_session,
    list_project_chat_sessions,
    sync_project_chats,
)
from app.services.project_memory_service import create_project_memory, list_project_memories
from app.services.project_room_service import (
    append_project_room_message,
    create_project_room,
    create_room_handoff,
    delete_project_room_message,
    list_project_room_messages,
    list_project_rooms,
    update_project_room_message,
)
from app.services.project_turn_planner import plan_project_turn

PROJ_ID = "proj-rooms-1"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username, *, active=True):
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def _setup_project(db, *, visibility=PROJECT_VISIBILITY_PRIVATE):
    owner = await _user(db, "owner")
    contrib = await _user(db, "contrib")
    viewer = await _user(db, "viewer")
    db.add(
        Project(
            id=PROJ_ID,
            name="Rooms",
            status="active",
            visibility=visibility,
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


def test_member_session_cannot_call_completions():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                room = await create_project_room(db, project_id=PROJ_ID, user=owner, title="Teaser")
                assert room is not None
                row = await db.get(ChatSession, room["id"])
                assert row.channel_kind == CHANNEL_KIND_MEMBER
                try:
                    await assert_session_allows_model_generation(db, room["id"])
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
                    assert exc.detail["code"] == ROOM_SESSION_NOT_ALLOWED
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_rooms_do_not_appear_in_project_chats():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                room = await create_project_room(db, project_id=PROJ_ID, user=owner, title="Hidden")
                listed = await list_project_chat_sessions(db, project_id=PROJ_ID, user=owner)
                assert listed is not None
                sessions, total = listed
                assert total == 0
                assert sessions == []
                assert await get_project_chat_session(
                    db, project_id=PROJ_ID, session_id=room["id"], user=owner
                ) is None
                sync = await sync_project_chats(
                    db, project_id=PROJ_ID, user=owner, session_id=room["id"]
                )
                assert sync is not None
                assert sync["sessions"] == []
                assert sync["goneSessionId"] == room["id"]
                assert sync["messages"] == []
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_public_non_member_cannot_list_rooms():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, visibility=PROJECT_VISIBILITY_PUBLIC)
                await create_project_room(db, project_id=PROJ_ID, user=owner, title="Private room")
                stranger = await _user(db, "stranger")
                assert await list_project_rooms(db, project_id=PROJ_ID, user=stranger) is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_viewer_member_can_read_but_not_write_or_handoff():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, viewer = await _setup_project(db)
                room = await create_project_room(db, project_id=PROJ_ID, user=owner, title="Read me")
                await append_project_room_message(
                    db, project_id=PROJ_ID, room_id=room["id"], user=owner, content="hello"
                )
                listed = await list_project_rooms(db, project_id=PROJ_ID, user=viewer)
                assert listed is not None
                rooms, total = listed
                assert total == 1
                assert rooms[0]["id"] == room["id"]
                messages = await list_project_room_messages(
                    db, project_id=PROJ_ID, room_id=room["id"], user=viewer
                )
                assert messages is not None
                assert messages[0][0]["content"] == "hello"
                assert messages[0][0]["userId"] == owner.id
                try:
                    await append_project_room_message(
                        db, project_id=PROJ_ID, room_id=room["id"], user=viewer, content="nope"
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
                try:
                    await create_room_handoff(
                        db,
                        project_id=PROJ_ID,
                        room_id=room["id"],
                        user=viewer,
                        brief="Ship the teaser",
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_contributor_rooms_do_not_leak_messages():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, contrib, _ = await _setup_project(db)
                teaser = await create_project_room(
                    db, project_id=PROJ_ID, user=contrib, title="Nowruz teaser"
                )
                campaign = await create_project_room(
                    db, project_id=PROJ_ID, user=contrib, title="Instagram campaign"
                )
                await append_project_room_message(
                    db, project_id=PROJ_ID, room_id=teaser["id"], user=contrib, content="teaser only"
                )
                await append_project_room_message(
                    db,
                    project_id=PROJ_ID,
                    room_id=campaign["id"],
                    user=contrib,
                    content="campaign only",
                )
                teaser_msgs, _ = await list_project_room_messages(
                    db, project_id=PROJ_ID, room_id=teaser["id"], user=contrib
                )
                campaign_msgs, _ = await list_project_room_messages(
                    db, project_id=PROJ_ID, room_id=campaign["id"], user=contrib
                )
                assert [m["content"] for m in teaser_msgs] == ["teaser only"]
                assert [m["content"] for m in campaign_msgs] == ["campaign only"]
                listed, total = await list_project_rooms(db, project_id=PROJ_ID, user=contrib)
                assert total == 2
                assert {row["id"] for row in listed} == {teaser["id"], campaign["id"]}
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_handoff_creates_ai_session_from_brief_only():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db)
                room = await create_project_room(db, project_id=PROJ_ID, user=contrib, title="Teaser")
                await append_project_room_message(
                    db, project_id=PROJ_ID, room_id=room["id"], user=contrib, content="long debate"
                )
                brief = "Approve the 15s Nowruz teaser."
                result = await create_room_handoff(
                    db,
                    project_id=PROJ_ID,
                    room_id=room["id"],
                    user=contrib,
                    brief=brief,
                    title="Teaser chat",
                )
                assert result is not None
                assert result["sourceRoomId"] == room["id"]
                assert result["brief"] == brief
                target = await db.get(ChatSession, result["targetSessionId"])
                assert target is not None
                assert target.channel_kind == "ai"
                assert target.project_id == PROJ_ID
                first = (
                    await db.execute(
                        select(ChatMessage)
                        .where(ChatMessage.session_id == target.id)
                        .order_by(ChatMessage.sequence.asc())
                    )
                ).scalars().all()
                assert first == []
                assert target.message_count == 0
                handoff = (
                    await db.execute(
                        select(ProjectRoomHandoff).where(
                            ProjectRoomHandoff.target_session_id == target.id
                        )
                    )
                ).scalar_one()
                assert handoff.brief == brief
                chats, total = await list_project_chat_sessions(db, project_id=PROJ_ID, user=owner)
                assert total == 1
                assert chats[0]["id"] == target.id
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_room_messages_do_not_create_project_memory():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db)
                room = await create_project_room(db, project_id=PROJ_ID, user=contrib)
                await append_project_room_message(
                    db, project_id=PROJ_ID, room_id=room["id"], user=contrib, content="do not memorize"
                )
                count = int(
                    (
                        await db.execute(
                            select(func.count())
                            .select_from(ProjectMemory)
                            .where(ProjectMemory.project_id == PROJ_ID)
                        )
                    ).scalar_one()
                    or 0
                )
                assert count == 0
                created = await create_project_memory(
                    db, project_id=PROJ_ID, user=owner, content="explicit memory"
                )
                assert created is not None
                memories = await list_project_memories(db, project_id=PROJ_ID, user=owner)
                assert memories is not None
                assert any(row.get("content") == "explicit memory" for row in memories[0])
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_planner_skips_member_rooms():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                from app.services.project_config_service import update_project_config

                await update_project_config(
                    db,
                    project_id=PROJ_ID,
                    user=owner,
                    custom_prompt="Always greet as ProjectBot.",
                    memory_enabled=True,
                )
                room = await create_project_room(db, project_id=PROJ_ID, user=owner)
                messages = [{"role": "user", "content": "hi"}]
                out = await plan_project_turn(
                    db,
                    messages,
                    user_id=owner.id,
                    chat_session_id=room["id"],
                )
                assert out == messages
                joined = "\n".join(
                    str(item.get("content") or "") for item in out if isinstance(item, dict)
                )
                assert "ProjectBot" not in joined
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_sender_can_edit_and_delete_own_message():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db)
                room = await create_project_room(db, project_id=PROJ_ID, user=contrib)
                posted = await append_project_room_message(
                    db, project_id=PROJ_ID, room_id=room["id"], user=contrib, content="draft"
                )
                assert posted["mine"] is True
                edited = await update_project_room_message(
                    db,
                    project_id=PROJ_ID,
                    room_id=room["id"],
                    message_id=posted["id"],
                    user=contrib,
                    content="final",
                )
                assert edited["content"] == "final"
                assert edited["edited"] is True
                try:
                    await update_project_room_message(
                        db,
                        project_id=PROJ_ID,
                        room_id=room["id"],
                        message_id=posted["id"],
                        user=owner,
                        content="hijack",
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
                assert await delete_project_room_message(
                    db,
                    project_id=PROJ_ID,
                    room_id=room["id"],
                    message_id=posted["id"],
                    user=contrib,
                )
                leftover, _ = await list_project_room_messages(
                    db, project_id=PROJ_ID, room_id=room["id"], user=contrib
                )
                assert leftover == []
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_reply_stores_parent_snippet():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, contrib, _ = await _setup_project(db)
                room = await create_project_room(db, project_id=PROJ_ID, user=contrib)
                parent = await append_project_room_message(
                    db, project_id=PROJ_ID, room_id=room["id"], user=contrib, content="original idea"
                )
                reply = await append_project_room_message(
                    db,
                    project_id=PROJ_ID,
                    room_id=room["id"],
                    user=contrib,
                    content="agree",
                    reply_to_message_id=parent["id"],
                )
                assert reply["replyToMessageId"] == parent["id"]
                assert reply["replyToContent"] == "original idea"
        finally:
            await engine.dispose()

    asyncio.run(run())
