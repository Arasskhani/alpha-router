"""Live project chat, last-opened prefs, recent list, overview ACL, and deep-link get-by-id."""

import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    PROJECT_VISIBILITY_PRIVATE,
    Project,
    ProjectMember,
)
from app.models.user import User
from app.services.project_chat_service import (
    append_project_chat_message,
    create_project_chat_session,
    delete_project_chat_session,
    get_last_opened_session_id,
    get_project_chat_session,
    list_project_chat_sessions,
    pin_project_chat,
    sync_project_chats,
    touch_project_visit,
)
from app.services.project_service import (
    create_project,
    get_project_overview,
    list_recent_projects,
)

PROJ_ID = "proj-live-1"


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


async def _setup_project(db):
    owner = await _user(db, "owner")
    contrib = await _user(db, "contrib")
    viewer = await _user(db, "viewer")
    db.add(
        Project(
            id=PROJ_ID,
            name="Live",
            status="active",
            visibility=PROJECT_VISIBILITY_PRIVATE,
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


def test_get_chat_not_in_first_page():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, viewer = await _setup_project(db)
                base = dt.datetime.utcnow()
                ids = []
                for i in range(55):
                    session = await create_project_chat_session(
                        db, project_id=PROJ_ID, user=owner, title=f"T{i}"
                    )
                    ids.append(session["id"])
                    row = await db.get(ChatSession, session["id"])
                    row.updated_at = base - dt.timedelta(seconds=i)
                await db.flush()
                oldest = ids[-1]
                listed, total = await list_project_chat_sessions(
                    db, project_id=PROJ_ID, user=viewer, limit=50
                )
                assert total == 55
                assert oldest not in {row["id"] for row in listed}
                got = await get_project_chat_session(
                    db, project_id=PROJ_ID, session_id=oldest, user=viewer
                )
                assert got is not None
                assert got["id"] == oldest
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_sync_pin_and_messages_visible_to_other_member():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup_project(db)
                session = await create_project_chat_session(
                    db, project_id=PROJ_ID, user=contrib, title="Shared"
                )
                sid = session["id"]
                await pin_project_chat(db, project_id=PROJ_ID, session_id=sid, user=owner)
                await append_project_chat_message(
                    db,
                    project_id=PROJ_ID,
                    session_id=sid,
                    user=contrib,
                    role="user",
                    content="hello from contrib",
                )
                snapshot = await sync_project_chats(
                    db,
                    project_id=PROJ_ID,
                    user=viewer,
                    session_id=sid,
                    after_sequence=0,
                )
                assert snapshot is not None
                assert sid in snapshot["pinnedSessionIds"]
                assert any(row["id"] == sid and row["pinned"] for row in snapshot["sessions"])
                assert any(msg["content"] == "hello from contrib" for msg in snapshot["messages"])
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_sync_returns_patched_assistant_at_after_sequence():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup_project(db)
                session = await create_project_chat_session(
                    db, project_id=PROJ_ID, user=contrib, title="Stream"
                )
                sid = session["id"]
                await append_project_chat_message(
                    db,
                    project_id=PROJ_ID,
                    session_id=sid,
                    user=contrib,
                    role="user",
                    content="draw a cat",
                )
                placeholder = await append_project_chat_message(
                    db,
                    project_id=PROJ_ID,
                    session_id=sid,
                    user=contrib,
                    role="assistant",
                    content="",
                    client_message_id="asst-1",
                )
                seq = int(placeholder["sequence"])
                row = await db.get(ChatMessage, placeholder["id"])
                assert row is not None
                row.content = "here is the picture ![cat](/api/projects/x/media/1/download)"
                row.meta = {
                    **(row.meta if isinstance(row.meta, dict) else {}),
                    "streaming": False,
                    "receivedAt": 1_700_000_000_000,
                    "modelId": "m1",
                    "modelName": "Model One",
                }
                await db.flush()
                snapshot = await sync_project_chats(
                    db,
                    project_id=PROJ_ID,
                    user=viewer,
                    session_id=sid,
                    after_sequence=seq,
                )
                assert snapshot is not None
                contents = [msg["content"] for msg in snapshot["messages"]]
                assert any("here is the picture" in (c or "") for c in contents)
                done = next(
                    msg
                    for msg in snapshot["messages"]
                    if "here is the picture" in (msg.get("content") or "")
                )
                assert done.get("streaming") is False
                assert done.get("receivedAt") == 1_700_000_000_000
                assert done.get("modelId") == "m1"
                assert done.get("modelName") == "Model One"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_sync_drops_deleted_session_when_window_complete():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, viewer = await _setup_project(db)
                keep = await create_project_chat_session(
                    db, project_id=PROJ_ID, user=owner, title="Keep"
                )
                gone = await create_project_chat_session(
                    db, project_id=PROJ_ID, user=owner, title="Gone"
                )
                await delete_project_chat_session(
                    db, project_id=PROJ_ID, session_id=gone["id"], user=owner
                )
                snapshot = await sync_project_chats(db, project_id=PROJ_ID, user=viewer)
                assert snapshot is not None
                assert snapshot["completeWindow"] is True
                assert keep["id"] in snapshot["sessionIds"]
                assert gone["id"] not in snapshot["sessionIds"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_last_opened_session_and_recent_projects():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                first = await create_project(
                    db, user=owner, name="Alpha", visibility=PROJECT_VISIBILITY_PRIVATE
                )
                second = await create_project(
                    db, user=owner, name="Beta", visibility=PROJECT_VISIBILITY_PRIVATE
                )
                chat = await create_project_chat_session(
                    db, project_id=first["id"], user=owner, title="Thread"
                )
                await touch_project_visit(db, project_id=first["id"], user=owner)
                await touch_project_visit(
                    db,
                    project_id=first["id"],
                    user=owner,
                    session_id=chat["id"],
                )
                await touch_project_visit(db, project_id=second["id"], user=owner)
                assert (
                    await get_last_opened_session_id(
                        db, project_id=first["id"], user=owner
                    )
                    == chat["id"]
                )
                listed, _total = await list_project_chat_sessions(
                    db, project_id=first["id"], user=owner
                )
                # list endpoint adds lastOpened separately; service list is sessions only
                assert listed[0]["id"] == chat["id"] or any(row["id"] == chat["id"] for row in listed)
                recent, count = await list_recent_projects(db, user=owner, limit=8)
                assert count >= 2
                assert recent[0]["id"] == second["id"]
                assert {row["id"] for row in recent} >= {first["id"], second["id"]}
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_overview_hides_usage_from_contributor():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, viewer = await _setup_project(db)
                owner_view = await get_project_overview(db, project_id=PROJ_ID, user=owner)
                contrib_view = await get_project_overview(db, project_id=PROJ_ID, user=contrib)
                viewer_view = await get_project_overview(db, project_id=PROJ_ID, user=viewer)
                assert owner_view is not None and owner_view["usage"] is not None
                assert contrib_view is not None and contrib_view["usage"] is None
                assert viewer_view is not None and viewer_view["usage"] is None
                assert owner_view["counts"]["members"] == 3
        finally:
            await engine.dispose()

    asyncio.run(run())
