"""Step 8 security gate: ACL, race, leakage, billing isolation, cascade."""

import asyncio
import datetime
import os
import tempfile

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.logging import RequestLog
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMediaAsset,
    ProjectMember,
)
from app.models.user import User
from app.services.project_access_service import require_capability
from app.services.project_billing_service import report_project_usage_summary
from app.services.project_media_service import (
    delete_project_media,
    get_project_media,
    list_project_media,
    upload_project_media,
)
from app.services.project_service import hard_delete_project, remove_member
from app.services.user_lifecycle_service import permanently_delete_user

PROJ_A = "media-sec-a"
PROJ_B = "media-sec-b"


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


async def _file_factory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
        pool_size=10,
        max_overflow=10,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def dispose():
        await engine.dispose()
        try:
            os.remove(path)
        except OSError:
            pass

    return (
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        dispose,
    )


async def _user(db, username, *, active=True):
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=active,
        monthly_budget_usd=100.0,
    )
    db.add(u)
    await db.flush()
    return u


async def _setup(db, pid, *, owner_name="owner"):
    owner = await _user(db, f"{owner_name}_{pid}")
    contrib = await _user(db, f"contrib_{pid}")
    viewer = await _user(db, f"viewer_{pid}")
    db.add(
        Project(
            id=pid,
            name=f"P {pid}",
            status="active",
            visibility="private",
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


def _window():
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=30)
    return start, end


def test_viewer_upload_denied():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                _, _, viewer = await _setup(db, PROJ_A)
                try:
                    await require_capability(
                        db, project_id=PROJ_A, user=viewer, capability="media.upload"
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
                try:
                    await upload_project_media(
                        db,
                        project_id=PROJ_A,
                        user=viewer,
                        file_name="no.png",
                        mime_type="image/png",
                        content_bytes=b"nope",
                        object_store=store,
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_contributor_cannot_delete_others_media():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db, PROJ_A)
                uploaded = await upload_project_media(
                    db,
                    project_id=PROJ_A,
                    user=owner,
                    file_name="owner.png",
                    mime_type="image/png",
                    content_bytes=b"owner-file",
                    object_store=store,
                )
                try:
                    await delete_project_media(
                        db,
                        project_id=PROJ_A,
                        media_id=uploaded["id"],
                        user=contrib,
                        object_store=store,
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
                row = await db.get(ProjectMediaAsset, uploaded["id"])
                assert row is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cross_project_media_isolation():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner_a, _, _ = await _setup(db, PROJ_A, owner_name="oa")
                owner_b, _, _ = await _setup(db, PROJ_B, owner_name="ob")
                uploaded = await upload_project_media(
                    db,
                    project_id=PROJ_A,
                    user=owner_a,
                    file_name="secret.png",
                    mime_type="image/png",
                    content_bytes=b"secret-a",
                    object_store=store,
                )
                items_b, total_b = await list_project_media(
                    db, project_id=PROJ_B, user=owner_b
                )
                assert total_b == 0
                assert items_b == []

                hidden = await get_project_media(
                    db,
                    project_id=PROJ_B,
                    media_id=uploaded["id"],
                    user=owner_b,
                )
                assert hidden is None

                try:
                    await get_project_media(
                        db,
                        project_id=PROJ_A,
                        media_id=uploaded["id"],
                        user=owner_b,
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_concurrent_distinct_uploads_both_succeed():
    async def run():
        factory, dispose = await _file_factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db, PROJ_A)
                owner_id = owner.id
                await db.commit()

            async def upload_one(name: str, body: bytes):
                async with factory() as db:
                    user = await db.get(User, owner_id)
                    item = await upload_project_media(
                        db,
                        project_id=PROJ_A,
                        user=user,
                        file_name=name,
                        mime_type="application/octet-stream",
                        content_bytes=body,
                        object_store=store,
                    )
                    await db.commit()
                    return item

            first, second = await asyncio.gather(
                upload_one("one.bin", b"payload-one"),
                upload_one("two.bin", b"payload-two"),
            )
            assert first["id"] != second["id"]
            async with factory() as db:
                user = await db.get(User, owner_id)
                _, total = await list_project_media(db, project_id=PROJ_A, user=user)
                assert total == 2
        finally:
            await dispose()

    asyncio.run(run())


def test_media_billing_isolated_per_project():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner_a, _, _ = await _setup(db, PROJ_A, owner_name="oa")
                owner_b, _, _ = await _setup(db, PROJ_B, owner_name="ob")
                now = datetime.datetime.utcnow()
                db.add(
                    RequestLog(
                        user_id=owner_a.id,
                        username=owner_a.username,
                        model_id="gemini-image",
                        project_id=PROJ_A,
                        total_cost_usd=2.5,
                        request_time=now,
                        success=True,
                        client_app="Alpharouter Chat (image:generation)",
                    )
                )
                db.add(
                    RequestLog(
                        user_id=owner_b.id,
                        username=owner_b.username,
                        model_id="gemini-image",
                        project_id=PROJ_B,
                        total_cost_usd=9.0,
                        request_time=now,
                        success=True,
                        client_app="Alpharouter Chat (image:generation)",
                    )
                )
                await db.flush()
                start, end = _window()
                summary_a = await report_project_usage_summary(db, PROJ_A, start, end)
                summary_b = await report_project_usage_summary(db, PROJ_B, start, end)
                assert float(summary_a.iloc[0]["media_cost_usd"]) == 2.5
                assert float(summary_b.iloc[0]["media_cost_usd"]) == 9.0
                assert float(summary_a.iloc[0]["total_cost_usd"]) == 2.5
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_hard_delete_cascade_vs_user_delete(monkeypatch):
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        monkeypatch.setattr(
            "app.services.user_account_cleanup_service.oss.purge_user_cdn_objects",
            lambda slug, user_id: 0,
        )
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db, PROJ_A)
                uploaded = await upload_project_media(
                    db,
                    project_id=PROJ_A,
                    user=contrib,
                    file_name="stay.png",
                    mime_type="image/png",
                    content_bytes=b"stay-bytes",
                    object_store=store,
                )
                media_id = uploaded["id"]
                await permanently_delete_user(db, contrib)
                row = await db.get(ProjectMediaAsset, media_id)
                assert row is not None
                assert row.uploaded_by_user_id is None

                await hard_delete_project(
                    db, project_id=PROJ_A, user=owner, object_store=store
                )
                assert await db.get(ProjectMediaAsset, media_id) is None
                assert uploaded["storagePath"] in store.deleted
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_removed_member_cannot_read_but_file_remains():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db, PROJ_A)
                uploaded = await upload_project_media(
                    db,
                    project_id=PROJ_A,
                    user=contrib,
                    file_name="kept.png",
                    mime_type="image/png",
                    content_bytes=b"kept-bytes",
                    object_store=store,
                )
                await remove_member(
                    db, project_id=PROJ_A, user=owner, target_user_id=contrib.id
                )
                row = await db.get(ProjectMediaAsset, uploaded["id"])
                assert row is not None
                try:
                    await get_project_media(
                        db,
                        project_id=PROJ_A,
                        media_id=uploaded["id"],
                        user=contrib,
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())
