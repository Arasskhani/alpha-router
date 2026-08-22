"""Step 7: project media cascade, soft-delete hide, and account cleanup."""

import asyncio

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    PROJECT_STATUS_DELETION_PENDING,
    PROJECT_VISIBILITY_PUBLIC,
    Project,
    ProjectMediaAsset,
    ProjectMember,
)
from app.models.user import User
from app.services.project_media_service import (
    list_project_media,
    upload_project_media,
)
from app.services.project_service import (
    delete_project,
    hard_delete_project,
    remove_member,
)
from app.services.user_lifecycle_service import permanently_delete_user


PROJ = "media-cleanup-1"
PROJ_PUB = "media-cleanup-pub"


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


async def _setup(db, pid=PROJ, *, visibility="private"):
    owner = await _user(db, f"owner_{pid}")
    contrib = await _user(db, f"contrib_{pid}")
    viewer = await _user(db, f"viewer_{pid}")
    db.add(
        Project(
            id=pid,
            name=f"P {pid}",
            status="active",
            visibility=visibility,
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=pid, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=pid, user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
    db.add(ProjectMember(project_id=pid, user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
    await db.flush()
    return owner, contrib, viewer


def test_hard_delete_project_removes_media():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                uploaded = await upload_project_media(
                    db,
                    project_id=PROJ,
                    user=owner,
                    file_name="keep.png",
                    mime_type="image/png",
                    content_bytes=b"png-bytes",
                    object_store=store,
                )
                path = uploaded["storagePath"]
                assert path in store._store

                ok = await hard_delete_project(
                    db, project_id=PROJ, user=owner, object_store=store
                )
                assert ok is True
                assert await db.get(Project, PROJ) is None
                leftover = (
                    await db.execute(
                        select(ProjectMediaAsset).where(ProjectMediaAsset.project_id == PROJ)
                    )
                ).scalars().all()
                assert leftover == []
                assert path in store.deleted
                assert path not in store._store
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_soft_delete_project_hides_media():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(
                    db, pid=PROJ_PUB, visibility=PROJECT_VISIBILITY_PUBLIC
                )
                outsider = await _user(db, "outsider_pub")
                uploaded = await upload_project_media(
                    db,
                    project_id=PROJ_PUB,
                    user=owner,
                    file_name="public.png",
                    mime_type="image/png",
                    content_bytes=b"public-bytes",
                    object_store=store,
                )
                before, total = await list_project_media(
                    db, project_id=PROJ_PUB, user=outsider
                )
                assert total == 1
                assert before[0]["id"] == uploaded["id"]

                assert await delete_project(db, project_id=PROJ_PUB, user=owner)
                project = await db.get(Project, PROJ_PUB)
                assert project is not None
                assert project.status == PROJECT_STATUS_DELETION_PENDING

                try:
                    await list_project_media(db, project_id=PROJ_PUB, user=outsider)
                    assert False, "public viewer should not see media after soft-delete"
                except HTTPException as exc:
                    assert exc.status_code == 404

                items, remaining = await list_project_media(
                    db, project_id=PROJ_PUB, user=owner
                )
                assert remaining == 1
                assert items[0]["id"] == uploaded["id"]
                assert uploaded["storagePath"] in store._store
                row = await db.get(ProjectMediaAsset, uploaded["id"])
                assert row is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_user_deletion_preserves_project_media(monkeypatch):
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        monkeypatch.setattr(
            "app.services.user_account_cleanup_service.oss.purge_user_cdn_objects",
            lambda slug, user_id: 0,
        )
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                uploaded = await upload_project_media(
                    db,
                    project_id=PROJ,
                    user=contrib,
                    file_name="contrib.png",
                    mime_type="image/png",
                    content_bytes=b"contrib-bytes",
                    object_store=store,
                )
                media_id = uploaded["id"]
                path = uploaded["storagePath"]
                await permanently_delete_user(db, contrib)
                await db.flush()

                assert await db.get(User, contrib.id) is None
                row = await db.get(ProjectMediaAsset, media_id)
                assert row is not None
                assert row.project_id == PROJ
                assert row.uploaded_by_user_id is None
                assert path in store._store
                items, total = await list_project_media(db, project_id=PROJ, user=owner)
                assert total == 1
                assert items[0]["id"] == media_id
                assert items[0]["uploadedByUserId"] is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_removed_member_media_preserved():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                uploaded = await upload_project_media(
                    db,
                    project_id=PROJ,
                    user=contrib,
                    file_name="left.png",
                    mime_type="image/png",
                    content_bytes=b"left-bytes",
                    object_store=store,
                )
                media_id = uploaded["id"]
                contrib_id = contrib.id

                assert await remove_member(
                    db, project_id=PROJ, user=owner, target_user_id=contrib_id
                )

                row = await db.get(ProjectMediaAsset, media_id)
                assert row is not None
                assert row.uploaded_by_user_id == contrib_id
                assert uploaded["storagePath"] in store._store

                items, total = await list_project_media(db, project_id=PROJ, user=owner)
                assert total == 1
                assert items[0]["id"] == media_id

                try:
                    await list_project_media(db, project_id=PROJ, user=contrib)
                    assert False, "removed member must not list project media"
                except HTTPException as exc:
                    assert exc.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())
