"""Tests for project resource upload, listing, and deletion."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.knowledge import KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion
from app.models.project import (
    PROJECT_RESOURCE_STATUS_ACTIVE,
    PROJECT_RESOURCE_STATUS_PROCESSING,
    PROJECT_RESOURCE_STATUS_REVOKED,
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_OWNER,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    PROJECT_VISIBILITY_PRIVATE,
    PROJECT_VISIBILITY_PUBLIC,
    Project,
    ProjectMember,
    ProjectResource,
)
from app.models.user import User
from app.services.project_resource_service import (
    delete_project_resource,
    ensure_project_knowledge_base,
    list_project_resources,
    sync_project_resources_for_document,
    upload_project_resource,
)

PROJ_ID = "proj-res-1"


class InMemoryObjectStore:
    """Minimal in-memory implementation of KnowledgeObjectStoreProtocol for tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def put(self, key: str, body: bytes) -> None:
        self._store[key] = body

    async def get(self, key: str, *, max_bytes: int) -> bytes:
        return self._store[key]

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


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


def _fake_upload_bytes(name: str = "test.txt", content: str = "hello world") -> tuple[bytes, str, str]:
    return content.encode("utf-8"), name, "text/plain"


def test_ensure_knowledge_base_creates_once():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                project = await db.get(Project, PROJ_ID)
                kb1 = await ensure_project_knowledge_base(db, project=project)
                await db.flush()
                assert kb1 is not None
                assert project.knowledge_base_id == kb1.id

                # Calling again should return the same KB.
                kb2 = await ensure_project_knowledge_base(db, project=project)
                assert kb2.id == kb1.id
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_upload_resource_owner():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db,
                    project_id=PROJ_ID,
                    user=owner,
                    file_name=name,
                    declared_mime=mime,
                    data=data,
                    title="My Resource",
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                assert result.resource is not None
                assert result.resource.project_id == PROJ_ID
                assert result.resource.title == "My Resource"
                assert result.resource.status == PROJECT_RESOURCE_STATUS_PROCESSING
                assert result.submission.document is not None
                assert result.submission.version is not None
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_upload_resource_contributor():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, contrib, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db,
                    project_id=PROJ_ID,
                    user=contrib,
                    file_name=name,
                    declared_mime=mime,
                    data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                assert result.resource is not None
                assert result.resource.uploaded_by_user_id == contrib.id
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_upload_resource_viewer_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, _, viewer = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                from fastapi import HTTPException
                try:
                    await upload_project_resource(
                        db,
                        project_id=PROJ_ID,
                        user=viewer,
                        file_name=name,
                        declared_mime=mime,
                        data=data,
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_upload_resource_non_member_hidden():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, _, _ = await _setup_project(db)
                stranger = await _user(db, "stranger")
                data, name, mime = _fake_upload_bytes()
                from fastapi import HTTPException
                try:
                    await upload_project_resource(
                        db,
                        project_id=PROJ_ID,
                        user=stranger,
                        file_name=name,
                        declared_mime=mime,
                        data=data,
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_resources_owner():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(), title="A"
                )
                await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name="b.txt", declared_mime=mime, data=data, title="B",
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                items, total = await list_project_resources(db, project_id=PROJ_ID, user=owner)
                assert total == 2
                assert len(items) == 2
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_resources_viewer_can_see():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, viewer = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                items, total = await list_project_resources(db, project_id=PROJ_ID, user=viewer)
                assert total == 1
                assert len(items) == 1
                assert items[0]["versionStatus"] == "quarantined"
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_resources_shows_knowledge_review_status():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                result.submission.version.status = "review"
                await db.flush()
                items, total = await list_project_resources(db, project_id=PROJ_ID, user=owner)
                assert total == 1
                assert items[0]["versionStatus"] == "review"
                assert items[0]["status"] == PROJECT_RESOURCE_STATUS_PROCESSING
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_resources_public_project():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db, visibility=PROJECT_VISIBILITY_PUBLIC)
                data, name, mime = _fake_upload_bytes()
                await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                stranger = await _user(db, "stranger")
                items, total = await list_project_resources(db, project_id=PROJ_ID, user=stranger)
                assert total == 1
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_resources_non_member_private_hidden():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, _, _ = await _setup_project(db)
                stranger = await _user(db, "stranger")
                from fastapi import HTTPException
                try:
                    await list_project_resources(db, project_id=PROJ_ID, user=stranger)
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_list_resources_status_filter():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                # All resources start in processing status.
                items, total = await list_project_resources(
                    db, project_id=PROJ_ID, user=owner, status=PROJECT_RESOURCE_STATUS_PROCESSING
                )
                assert total == 1
                items, total = await list_project_resources(
                    db, project_id=PROJ_ID, user=owner, status="active"
                )
                assert total == 0
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_resource_owner():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                resource_id = result.resource.id
                deleted = await delete_project_resource(
                    db, project_id=PROJ_ID, resource_id=resource_id, user=owner
                )
                assert deleted is True
                resource = await db.get(ProjectResource, resource_id)
                assert resource.status == PROJECT_RESOURCE_STATUS_REVOKED
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_resource_contributor_own():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                _, contrib, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db, project_id=PROJ_ID, user=contrib, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                resource_id = result.resource.id
                deleted = await delete_project_resource(
                    db, project_id=PROJ_ID, resource_id=resource_id, user=contrib
                )
                assert deleted is True
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_resource_contributor_other_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, contrib, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                resource_id = result.resource.id
                from fastapi import HTTPException
                try:
                    await delete_project_resource(
                        db, project_id=PROJ_ID, resource_id=resource_id, user=contrib
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
            async with factory() as db:
                pass
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_resource_viewer_denied():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, viewer = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                resource_id = result.resource.id
                from fastapi import HTTPException
                try:
                    await delete_project_resource(
                        db, project_id=PROJ_ID, resource_id=resource_id, user=viewer
                    )
                    assert False
                except HTTPException as exc:
                    assert exc.status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_delete_resource_wrong_project_returns_false():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                # Try to delete from a different project.
                db.add(
                    Project(
                        id="proj-other",
                        name="Other",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(ProjectMember(project_id="proj-other", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
                await db.flush()
                deleted = await delete_project_resource(
                    db, project_id="proj-other", resource_id=result.resource.id, user=owner
                )
                assert deleted is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_resource_links_to_knowledge_base():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db, project_id=PROJ_ID, user=owner, file_name=name, declared_mime=mime, data=data,
                    object_store=InMemoryObjectStore(),
                )
                await db.flush()
                project = await db.get(Project, PROJ_ID)
                assert project.knowledge_base_id is not None
                kb = await db.get(KnowledgeBase, project.knowledge_base_id)
                assert kb is not None
                assert kb.access_type == "private"
                doc = await db.get(KnowledgeDocument, result.resource.document_id)
                assert doc is not None
                assert doc.knowledge_base_id == kb.id
        finally:
            await engine.dispose()

    asyncio.run(run())


async def _mark_latest_version_published(db, document_id: str) -> KnowledgeDocumentVersion:
    version = (
        await db.execute(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one()
    version.status = "published"
    await db.flush()
    return version


def test_list_promotes_published_resource_to_active():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db,
                    project_id=PROJ_ID,
                    user=owner,
                    file_name=name,
                    declared_mime=mime,
                    data=data,
                    object_store=InMemoryObjectStore(),
                    title="Guide",
                )
                await _mark_latest_version_published(db, result.resource.document_id)
                assert result.resource.status == PROJECT_RESOURCE_STATUS_PROCESSING
                items, _total = await list_project_resources(
                    db, project_id=PROJ_ID, user=owner
                )
                assert items[0]["status"] == PROJECT_RESOURCE_STATUS_ACTIVE
                assert items[0]["versionStatus"] == "published"
                resource = await db.get(ProjectResource, result.resource.id)
                assert resource.status == PROJECT_RESOURCE_STATUS_ACTIVE
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_approve_path_syncs_project_resource():
    async def run():
        factory, engine = await _session_factory()
        try:
            async with factory() as db:
                owner, _, _ = await _setup_project(db)
                data, name, mime = _fake_upload_bytes()
                result = await upload_project_resource(
                    db,
                    project_id=PROJ_ID,
                    user=owner,
                    file_name=name,
                    declared_mime=mime,
                    data=data,
                    object_store=InMemoryObjectStore(),
                )
                await _mark_latest_version_published(db, result.resource.document_id)
                updated = await sync_project_resources_for_document(
                    db, document_id=result.resource.document_id
                )
                assert updated == 1
                resource = await db.get(ProjectResource, result.resource.id)
                assert resource.status == PROJECT_RESOURCE_STATUS_ACTIVE
        finally:
            await engine.dispose()

    asyncio.run(run())
