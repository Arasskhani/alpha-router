"""Tests for project-scoped shared chat: create, list, append, pin/unpin, and ACL."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatSession
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    PROJECT_VISIBILITY_PRIVATE,
    PROJECT_VISIBILITY_PUBLIC,
    Project,
    ProjectChatPin,
    ProjectMember,
)
from app.models.user import User
from app.services.project_chat_service import (
    append_project_chat_message,
    create_project_chat_session,
    delete_project_chat_session,
    list_pinned_chats,
    list_project_chat_messages,
    list_project_chat_sessions,
    pin_project_chat,
    unpin_project_chat,
)
from app.services.user_chat_storage_service import list_session_messages

PROJ_ID = "proj-chat-1"


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username, *, active=True):
    user = User(
        username=username, email=f"{username}@test", hashed_password="x", auth_provider="local", is_active=active
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
            name="Test",
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


async def test_create_chat_owner():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="T")
            assert s is not None
            assert s["title"] == "T"
            assert s["pinned"] is False
            row = await db.get(ChatSession, s["id"])
            assert row.project_id == PROJ_ID
            assert row.private_mode is False
    finally:
        await engine.dispose()


async def test_create_chat_contributor():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            _, contrib, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=contrib)
            assert s is not None
    finally:
        await engine.dispose()


async def test_create_chat_viewer_denied():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            _, _, viewer = await _setup_project(db)
            from fastapi import HTTPException

            try:
                await create_project_chat_session(db, project_id=PROJ_ID, user=viewer)
                pytest.fail("expected an exception")
            except HTTPException as exc:
                assert exc.status_code == 403
    finally:
        await engine.dispose()


async def test_create_chat_non_member_hidden():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            _, _, _ = await _setup_project(db)
            stranger = await _user(db, "stranger")
            from fastapi import HTTPException

            try:
                await create_project_chat_session(db, project_id=PROJ_ID, user=stranger)
                pytest.fail("expected an exception")
            except HTTPException as exc:
                assert exc.status_code == 404
    finally:
        await engine.dispose()


async def test_list_chats():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="A")
            await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="B")
            result = await list_project_chat_sessions(db, project_id=PROJ_ID, user=owner)
            assert result is not None
            sessions, total = result
            assert total == 2
            assert len(sessions) == 2
    finally:
        await engine.dispose()


async def test_list_chats_pinned_first():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            older = await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="Older")
            newer = await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="Newer")
            await pin_project_chat(db, project_id=PROJ_ID, session_id=older["id"], user=owner)
            result = await list_project_chat_sessions(db, project_id=PROJ_ID, user=owner)
            assert result is not None
            sessions, _total = result
            assert sessions[0]["id"] == older["id"]
            assert sessions[0]["pinned"] is True
            assert sessions[1]["id"] == newer["id"]
            assert sessions[1]["pinned"] is False
    finally:
        await engine.dispose()


async def test_list_chats_search():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="Sprint")
            await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="Bug")
            result = await list_project_chat_sessions(db, project_id=PROJ_ID, user=owner, q="sprint")
            assert result is not None
            sessions, total = result
            assert total == 1
            assert sessions[0]["title"] == "Sprint"
    finally:
        await engine.dispose()


async def test_list_chats_public_viewer():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db, visibility=PROJECT_VISIBILITY_PUBLIC)
            await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="S")
            stranger = await _user(db, "stranger")
            result = await list_project_chat_sessions(db, project_id=PROJ_ID, user=stranger)
            assert result is not None
            sessions, total = result
            assert total == 1
    finally:
        await engine.dispose()


async def test_append_message_owner():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            msg = await append_project_chat_message(
                db,
                project_id=PROJ_ID,
                session_id=s["id"],
                user=owner,
                role="user",
                content="Hi",
                client_message_id="c1",
            )
            assert msg is not None
            assert msg["content"] == "Hi"
            assert msg["sequence"] == 1
            assert msg["authorDisplayName"] == "owner"
            row = await db.get(ChatSession, s["id"])
            assert row.message_count == 1
            assert row.revision == 2
    finally:
        await engine.dispose()


async def test_append_message_contributor():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            _, contrib, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=contrib)
            msg = await append_project_chat_message(
                db, project_id=PROJ_ID, session_id=s["id"], user=contrib, role="user", content="C"
            )
            assert msg is not None
            assert msg["authorDisplayName"] == "contrib"
    finally:
        await engine.dispose()


async def test_list_session_messages_includes_author_display_name():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, contrib, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            await append_project_chat_message(
                db, project_id=PROJ_ID, session_id=s["id"], user=owner, role="user", content="Hi"
            )
            await append_project_chat_message(
                db, project_id=PROJ_ID, session_id=s["id"], user=contrib, role="user", content="Hello"
            )
            msgs, has_more = await list_session_messages(db, contrib.id, s["id"])
            assert has_more is False
            assert [m["authorDisplayName"] for m in msgs] == ["owner", "contrib"]
            assert [m["content"] for m in msgs] == ["Hi", "Hello"]
    finally:
        await engine.dispose()


async def test_append_message_viewer_denied():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, viewer = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            from fastapi import HTTPException

            try:
                await append_project_chat_message(
                    db, project_id=PROJ_ID, session_id=s["id"], user=viewer, role="user", content="X"
                )
                pytest.fail("expected an exception")
            except HTTPException as exc:
                assert exc.status_code == 403
    finally:
        await engine.dispose()


async def test_append_message_idempotent():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            m1 = await append_project_chat_message(
                db,
                project_id=PROJ_ID,
                session_id=s["id"],
                user=owner,
                role="user",
                content="A",
                client_message_id="dup",
            )
            m2 = await append_project_chat_message(
                db,
                project_id=PROJ_ID,
                session_id=s["id"],
                user=owner,
                role="user",
                content="B",
                client_message_id="dup",
            )
            assert m1["id"] == m2["id"]
            row = await db.get(ChatSession, s["id"])
            assert row.message_count == 1
    finally:
        await engine.dispose()


async def test_message_pagination():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            for i in range(5):
                await append_project_chat_message(
                    db,
                    project_id=PROJ_ID,
                    session_id=s["id"],
                    user=owner,
                    role="user",
                    content=f"m{i}",
                    client_message_id=f"c{i}",
                )
            result = await list_project_chat_messages(db, project_id=PROJ_ID, session_id=s["id"], user=owner, limit=3)
            assert result is not None
            messages, has_more = result
            assert has_more is True
            assert len(messages) == 3
            # Latest 3 messages in ascending order: sequences 3,4,5
            assert messages[0]["sequence"] == 3
            assert messages[2]["sequence"] == 5
            result = await list_project_chat_messages(
                db, project_id=PROJ_ID, session_id=s["id"], user=owner, limit=3, before=4
            )
            messages, has_more = result
            assert len(messages) == 3
            assert messages[0]["sequence"] == 1
            assert has_more is False
    finally:
        await engine.dispose()


async def test_pin_owner():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            result = await pin_project_chat(db, project_id=PROJ_ID, session_id=s["id"], user=owner)
            assert result is not None
            assert result["pinned"] is True
            pin = (
                await db.execute(select(ProjectChatPin).where(ProjectChatPin.session_id == s["id"]))
            ).scalar_one_or_none()
            assert pin is not None
    finally:
        await engine.dispose()


async def test_pin_contributor():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            _, contrib, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=contrib)
            result = await pin_project_chat(db, project_id=PROJ_ID, session_id=s["id"], user=contrib)
            assert result is not None
            assert result["pinned"] is True
    finally:
        await engine.dispose()


async def test_pin_viewer_denied():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, viewer = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            from fastapi import HTTPException

            try:
                await pin_project_chat(db, project_id=PROJ_ID, session_id=s["id"], user=viewer)
                pytest.fail("expected an exception")
            except HTTPException as exc:
                assert exc.status_code == 403
    finally:
        await engine.dispose()


async def test_pin_idempotent():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            await pin_project_chat(db, project_id=PROJ_ID, session_id=s["id"], user=owner)
            await pin_project_chat(db, project_id=PROJ_ID, session_id=s["id"], user=owner)
            pins = (
                (await db.execute(select(ProjectChatPin).where(ProjectChatPin.session_id == s["id"]))).scalars().all()
            )
            assert len(pins) == 1
    finally:
        await engine.dispose()


async def test_unpin():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            await pin_project_chat(db, project_id=PROJ_ID, session_id=s["id"], user=owner)
            result = await unpin_project_chat(db, project_id=PROJ_ID, session_id=s["id"], user=owner)
            assert result["pinned"] is False
            pins = (
                (await db.execute(select(ProjectChatPin).where(ProjectChatPin.session_id == s["id"]))).scalars().all()
            )
            assert len(pins) == 0
    finally:
        await engine.dispose()


async def test_list_pinned_visible_to_viewer():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, viewer = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            await pin_project_chat(db, project_id=PROJ_ID, session_id=s["id"], user=owner)
            pinned = await list_pinned_chats(db, project_id=PROJ_ID, user=viewer)
            assert pinned is not None
            assert s["id"] in pinned
    finally:
        await engine.dispose()


async def test_delete_chat_owner():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            result = await delete_project_chat_session(db, project_id=PROJ_ID, session_id=s["id"], user=owner)
            assert result is True
            row = await db.get(ChatSession, s["id"])
            assert row is None
    finally:
        await engine.dispose()


async def test_delete_chat_viewer_denied():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, viewer = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            from fastapi import HTTPException

            try:
                await delete_project_chat_session(db, project_id=PROJ_ID, session_id=s["id"], user=viewer)
                pytest.fail("expected an exception")
            except HTTPException as exc:
                assert exc.status_code == 403
    finally:
        await engine.dispose()


async def test_session_from_other_project_hidden():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            await create_project_chat_session(db, project_id=PROJ_ID, user=owner)
            # Create a second project with a session.
            db.add(
                Project(
                    id="proj-2",
                    name="P2",
                    status="active",
                    visibility="private",
                    created_by_user_id=owner.id,
                    revision=1,
                    acl_version=1,
                )
            )
            db.add(ProjectMember(project_id="proj-2", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
            await db.flush()
            s2 = await create_project_chat_session(db, project_id="proj-2", user=owner, title="Other")
            # Listing messages of proj-2's session under proj-1 should return None.
            result = await list_project_chat_messages(db, project_id=PROJ_ID, session_id=s2["id"], user=owner)
            assert result is None
    finally:
        await engine.dispose()


async def test_create_chat_with_client_session_id():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, _, _ = await _setup_project(db)
            s = await create_project_chat_session(
                db,
                project_id=PROJ_ID,
                user=owner,
                title="Client",
                session_id="client-session-1",
            )
            assert s is not None
            assert s["id"] == "client-session-1"
            again = await create_project_chat_session(
                db,
                project_id=PROJ_ID,
                user=owner,
                title="Ignored",
                session_id="client-session-1",
            )
            assert again["id"] == "client-session-1"
            assert again["title"] == "Client"
    finally:
        await engine.dispose()


async def test_contributor_can_persist_via_user_chat_storage():
    from app.services.user_chat_storage_service import (
        append_session_messages,
        get_chat_session,
        list_chat_sessions,
    )

    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, contrib, viewer = await _setup_project(db)
            s = await create_project_chat_session(db, project_id=PROJ_ID, user=owner, title="Shared")
            assert s is not None
            sid = s["id"]

            owner_personal = await list_chat_sessions(db, owner.id)
            assert all(row["id"] != sid for row in owner_personal[0])

            fetched = await get_chat_session(db, contrib.id, sid)
            assert fetched is not None
            assert fetched["id"] == sid

            appended = await append_session_messages(
                db,
                contrib.id,
                sid,
                [{"role": "user", "content": "hello from contrib", "clientMessageId": "c1"}],
            )
            assert appended is not None
            assert len(appended) == 1

            viewer_read = await get_chat_session(db, viewer.id, sid)
            assert viewer_read is not None
            viewer_append = await append_session_messages(
                db,
                viewer.id,
                sid,
                [{"role": "user", "content": "nope", "clientMessageId": "v1"}],
            )
            assert viewer_append is None

            stranger = await _user(db, "stranger2")
            assert await get_chat_session(db, stranger.id, sid) is None
    finally:
        await engine.dispose()


async def test_create_chat_session_with_project_id_scopes_thread():
    from app.services.user_chat_storage_service import (
        create_chat_session,
        list_chat_sessions,
    )

    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner, contrib, _ = await _setup_project(db)
            created = await create_chat_session(
                db,
                contrib.id,
                {
                    "id": "stream-session-1",
                    "title": "New chat",
                    "project_id": PROJ_ID,
                },
            )
            row = await db.get(ChatSession, created["id"])
            assert row.project_id == PROJ_ID
            assert row.created_by_user_id == contrib.id
            personal, total, _ = await list_chat_sessions(db, contrib.id)
            assert total == 0
            assert personal == []
    finally:
        await engine.dispose()
