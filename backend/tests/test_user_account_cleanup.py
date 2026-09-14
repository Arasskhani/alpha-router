"""Tests for user account cleanup on delete."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatSession, UserChatPrefs, UserMemory
from app.models.media import MediaAsset
from app.models.user import User
from app.services.object_storage_service import cdn_user_prefix
from app.services.storage_service import user_storage_slug
from app.services.user_account_cleanup_service import purge_user_account_data


def test_cdn_user_prefix_uses_username_slug():

    slug = user_storage_slug("admin")

    assert cdn_user_prefix(slug) == "cdn/u/admin/"

    assert cdn_user_prefix("1") == "cdn/u/1/"


def test_cdn_user_prefix_sanitizes_unsafe_chars():

    slug = user_storage_slug("user@corp.local")

    assert cdn_user_prefix(slug) == "cdn/u/user@corp.local/"


async def _purge_roundtrip(monkeypatch) -> None:

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        user = User(username="alice", email="a@test.local", auth_provider="local")

        db.add(user)

        await db.flush()

        db.add(
            MediaAsset(
                user_id=user.id,
                kind="image",
                mime_type="image/png",
                file_name="a.png",
                storage_path="cdn/u/alice/abc123.png",
                content_hash="abc123",
                size_bytes=10,
            )
        )

        db.add(
            ChatSession(
                id="s1",
                user_id=user.id,
                title="Hi",
                model_id="gpt-4",
            )
        )

        db.add(UserChatPrefs(user_id=user.id, prefs={}))

        db.add(
            UserMemory(
                id="mem1",
                user_id=user.id,
                content="Likes tea",
                enabled=True,
                content_hash="abc",
            )
        )

        await db.commit()

        deleted_objects: list[str] = []

        def fake_purge(slug: str, user_id: int) -> int:

            deleted_objects.append(f"{slug}:{user_id}")

            return 2

        monkeypatch.setattr(
            "app.services.user_account_cleanup_service.oss.purge_user_cdn_objects",
            fake_purge,
        )

        unlinked: list[str] = []

        async def fake_unlink(_db, path: str) -> None:

            unlinked.append(path)

        monkeypatch.setattr(
            "app.services.user_media_service.unlink_storage_if_unreferenced",
            fake_unlink,
        )

        stats = await purge_user_account_data(db, user_id=user.id, username=user.username)

        await db.commit()

        assert stats["media_rows"] == 1

        assert stats["chat_store"] == 1

        assert stats["object_storage_objects"] == 2

        assert unlinked == ["cdn/u/alice/abc123.png"]

        assert deleted_objects == [f"alice:{user.id}"]

        media_left = (await db.execute(select(MediaAsset).where(MediaAsset.user_id == user.id))).scalars().all()

        chat_left = await db.get(ChatSession, "s1")

        prefs_left = await db.get(UserChatPrefs, user.id)

        memory_left = await db.get(UserMemory, "mem1")

        assert not media_left

        assert chat_left is None

        assert prefs_left is None

        assert memory_left is None

    await engine.dispose()


async def test_purge_user_account_data_removes_media_and_chat(monkeypatch):

    await _purge_roundtrip(monkeypatch)
