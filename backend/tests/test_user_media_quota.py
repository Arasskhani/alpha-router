"""Tests for configurable per-user media quota."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.media import MediaAsset
from app.models.user import User
from app.services.user_media_service import (
    DEFAULT_USER_MEDIA_QUOTA_GB,
    MediaQuotaExceededError,
    count_users_over_media_quota,
    ensure_user_media_quota,
    get_user_media_quota_bytes,
    get_user_media_quota_gb,
    set_user_media_quota_gb,
    user_media_quota_summary,
)


async def _run_quota_roundtrip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        assert await get_user_media_quota_gb(session) == DEFAULT_USER_MEDIA_QUOTA_GB
        assert await get_user_media_quota_bytes(session) == 1024 * 1024 * 1024

        await set_user_media_quota_gb(session, 5)
        await session.commit()
        assert await get_user_media_quota_gb(session) == 5
        assert await get_user_media_quota_bytes(session) == 5 * 1024 * 1024 * 1024

        user = User(
            username="quota_user",
            email="quota@nitro.local",
            display_name="Quota",
            hashed_password="x",
            role="user",
            auth_provider="local",
        )
        session.add(user)
        await session.flush()

        half_gb = 512 * 1024 * 1024
        session.add(
            MediaAsset(
                user_id=user.id,
                kind="image",
                mime_type="image/png",
                file_name="a.png",
                storage_path="u/quota/a.png",
                content_hash="abc123",
                size_bytes=half_gb,
            )
        )
        await session.commit()

        summary = await user_media_quota_summary(session, user.id)
        assert summary["quota_bytes"] == 5 * 1024 * 1024 * 1024
        assert summary["used_bytes"] == half_gb

        await ensure_user_media_quota(session, user.id, half_gb)
        try:
            await ensure_user_media_quota(session, user.id, half_gb + 1)
            raise AssertionError("expected quota exceeded")
        except MediaQuotaExceededError as exc:
            assert exc.quota_bytes == 5 * 1024 * 1024 * 1024

        await set_user_media_quota_gb(session, 1)
        await session.commit()
        assert await count_users_over_media_quota(session) == 1
    await engine.dispose()


def test_user_media_quota_settings():
    asyncio.run(_run_quota_roundtrip())
