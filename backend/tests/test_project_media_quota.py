"""Tests for configurable per-project media quota."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.project import (
    PROJECT_ROLE_PRIMARY_OWNER,
    Project,
    ProjectMediaAsset,
    ProjectMember,
)
from app.models.user import User
from app.services.project_media_service import (
    DEFAULT_PROJECT_MEDIA_QUOTA_GB,
    ProjectMediaQuotaError,
    count_projects_over_media_quota,
    ensure_project_media_quota,
    get_project_media_quota_bytes,
    get_project_media_quota_gb,
    invalidate_project_media_quota_cache,
    set_project_media_quota_gb,
)


async def _run_quota_roundtrip() -> None:
    invalidate_project_media_quota_cache()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        assert await get_project_media_quota_gb(session) == DEFAULT_PROJECT_MEDIA_QUOTA_GB
        assert await get_project_media_quota_bytes(session) == 1024 * 1024 * 1024

        await set_project_media_quota_gb(session, 5)
        await session.commit()
        assert await get_project_media_quota_gb(session) == 5
        assert await get_project_media_quota_bytes(session) == 5 * 1024 * 1024 * 1024

        owner = User(
            username="quota_owner",
            email="quota-owner@alpha-router.local",
            display_name="Quota",
            hashed_password="x",
            auth_provider="local",
        )
        session.add(owner)
        await session.flush()
        session.add(
            Project(
                id="quota-proj",
                name="Quota",
                status="active",
                visibility="private",
                created_by_user_id=owner.id,
                revision=1,
                acl_version=1,
            )
        )
        session.add(ProjectMember(project_id="quota-proj", user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))

        half_gb = (5 * 1024 * 1024 * 1024) // 2
        session.add(
            ProjectMediaAsset(
                project_id="quota-proj",
                uploaded_by_user_id=owner.id,
                kind="image",
                mime_type="image/png",
                file_name="a.png",
                storage_path="p/quota-proj/a.png",
                content_hash="abc123",
                size_bytes=half_gb,
            )
        )
        await session.commit()

        await ensure_project_media_quota(session, "quota-proj", half_gb)
        try:
            await ensure_project_media_quota(session, "quota-proj", half_gb + 1)
            raise AssertionError("expected quota exceeded")
        except ProjectMediaQuotaError as exc:
            assert exc.quota_bytes == 5 * 1024 * 1024 * 1024

        await set_project_media_quota_gb(session, 1)
        await session.commit()
        assert await count_projects_over_media_quota(session) == 1

        await set_project_media_quota_gb(session, 0)
        assert await get_project_media_quota_gb(session) == 1
        await set_project_media_quota_gb(session, 500)
        assert await get_project_media_quota_gb(session) == 100
    await engine.dispose()
    invalidate_project_media_quota_cache()


async def test_project_media_quota_settings():
    await _run_quota_roundtrip()
