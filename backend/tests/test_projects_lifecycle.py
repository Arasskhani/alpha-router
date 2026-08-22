"""Archive, restore, delayed purge, and account-delete preservation of project chats."""

import asyncio
import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.project import (
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_STATUS_ARCHIVED,
    PROJECT_STATUS_DELETION_PENDING,
    PROJECT_VISIBILITY_PUBLIC,
    Project,
    ProjectMediaAsset,
    ProjectMember,
)
from app.models.user import User
from app.services.project_chat_service import (
    append_project_chat_message,
    create_project_chat_session,
)
from app.services.project_service import (
    archive_project,
    create_project,
    delete_project,
    list_my_projects,
    list_public_projects,
    purge_expired_deleted_projects,
    restore_project,
)
from app.services.user_lifecycle_service import permanently_delete_user

PROJ = "life-1"


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, key: str, body: bytes, mime: str) -> None:
        self._store[key] = body

    async def get(self, key: str) -> bytes:
        return self._store[key]

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self.deleted.append(key)

    async def exists(self, key: str) -> bool:
        return key in self._store


async def _factory():
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


def test_archive_hides_from_explore():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                outsider = await _user(db, "outsider")
                proj = await create_project(
                    db,
                    user=owner,
                    name="Public Alpha",
                    visibility=PROJECT_VISIBILITY_PUBLIC,
                )
                pid = proj["id"]
                before, _ = await list_public_projects(db, user=outsider)
                assert any(p["id"] == pid for p in before)
                archived = await archive_project(db, project_id=pid, user=owner)
                assert archived["status"] == PROJECT_STATUS_ARCHIVED
                after, _ = await list_public_projects(db, user=outsider)
                assert not any(p["id"] == pid for p in after)
                mine, _ = await list_my_projects(db, user=owner)
                assert any(p["id"] == pid and p["status"] == PROJECT_STATUS_ARCHIVED for p in mine)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_restore_archive():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                outsider = await _user(db, "outsider")
                proj = await create_project(
                    db,
                    user=owner,
                    name="Public Beta",
                    visibility=PROJECT_VISIBILITY_PUBLIC,
                )
                pid = proj["id"]
                await archive_project(db, project_id=pid, user=owner)
                restored = await restore_project(db, project_id=pid, user=owner)
                assert restored["status"] == "active"
                assert restored["archivedAt"] is None
                explore, _ = await list_public_projects(db, user=outsider)
                assert any(p["id"] == pid for p in explore)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_purge_deletion_pending_cleans_storage():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                proj = await create_project(db, user=owner, name="Doomed")
                pid = proj["id"]
                from app.services.project_media_service import upload_project_media

                uploaded = await upload_project_media(
                    db,
                    project_id=pid,
                    user=owner,
                    file_name="gone.png",
                    mime_type="image/png",
                    content_bytes=b"purge-me",
                    object_store=store,
                )
                await delete_project(db, project_id=pid, user=owner)
                row = await db.get(Project, pid)
                row.updated_at = datetime.datetime.utcnow() - datetime.timedelta(days=40)
                await db.flush()
                n = await purge_expired_deleted_projects(
                    db, retention_days=30, object_store=store
                )
                assert n == 1
                assert await db.get(Project, pid) is None
                assert await db.get(ProjectMediaAsset, uploaded["id"]) is None
                assert uploaded["storagePath"] in store.deleted
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_user_delete_keeps_project_chat_session(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_account_cleanup_service.oss.purge_user_cdn_objects",
        lambda slug, user_id: 0,
    )
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                contrib = await _user(db, "contrib")
                db.add(
                    Project(
                        id=PROJ,
                        name="Keep",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                db.add(ProjectMember(project_id=PROJ, user_id=contrib.id, role="contributor"))
                await db.flush()
                session = await create_project_chat_session(
                    db, project_id=PROJ, user=contrib, title="Shared"
                )
                sid = session["id"]
                await append_project_chat_message(
                    db,
                    project_id=PROJ,
                    session_id=sid,
                    user=contrib,
                    role="user",
                    content="hello from contrib",
                )
                await permanently_delete_user(db, contrib)
                row = await db.get(ChatSession, sid)
                assert row is not None
                assert row.project_id == PROJ
                from sqlalchemy import select

                kept = (
                    await db.execute(select(ChatMessage).where(ChatMessage.session_id == sid))
                ).scalars().all()
                assert len(kept) == 1
                assert kept[0].content == "hello from contrib"
                assert kept[0].user_id is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_session_user_id_reassigned_to_remaining_owner(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_account_cleanup_service.oss.purge_user_cdn_objects",
        lambda slug, user_id: 0,
    )
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner_a = await _user(db, "owner_a")
                owner_b = await _user(db, "owner_b")
                db.add(
                    Project(
                        id=PROJ,
                        name="Owners",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner_a.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(ProjectMember(project_id=PROJ, user_id=owner_a.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                db.add(ProjectMember(project_id=PROJ, user_id=owner_b.id, role=PROJECT_ROLE_OWNER))
                await db.flush()
                session = await create_project_chat_session(
                    db, project_id=PROJ, user=owner_a, title="A's thread"
                )
                sid = session["id"]
                await permanently_delete_user(db, owner_a)
                row = await db.get(ChatSession, sid)
                assert row is not None
                assert row.user_id == owner_b.id
        finally:
            await engine.dispose()

    asyncio.run(run())
