"""Tests for DB-backed chat storage."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatSession
from app.models.user import User
from app.services.user_chat_storage_service import (
    RevisionConflictError,
    append_session_messages,
    create_chat_folder,
    create_chat_session,
    list_chat_folders,
    list_chat_sessions,
    list_session_messages,
    load_user_prefs,
    replace_session_messages,
    save_user_prefs,
    update_chat_session,
    update_last_session_message,
)


async def _run_roundtrip() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="tester",
                email="tester@nitro.local",
                display_name="Tester",
                hashed_password="x",
                role="user",
                auth_provider="local",
            )
        )
        await session.commit()

        user = (await session.execute(select(User))).scalar_one()
        prefs = await save_user_prefs(session, user.id, {"default_model": "gpt-4", "theme": "dark"})
        assert prefs["default_model"] == "gpt-4"
        assert prefs["theme"] == "dark"

        folder = await create_chat_folder(session, user.id, {"id": "f1", "name": "Work"})
        assert folder["name"] == "Work"

        chat = await create_chat_session(
            session,
            user.id,
            {"id": "s1", "title": "Hello", "model": "gpt-4"},
        )
        assert chat["title"] == "Hello"
        assert chat["revision"] == 1

        dup = await create_chat_session(
            session,
            user.id,
            {"id": "s1", "title": "Other", "model": "gpt-4"},
        )
        assert dup["id"] == "s1"
        assert dup["title"] == "Hello"

        await append_session_messages(
            session,
            user.id,
            "s1",
            [{"role": "user", "content": "Hi", "clientMessageId": "m1"}],
        )
        msgs, has_more = await list_session_messages(session, user.id, "s1")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hi"
        assert not has_more

        sessions, total, _older = await list_chat_sessions(session, user.id)
        assert total == 1
        assert sessions[0]["title"] == "Hello"
        assert sessions[0]["messageCount"] == 1
        assert sessions[0]["revision"] == 2

        # Idempotent append via clientMessageId
        await append_session_messages(
            session,
            user.id,
            "s1",
            [{"role": "user", "content": "Hi", "clientMessageId": "m1"}],
            expected_revision=2,
        )
        msgs, _ = await list_session_messages(session, user.id, "s1")
        assert len(msgs) == 1

        folders = await list_chat_folders(session, user.id)
        assert folders[0]["name"] == "Work"

        await replace_session_messages(
            session,
            user.id,
            "s1",
            [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
            expected_revision=2,
        )
        msgs, _ = await list_session_messages(session, user.id, "s1")
        assert len(msgs) == 2

        defaults = await load_user_prefs(session, user.id)
        assert defaults["default_model"] == "gpt-4"

        row = await session.get(ChatSession, "s1")
        assert row is not None
        assert row.message_count == 2

        updated = await update_chat_session(
            session,
            user.id,
            "s1",
            {"title": "Renamed"},
            expected_revision=row.revision,
        )
        assert updated is not None
        assert updated["title"] == "Renamed"

        try:
            await update_chat_session(
                session,
                user.id,
                "s1",
                {"title": "Conflict"},
                expected_revision=1,
            )
            assert False, "expected RevisionConflictError"
        except RevisionConflictError as exc:
            assert exc.current_revision >= 2

        patched = await update_last_session_message(
            session,
            user.id,
            "s1",
            "Hello!",
            expected_revision=updated["revision"],
        )
        assert patched is not None
        msgs, _ = await list_session_messages(session, user.id, "s1")
        assert msgs[-1]["content"] == "Hello!"

        since_sessions, _, __ = await list_chat_sessions(session, user.id, since_ms=0)
        assert len(since_sessions) >= 1

        title_hits, _, __ = await list_chat_sessions(session, user.id, q="Rename")
        assert len(title_hits) == 1
    await engine.dispose()


def test_chat_store_roundtrip():
    asyncio.run(_run_roundtrip())


def test_dt_to_ms_interprets_naive_as_utc():
    import datetime as dt

    from app.services.user_chat_storage_service import _dt_to_ms

    naive = dt.datetime(2026, 1, 15, 12, 0, 0)
    expected = int(dt.datetime(2026, 1, 15, 12, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert _dt_to_ms(naive) == expected


async def _run_activity_filters() -> None:
    import datetime as dt

    from app.services.user_chat_storage_service import _dt_to_ms

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="activity",
                email="activity@test",
                display_name="Activity",
                hashed_password="x",
                role="user",
                auth_provider="local",
            )
        )
        await session.commit()
        user = (await session.execute(select(User))).scalar_one()

        await create_chat_session(session, user.id, {"id": "old", "title": "Old", "model": "gpt-4"})
        await append_session_messages(
            session,
            user.id,
            "old",
            [{"role": "user", "content": "old msg", "clientMessageId": "old-m1"}],
        )
        old_row = await session.get(ChatSession, "old")
        assert old_row is not None
        old_row.last_message_at = dt.datetime.utcnow() - dt.timedelta(days=10)
        await session.commit()

        await create_chat_session(session, user.id, {"id": "new", "title": "New", "model": "gpt-4"})
        await append_session_messages(
            session,
            user.id,
            "new",
            [{"role": "user", "content": "new msg", "clientMessageId": "new-m1"}],
        )
        await session.commit()

        cutoff_ms = _dt_to_ms(dt.datetime.utcnow() - dt.timedelta(days=7))
        recent, recent_total, older_total = await list_chat_sessions(
            session, user.id, min_activity_ms=cutoff_ms,
        )
        assert recent_total >= 1
        assert any(s["id"] == "new" for s in recent)
        assert older_total >= 1

        older, older_count, _ = await list_chat_sessions(
            session, user.id, max_activity_ms=cutoff_ms,
        )
        assert older_count >= 1
        assert any(s["id"] == "old" for s in older)
        assert sessions_have_last_message_at(older)


def sessions_have_last_message_at(rows):
    return all("lastMessageAt" in r for r in rows)


def test_activity_filters():
    asyncio.run(_run_activity_filters())


def test_compact_attachment_strips_data_url_for_storage():
    from app.services.user_chat_storage_service import (
        ATTACHMENT_MESSAGE_PREFIX,
        _compact_attachment_content_for_storage,
    )

    huge_b64 = "A" * (600 * 1024)
    raw = (
        ATTACHMENT_MESSAGE_PREFIX
        + '{"userText":"edit","attachments":[{"name":"photo.png","kind":"image","mime_type":"image/png","url":"/api/chat/media/x/file","data_url":"data:image/png;base64,'
        + huge_b64
        + '"}]}'
    )
    compact = _compact_attachment_content_for_storage(raw)
    assert "data_url" not in compact
    assert "/api/chat/media/x/file" in compact
    assert len(compact.encode("utf-8")) < 512 * 1024


async def _run_attachment_append():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add(
            User(
                username="attach_user",
                email="attach@test",
                display_name="Attach",
                hashed_password="x",
                role="user",
                auth_provider="local",
            )
        )
        await session.commit()
        user = (await session.execute(select(User))).scalar_one()

        from app.services.user_chat_storage_service import ATTACHMENT_MESSAGE_PREFIX

        await create_chat_session(
            session,
            user.id,
            {"id": "attach-s1", "title": "Attach", "model": "gpt-4"},
        )
        huge_b64 = "B" * (600 * 1024)
        content = (
            ATTACHMENT_MESSAGE_PREFIX
            + '{"userText":"edit image","attachments":[{"name":"photo.png","kind":"image","mime_type":"image/png","url":"/api/chat/media/y/file","data_url":"data:image/png;base64,'
            + huge_b64
            + '"}]}'
        )
        await append_session_messages(
            session,
            user.id,
            "attach-s1",
            [{"role": "user", "content": content, "clientMessageId": "attach-m1"}],
        )
        msgs, _ = await list_session_messages(session, user.id, "attach-s1")
        assert len(msgs) == 1
        assert "data_url" not in msgs[0]["content"]
        assert "edit image" in msgs[0]["content"]
    await engine.dispose()


def test_append_attachment_message_without_storage_limit_error():
    asyncio.run(_run_attachment_append())
