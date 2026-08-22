"""Step 3 tests: project media service (upload, list, delete, isolation, quota)."""

import asyncio

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMember,
    ProjectMediaAsset,
)
from app.models.media import MediaAsset
from app.models.user import User
from app.services.project_media_service import (
    ProjectMediaQuotaError,
    ProjectMediaValidationError,
    delete_project_media,
    get_project_media,
    list_project_media,
    persist_scoped_chat_media,
    project_media_public_url,
    read_project_media_bytes,
    rewrite_personal_media_urls_in_messages,
    upload_project_media,
)

PROJ = "media-svc-1"
PROJ2 = "media-svc-2"


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


def test_upload_and_list_media():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                a = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="a.png", mime_type="image/png",
                    content_bytes=b"png-one", object_store=store,
                )
                b = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="b.jpg", mime_type="image/jpeg",
                    content_bytes=b"jpg-two", object_store=store,
                )
                items, total = await list_project_media(db, project_id=PROJ, user=owner)
                assert total == 2
                names = {i["fileName"] for i in items}
                assert names == {"a.png", "b.jpg"}
                assert a["kind"] == "image"
                assert b["kind"] == "image"
                assert a["uploadedByUserId"] == owner.id
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_upload_dedup_same_hash():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                first = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="one.bin", mime_type="application/octet-stream",
                    content_bytes=b"same-bytes", object_store=store,
                )
                second = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="two.bin", mime_type="application/octet-stream",
                    content_bytes=b"same-bytes", object_store=store,
                )
                assert first["id"] == second["id"]
                items, total = await list_project_media(db, project_id=PROJ, user=owner)
                assert total == 1
                assert len(store._store) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_upload_different_projects_isolated():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db, PROJ)
                owner2, _, _ = await _setup(db, PROJ2)
                await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="a.bin", mime_type="application/octet-stream",
                    content_bytes=b"secret-a", object_store=store,
                )
                items, total = await list_project_media(db, project_id=PROJ2, user=owner2)
                assert total == 0
                assert items == []
                # same hash in a different project is a separate asset
                other = await upload_project_media(
                    db, project_id=PROJ2, user=owner2,
                    file_name="a.bin", mime_type="application/octet-stream",
                    content_bytes=b"secret-a", object_store=store,
                )
                assert other["projectId"] == PROJ2
                a_items, a_total = await list_project_media(db, project_id=PROJ, user=owner)
                assert a_total == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_by_owner_any_file():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                uploaded = await upload_project_media(
                    db, project_id=PROJ, user=contrib,
                    file_name="c.bin", mime_type="application/octet-stream",
                    content_bytes=b"contrib-file", object_store=store,
                )
                ok = await delete_project_media(
                    db, project_id=PROJ, media_id=uploaded["id"],
                    user=owner, object_store=store,
                )
                assert ok is True
                items, total = await list_project_media(db, project_id=PROJ, user=owner)
                assert total == 0
                assert uploaded["storagePath"] in store.deleted
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_by_contributor_own_file_only():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                own = await upload_project_media(
                    db, project_id=PROJ, user=contrib,
                    file_name="mine.bin", mime_type="application/octet-stream",
                    content_bytes=b"mine", object_store=store,
                )
                others = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="theirs.bin", mime_type="application/octet-stream",
                    content_bytes=b"theirs", object_store=store,
                )
                ok = await delete_project_media(
                    db, project_id=PROJ, media_id=own["id"],
                    user=contrib, object_store=store,
                )
                assert ok is True
                try:
                    await delete_project_media(
                        db, project_id=PROJ, media_id=others["id"],
                        user=contrib, object_store=store,
                    )
                    assert False, "contributor must not delete others' files"
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_by_viewer_denied():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, viewer = await _setup(db)
                uploaded = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="x.bin", mime_type="application/octet-stream",
                    content_bytes=b"x", object_store=store,
                )
                try:
                    await delete_project_media(
                        db, project_id=PROJ, media_id=uploaded["id"],
                        user=viewer, object_store=store,
                    )
                    assert False
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_get_hidden_for_non_member():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                outsider = await _user(db, "outsider")
                uploaded = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="x.bin", mime_type="application/octet-stream",
                    content_bytes=b"x", object_store=store,
                )
                try:
                    await get_project_media(
                        db, project_id=PROJ, media_id=uploaded["id"], user=outsider,
                    )
                    assert False
                except HTTPException as e:
                    assert e.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_upload_quota_enforced():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="a.bin", mime_type="application/octet-stream",
                    content_bytes=b"12345", object_store=store, quota_bytes=8,
                )
                try:
                    await upload_project_media(
                        db, project_id=PROJ, user=owner,
                        file_name="b.bin", mime_type="application/octet-stream",
                        content_bytes=b"67890", object_store=store, quota_bytes=8,
                    )
                    assert False
                except ProjectMediaQuotaError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_storage_path_uses_project_prefix():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                uploaded = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="pic.png", mime_type="image/png",
                    content_bytes=b"png-bytes", object_store=store,
                )
                path = uploaded["storagePath"].replace("\\", "/")
                assert f"/p/{PROJ}/" in path
                assert "/u/" not in path
                assert path in store._store
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_viewer_cannot_upload():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                _, _, viewer = await _setup(db)
                try:
                    await upload_project_media(
                        db, project_id=PROJ, user=viewer,
                        file_name="x.bin", mime_type="application/octet-stream",
                        content_bytes=b"x", object_store=store,
                    )
                    assert False
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_read_bytes_and_empty_rejected():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, viewer = await _setup(db)
                uploaded = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="doc.pdf", mime_type="application/pdf",
                    content_bytes=b"%PDF-fake", object_store=store,
                )
                assert uploaded["kind"] == "document"
                result = await read_project_media_bytes(
                    db, project_id=PROJ, media_id=uploaded["id"],
                    user=viewer, object_store=store,
                )
                assert result is not None
                row, blob = result
                assert blob == b"%PDF-fake"
                assert row.file_name == "doc.pdf"
                try:
                    await upload_project_media(
                        db, project_id=PROJ, user=owner,
                        file_name="empty.bin", mime_type="application/octet-stream",
                        content_bytes=b"", object_store=store,
                    )
                    assert False
                except ProjectMediaValidationError:
                    pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_get_wrong_project_returns_none():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db, PROJ)
                owner2, _, _ = await _setup(db, PROJ2)
                uploaded = await upload_project_media(
                    db, project_id=PROJ, user=owner,
                    file_name="x.bin", mime_type="application/octet-stream",
                    content_bytes=b"x", object_store=store,
                )
                result = await get_project_media(
                    db, project_id=PROJ2, media_id=uploaded["id"], user=owner2,
                )
                assert result is None
        finally:
            await engine.dispose()

    asyncio.run(run())


async def _count_rows(db, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for key, value in filters.items():
        stmt = stmt.where(getattr(model, key) == value)
    return int((await db.execute(stmt)).scalar() or 0)


def test_persist_scoped_chat_media_project_only():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                url = await persist_scoped_chat_media(
                    db,
                    user=owner,
                    project_id=PROJ,
                    kind='document',
                    blob=b'project-only-bytes',
                    mime='application/pdf',
                    file_name='note.pdf',
                    object_store=store,
                )
                assert url.startswith(f'/api/projects/{PROJ}/media/')
                assert '/api/chat/media/' not in url
                assert await _count_rows(db, ProjectMediaAsset, project_id=PROJ) == 1
                assert await _count_rows(db, MediaAsset) == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_persist_scoped_chat_media_personal_when_no_project():
    async def run():
        from unittest.mock import patch

        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)

                async def fake_store(db_sess, **kwargs):
                    row = MediaAsset(
                        user_id=kwargs['user_id'],
                        kind=kwargs['kind'],
                        mime_type=kwargs.get('mime') or 'application/octet-stream',
                        file_name=kwargs.get('file_name_hint') or 'x.bin',
                        storage_path='u/test/x.bin',
                        content_hash=kwargs.get('content_hash') or 'a' * 64,
                        size_bytes=len(kwargs.get('blob') or b''),
                    )
                    db_sess.add(row)
                    await db_sess.flush()
                    return row

                with patch(
                    'app.services.storage_service.store_media_from_blob',
                    side_effect=fake_store,
                ):
                    url = await persist_scoped_chat_media(
                        db,
                        user=owner,
                        project_id=None,
                        kind='document',
                        blob=b'personal-only',
                        mime='application/pdf',
                        file_name='me.pdf',
                    )
                assert url.startswith('/api/chat/media/')
                assert url.endswith('/file')
                assert await _count_rows(db, ProjectMediaAsset) == 0
                assert await _count_rows(db, MediaAsset) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_persist_scoped_chat_media_quota_falls_back_to_user():
    async def run():
        from unittest.mock import patch

        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)

                async def fake_store(db_sess, **kwargs):
                    row = MediaAsset(
                        user_id=kwargs['user_id'],
                        kind=kwargs['kind'],
                        mime_type=kwargs.get('mime') or 'application/octet-stream',
                        file_name=kwargs.get('file_name_hint') or 'x.bin',
                        storage_path='u/test/fallback.bin',
                        content_hash=kwargs.get('content_hash') or 'b' * 64,
                        size_bytes=len(kwargs.get('blob') or b''),
                    )
                    db_sess.add(row)
                    await db_sess.flush()
                    return row

                with patch(
                    'app.services.storage_service.store_media_from_blob',
                    side_effect=fake_store,
                ):
                    url = await persist_scoped_chat_media(
                        db,
                        user=owner,
                        project_id=PROJ,
                        kind='document',
                        blob=b'12345',
                        mime='application/pdf',
                        file_name='over.pdf',
                        object_store=store,
                        quota_bytes=3,
                    )
                assert url.startswith('/api/chat/media/')
                assert await _count_rows(db, ProjectMediaAsset, project_id=PROJ) == 0
                assert await _count_rows(db, MediaAsset) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_rewrite_personal_media_urls_when_hash_matches():
    async def run():
        factory, engine = await _factory()
        store = InMemoryObjectStore()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                digest = 'ab' * 32
                personal = MediaAsset(
                    user_id=owner.id,
                    kind='image',
                    mime_type='image/png',
                    file_name='old.png',
                    storage_path='u/owner/old.png',
                    content_hash=digest,
                    size_bytes=12,
                )
                db.add(personal)
                await db.flush()
                saved = await upload_project_media(
                    db,
                    project_id=PROJ,
                    user=owner,
                    file_name='copy.png',
                    mime_type='image/png',
                    content_bytes=b'project-copy',
                    object_store=store,
                    content_hash=digest,
                )
                messages = [
                    {
                        'content': f'![img](/api/chat/media/{personal.id}/file)',
                    }
                ]
                rewritten = await rewrite_personal_media_urls_in_messages(
                    db, project_id=PROJ, messages=messages
                )
                expected = project_media_public_url(PROJ, int(saved['id']))
                assert expected in rewritten[0]['content']
                assert f'/api/chat/media/{personal.id}/file' not in rewritten[0]['content']
        finally:
            await engine.dispose()

    asyncio.run(run())
