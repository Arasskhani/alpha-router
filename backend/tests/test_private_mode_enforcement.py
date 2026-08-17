"""Server-side Private Mode cannot be bypassed by a client payload."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatSession
from app.models.user import User
from app.services.private_mode_service import (
    PrivateModePersistenceError,
    resolve_private_mode,
)
from app.services.user_chat_storage_service import (
    append_session_messages,
    create_chat_session,
    replace_session_messages,
    update_chat_session,
    update_last_session_message,
)


async def _exercise_private_mode_invariants() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            user = User(
                username="private-mode-user",
                email="private-mode@test",
                hashed_password="x",
                auth_provider="local",
            )
            db.add(user)
            await db.flush()

            with pytest.raises(PrivateModePersistenceError):
                await resolve_private_mode(
                    db,
                    {"private_mode": True, "persist_chat": True},
                    user_id=user.id,
                    source="alpha_router_chat",
                )

            await create_chat_session(
                db,
                user.id,
                {"id": "private-session", "privateMode": True},
            )
            context = await resolve_private_mode(
                db,
                {
                    "chat_session_id": "private-session",
                    "private_mode": False,
                    "persist_chat": False,
                },
                user_id=user.id,
                source="alpha_router_chat",
            )
            assert context.effective
            assert context.session_private

            with pytest.raises(PrivateModePersistenceError):
                await resolve_private_mode(
                    db,
                    {
                        "chat_session_id": "private-session",
                        "persist_chat": True,
                    },
                    user_id=user.id,
                    source="alpha_router_chat",
                )
            with pytest.raises(PrivateModePersistenceError):
                await append_session_messages(
                    db,
                    user.id,
                    "private-session",
                    [{"role": "user", "content": "must not persist"}],
                )
            with pytest.raises(PrivateModePersistenceError):
                await replace_session_messages(
                    db,
                    user.id,
                    "private-session",
                    [{"role": "user", "content": "must not persist"}],
                )
            with pytest.raises(PrivateModePersistenceError):
                await update_last_session_message(
                    db,
                    user.id,
                    "private-session",
                    "must not persist",
                )
            with pytest.raises(PrivateModePersistenceError):
                await update_chat_session(
                    db,
                    user.id,
                    "private-session",
                    {"privateMode": False},
                )

            await create_chat_session(
                db,
                user.id,
                {"id": "public-session", "privateMode": False},
            )
            await append_session_messages(
                db,
                user.id,
                "public-session",
                [{"role": "user", "content": "already persisted"}],
            )
            with pytest.raises(PrivateModePersistenceError):
                await update_chat_session(
                    db,
                    user.id,
                    "public-session",
                    {"privateMode": True},
                )

            private_row = await db.get(ChatSession, "private-session")
            assert private_row is not None
            assert private_row.message_count == 0
    finally:
        await engine.dispose()


def test_private_mode_is_enforced_by_server_storage() -> None:
    asyncio.run(_exercise_private_mode_invariants())
