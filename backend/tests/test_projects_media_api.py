"""Step 5 tests: project media API endpoints."""

import asyncio
from io import BytesIO

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.projects import (
    delete_project_media_endpoint,
    download_project_media_endpoint,
    get_project_media_endpoint,
    list_project_media_endpoint,
    upload_project_media_endpoint,
)
from app.database import Base
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMember,
)
from app.models.user import User

PROJ = "media-api-1"


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put(self, key: str, body: bytes, mime: str) -> None:
        self._store[key] = body

    async def get(self, key: str) -> bytes:
        return self._store[key]

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self._store


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username):
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _setup(db):
    owner = await _user(db, "owner")
    contrib = await _user(db, "contrib")
    viewer = await _user(db, "viewer")
    db.add(
        Project(
            id=PROJ,
            name="API Media",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    db.add(ProjectMember(project_id=PROJ, user_id=contrib.id, role=PROJECT_ROLE_CONTRIBUTOR))
    db.add(ProjectMember(project_id=PROJ, user_id=viewer.id, role=PROJECT_ROLE_VIEWER))
    await db.flush()
    return owner, contrib, viewer


def _upload(name: str, data: bytes, content_type: str = "application/octet-stream") -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(data), headers={"content-type": content_type})


def test_api_upload_media_success(monkeypatch):
    store = InMemoryObjectStore()
    monkeypatch.setattr(
        "app.api.projects.default_project_media_store", lambda: store
    )

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                item = await upload_project_media_endpoint(
                    project_id=PROJ,
                    file=_upload("pic.png", b"png-bytes", "image/png"),
                    kind="image",
                    source_model=None,
                    source_prompt=None,
                    chat_session_id=None,
                    user=owner,
                    db=db,
                )
                assert item["fileName"] == "pic.png"
                assert item["kind"] == "image"
                assert item["uploadedByUserId"] == owner.id
                listed = await list_project_media_endpoint(
                    project_id=PROJ, user=owner, db=db, kind=None, q=None, limit=50, offset=0
                )
                assert listed["total"] == 1
                assert listed["items"][0]["id"] == item["id"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_api_list_media_pagination(monkeypatch):
    store = InMemoryObjectStore()
    monkeypatch.setattr("app.api.projects.default_project_media_store", lambda: store)

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                for i in range(5):
                    await upload_project_media_endpoint(
                        project_id=PROJ,
                        file=_upload(f"f{i}.bin", f"body-{i}".encode()),
                        kind=None,
                        source_model=None,
                        source_prompt=None,
                        chat_session_id=None,
                        user=owner,
                        db=db,
                    )
                page = await list_project_media_endpoint(
                    project_id=PROJ, user=owner, db=db, kind=None, q=None, limit=2, offset=0
                )
                assert page["total"] == 5
                assert len(page["items"]) == 2
                page2 = await list_project_media_endpoint(
                    project_id=PROJ, user=owner, db=db, kind=None, q=None, limit=2, offset=2
                )
                assert len(page2["items"]) == 2
                ids = {row["id"] for row in page["items"] + page2["items"]}
                assert len(ids) == 4
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_api_upload_media_viewer_403(monkeypatch):
    store = InMemoryObjectStore()
    monkeypatch.setattr("app.api.projects.default_project_media_store", lambda: store)

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                _, _, viewer = await _setup(db)
                try:
                    await upload_project_media_endpoint(
                        project_id=PROJ,
                        file=_upload("x.bin", b"x"),
                        kind=None,
                        source_model=None,
                        source_prompt=None,
                        chat_session_id=None,
                        user=viewer,
                        db=db,
                    )
                    assert False
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_api_download_media_success(monkeypatch):
    store = InMemoryObjectStore()
    monkeypatch.setattr("app.api.projects.default_project_media_store", lambda: store)

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, viewer = await _setup(db)
                item = await upload_project_media_endpoint(
                    project_id=PROJ,
                    file=_upload("doc.pdf", b"%PDF-bytes", "application/pdf"),
                    kind=None,
                    source_model=None,
                    source_prompt=None,
                    chat_session_id=None,
                    user=owner,
                    db=db,
                )
                meta = await get_project_media_endpoint(
                    project_id=PROJ, media_id=item["id"], user=viewer, db=db
                )
                assert meta["fileName"] == "doc.pdf"
                resp = await download_project_media_endpoint(
                    project_id=PROJ, media_id=item["id"], user=viewer, db=db
                )
                assert resp.body == b"%PDF-bytes"
                assert resp.media_type == "application/pdf"
                assert "doc.pdf" in resp.headers["content-disposition"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_api_delete_media_owner_success(monkeypatch):
    store = InMemoryObjectStore()
    monkeypatch.setattr("app.api.projects.default_project_media_store", lambda: store)

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                item = await upload_project_media_endpoint(
                    project_id=PROJ,
                    file=_upload("c.bin", b"contrib-bytes"),
                    kind=None,
                    source_model=None,
                    source_prompt=None,
                    chat_session_id=None,
                    user=contrib,
                    db=db,
                )
                result = await delete_project_media_endpoint(
                    project_id=PROJ, media_id=item["id"], user=owner, db=db
                )
                assert result == {"deleted": True}
                listed = await list_project_media_endpoint(
                    project_id=PROJ, user=owner, db=db, kind=None, q=None, limit=50, offset=0
                )
                assert listed["total"] == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_api_delete_media_contributor_other_403(monkeypatch):
    store = InMemoryObjectStore()
    monkeypatch.setattr("app.api.projects.default_project_media_store", lambda: store)

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup(db)
                item = await upload_project_media_endpoint(
                    project_id=PROJ,
                    file=_upload("owner.bin", b"owner-bytes"),
                    kind=None,
                    source_model=None,
                    source_prompt=None,
                    chat_session_id=None,
                    user=owner,
                    db=db,
                )
                try:
                    await delete_project_media_endpoint(
                        project_id=PROJ, media_id=item["id"], user=contrib, db=db
                    )
                    assert False
                except HTTPException as e:
                    assert e.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_api_media_not_found_404(monkeypatch):
    store = InMemoryObjectStore()
    monkeypatch.setattr("app.api.projects.default_project_media_store", lambda: store)

    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup(db)
                try:
                    await get_project_media_endpoint(
                        project_id=PROJ, media_id=99999, user=owner, db=db
                    )
                    assert False
                except HTTPException as e:
                    assert e.status_code == 404
                try:
                    await download_project_media_endpoint(
                        project_id=PROJ, media_id=99999, user=owner, db=db
                    )
                    assert False
                except HTTPException as e:
                    assert e.status_code == 404
                try:
                    await delete_project_media_endpoint(
                        project_id=PROJ, media_id=99999, user=owner, db=db
                    )
                    assert False
                except HTTPException as e:
                    assert e.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())
