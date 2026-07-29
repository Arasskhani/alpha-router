"""Security-focused unit tests for profile settings (prefs, import, TOTP)."""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.chat_import_export import (
    ChatImportError,
    detect_import_format,
    finalize_imported_messages,
    parse_import_sessions,
    import_user_chats,
    export_user_chats,
)
from app.services.totp_service import (
    consume_backup_code,
    encrypt_totp_secret,
    decrypt_totp_secret,
    generate_backup_codes,
    generate_totp_secret,
    hash_backup_codes,
    is_local_user,
    verify_totp_code,
)
from app.services.user_chat_storage_service import (
    append_session_messages,
    create_chat_session,
    load_user_prefs,
    save_user_prefs,
)


def test_prefs_timezone_and_language_normalization():
    async def _run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            db.add(
                User(
                    username="prefs-user",
                    email="prefs@alpha-router.local",
                    hashed_password="x",
                    role="user",
                    auth_provider="local",
                )
            )
            await db.commit()
            from sqlalchemy import select

            user = (await db.execute(select(User))).scalar_one()
            prefs = await save_user_prefs(
                db,
                user.id,
                {"timezone": "Asia/Tehran", "language": "fr", "theme": "dark"},
            )
            assert prefs["timezone"] == "Asia/Tehran"
            assert prefs["language"] == "en"  # only English accepted
            assert prefs["theme"] == "dark"

            system_prefs = await save_user_prefs(db, user.id, {"theme": "system"})
            assert system_prefs["theme"] == "system"

            bad = await save_user_prefs(db, user.id, {"timezone": "../../../etc/passwd"})
            assert bad["timezone"] == "UTC"

            loaded = await load_user_prefs(db, user.id)
            assert loaded["timezone"] == "UTC"
            assert loaded["language"] == "en"

    asyncio.run(_run())


def test_import_format_detection_and_reject_garbage():
    assert detect_import_format({"format": "alpha-router-chats", "version": 1, "sessions": []}) == "alpha-router-chats"
    assert detect_import_format([{"mapping": {}, "title": "t"}]) == "chatgpt"
    assert detect_import_format({"chats": []}) == "openwebui"
    try:
        detect_import_format({"foo": 1})
        raise AssertionError("expected ChatImportError")
    except ChatImportError:
        pass


def test_chatgpt_import_mapping_linearization():
    payload = [
        {
            "title": "Sample",
            "mapping": {
                "r": {"id": "r", "parent": None, "children": ["m1"], "message": None},
                "m1": {
                    "id": "m1",
                    "parent": "r",
                    "children": ["m2"],
                    "message": {
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["Hello"]},
                    },
                },
                "m2": {
                    "id": "m2",
                    "parent": "m1",
                    "children": [],
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text", "parts": ["Hi there"]},
                    },
                },
            },
        }
    ]
    fmt, sessions = parse_import_sessions(payload)
    assert fmt == "chatgpt"
    assert len(sessions) == 1
    assert sessions[0]["messages"][0]["content"] == "Hello"
    assert sessions[0]["messages"][1]["role"] == "assistant"


def test_finalize_imported_messages_sets_received_at():
    finalized = finalize_imported_messages(
        [
            {"role": "user", "content": "hi", "timestamp": 1_700_000_000},
            {"role": "assistant", "content": "hello"},
        ]
    )
    assert finalized[0]["role"] == "user"
    assert finalized[0]["sentAt"]
    assert finalized[1]["role"] == "assistant"
    assert finalized[1]["receivedAt"]
    assert finalized[1]["streaming"] is False


def test_import_assistant_messages_have_received_at():
    async def _run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            from sqlalchemy import select

            from app.services.user_chat_storage_service import list_session_messages

            db.add(
                User(
                    username="imp",
                    email="imp@alpha-router.local",
                    hashed_password="x",
                    role="user",
                    auth_provider="local",
                )
            )
            await db.commit()
            user = (await db.execute(select(User))).scalar_one()
            result = await import_user_chats(
                db,
                user.id,
                {
                    "chats": [
                        {
                            "title": "OWUI",
                            "chat": {
                                "messages": [
                                    {"role": "user", "content": "Q", "timestamp": 1700000000},
                                    {"role": "assistant", "content": "A", "timestamp": 1700000001},
                                ]
                            },
                        }
                    ]
                },
            )
            assert result["imported"] == 1
            from app.models.chat import ChatSession

            session = (
                await db.execute(select(ChatSession).where(ChatSession.user_id == user.id))
            ).scalar_one()
            msgs, _ = await list_session_messages(db, user.id, session.id)
            assert msgs[-1]["role"] == "assistant"
            assert msgs[-1].get("receivedAt") is not None
            assert msgs[-1].get("streaming") is not True

    asyncio.run(_run())


def test_export_import_roundtrip_new_ids():
    async def _run() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            from sqlalchemy import select

            db.add(
                User(
                    username="exp",
                    email="exp@alpha-router.local",
                    hashed_password="x",
                    role="user",
                    auth_provider="local",
                )
            )
            await db.commit()
            user = (await db.execute(select(User))).scalar_one()
            await create_chat_session(db, user.id, {"id": "orig-1", "title": "T", "model": "m"})
            await append_session_messages(
                db,
                user.id,
                "orig-1",
                [{"role": "user", "content": "secret note", "clientMessageId": "c1"}],
            )
            exported = await export_user_chats(db, user.id)
            assert exported["format"] == "alpha-router-chats"
            assert "hashed_password" not in str(exported)
            assert exported["sessions"][0]["messages"][0]["content"] == "secret note"

            result = await import_user_chats(db, user.id, exported)
            assert result["imported"] == 1
            # New session id — not overwriting orig-1 by foreign id reuse as same row
            from app.models.chat import ChatSession

            rows = (await db.execute(select(ChatSession).where(ChatSession.user_id == user.id))).scalars().all()
            ids = {r.id for r in rows}
            assert len(rows) == 2
            assert "orig-1" in ids
            assert any(i != "orig-1" for i in ids)

    asyncio.run(_run())


def test_totp_secret_encrypted_and_backup_codes_one_time():
    secret = generate_totp_secret()
    enc = encrypt_totp_secret(secret)
    assert enc != secret
    assert decrypt_totp_secret(enc) == secret

    import pyotp

    code = pyotp.TOTP(secret).now()
    assert verify_totp_code(secret, code)
    assert not verify_totp_code(secret, "000000")

    codes = generate_backup_codes()
    hashed = hash_backup_codes(codes)
    remaining = consume_backup_code(hashed, codes[0])
    assert remaining is not None
    assert len(remaining) == len(hashed) - 1
    # same code cannot be reused
    assert consume_backup_code(remaining, codes[0]) is None


def test_is_local_user_gate():
    class U:
        auth_provider = "saml"

    assert not is_local_user(U())

    class L:
        auth_provider = "local"

    assert is_local_user(L())
