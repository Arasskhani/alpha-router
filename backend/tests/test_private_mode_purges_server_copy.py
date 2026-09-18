"""Turning Private Mode on removes what the server already had.

The user agrees to two dialogs - "messages and media will be stored only in this
browser" and "this chat will be deleted when you log out or clear browser data".
The handler then set a flag in the browser and returned. Nothing removed the
server copy, so every message written before the toggle stayed on the server
permanently and the session stayed listable. The backend invariants were correct
for *new* writes; the gap was that nothing removed the past, while the consent
copy said it had.

``update_chat_session`` already refuses to convert a session that still has
messages, which is why this cannot be a plain PATCH: the removal and the flag
have to land in the same transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.chat import ChatMessage, ChatSession
from app.services.private_mode_service import PrivateModePersistenceError
from app.services.user_chat_storage_service import (
    append_session_messages,
    create_chat_session,
    purge_session_messages_for_private_mode,
    update_chat_session,
)


async def _chat_with_history(db_session, user) -> str:
    session = await create_chat_session(db_session, user.id, {"title": "Ordinary chat"})
    await append_session_messages(
        db_session,
        user.id,
        session["id"],
        [
            {"role": "user", "content": "something I would rather not keep"},
            {"role": "assistant", "content": "an answer"},
        ],
    )
    await db_session.flush()
    return session["id"]


async def test_the_server_copy_is_gone_after_enabling(db_session, user):
    session_id = await _chat_with_history(db_session, user)
    assert len((await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == session_id))).all()) == 2

    result = await purge_session_messages_for_private_mode(db_session, user.id, session_id)
    await db_session.flush()

    assert result is not None
    assert result["purgedMessages"] == 2
    remaining = (await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == session_id))).all()
    assert remaining == [], "messages written before the toggle stayed on the server"


async def test_the_session_is_marked_private_in_the_same_step(db_session, user):
    session_id = await _chat_with_history(db_session, user)

    await purge_session_messages_for_private_mode(db_session, user.id, session_id)
    await db_session.flush()

    row = await db_session.get(ChatSession, session_id)
    assert row.private_mode is True
    assert row.message_count == 0
    assert row.last_message_at is None


async def test_a_plain_patch_still_refuses_a_chat_with_history(db_session, user):
    """The invariant that makes the combined operation necessary."""

    session_id = await _chat_with_history(db_session, user)

    with pytest.raises(PrivateModePersistenceError):
        await update_chat_session(db_session, user.id, session_id, {"privateMode": True})


async def test_another_user_cannot_purge_your_chat(db_session, user):
    from app.core.security import hash_password
    from app.models.user import User

    session_id = await _chat_with_history(db_session, user)
    stranger = User(
        username="stranger",
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(stranger)
    await db_session.flush()

    assert await purge_session_messages_for_private_mode(db_session, stranger.id, session_id) is None
    remaining = (await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == session_id))).all()
    assert len(remaining) == 2
