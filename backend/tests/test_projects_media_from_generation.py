"""Generated image/video bytes are copied into the project media library best-effort."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.project import PROJECT_ROLE_PRIMARY_OWNER, Project, ProjectMember, ProjectMediaAsset
from app.models.user import User
from app.services.project_media_service import (
    maybe_save_generated_media_to_project,
    upload_project_media,
)

PROJ = "media-gen-1"


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


async def _setup(db):
    owner = await _user(db, "owner")
    db.add(
        Project(
            id=PROJ,
            name="Gen",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    await db.flush()
    return owner


async def _count_media(db) -> int:
    from sqlalchemy import func, select

    return int(
        (
            await db.execute(
                select(func.count()).select_from(ProjectMediaAsset).where(
                    ProjectMediaAsset.project_id == PROJ
                )
            )
        ).scalar()
        or 0
    )


def test_generated_image_saved_to_project_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _setup(db)
                store = InMemoryObjectStore()
                saved = await maybe_save_generated_media_to_project(
                    db,
                    project_id=PROJ,
                    user=owner,
                    content_bytes=b"\x89PNG generated-image",
                    mime_type="image/png",
                    file_name="generated.png",
                    kind="image",
                    source_model="test-model",
                    source_prompt="a fox",
                    chat_session_id="sess-gen",
                    object_store=store,
                )
                assert saved is not None
                assert saved["projectId"] == PROJ
                assert saved["kind"] == "image"
                assert saved["sourcePrompt"] == "a fox"
                assert await _count_media(db) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_personal_generation_does_not_write_project_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _setup(db)
                store = InMemoryObjectStore()
                saved = await maybe_save_generated_media_to_project(
                    db,
                    project_id=None,
                    user=owner,
                    content_bytes=b"\x89PNG personal",
                    mime_type="image/png",
                    file_name="generated.png",
                    kind="image",
                    object_store=store,
                )
                assert saved is None
                assert await _count_media(db) == 0
                assert store._store == {}
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_quota_skip_does_not_fail_generation():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _setup(db)
                store = InMemoryObjectStore()
                await upload_project_media(
                    db,
                    project_id=PROJ,
                    user=owner,
                    file_name="fill.bin",
                    mime_type="application/octet-stream",
                    content_bytes=b"x" * 20,
                    object_store=store,
                    quota_bytes=20,
                )
                saved = await maybe_save_generated_media_to_project(
                    db,
                    project_id=PROJ,
                    user=owner,
                    content_bytes=b"y" * 8,
                    mime_type="image/png",
                    file_name="generated.png",
                    kind="image",
                    object_store=store,
                    quota_bytes=20,
                )
                assert saved is None
                assert await _count_media(db) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())
