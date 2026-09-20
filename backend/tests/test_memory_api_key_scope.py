"""Whose chat is it, when the turn arrives on a personal API key?

Browser chat and the OpenAI-compatible gateway share preflight_stream_chat, so
they shared the memory injection too: paste a personal key into an editor, a
cron script or a service the team calls, and the owner's durable personal
facts — health and financial ones included, when the admin allows those
categories — went into that app's prompt. Private Mode does not help; a
gateway request carries no session and no flag, so it resolves to non-private
every time.

Nothing is learned on that path either way, because gateway turns are never
persisted as a chat session and so never schedule extraction. Reading without
writing is exactly the asymmetry worth an explicit switch.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.user_chat_storage_service import save_user_prefs
from app.services.user_memory_service import augment_messages_with_memory, create_memory

ASK = [{"role": "user", "content": "what should I avoid?"}]


@pytest.fixture
async def keyholder(db_session: AsyncSession) -> User:
    user = User(
        username="keyholder",
        email="key@alpha-router.local",
        hashed_password="x",
        auth_provider="local",
    )
    db_session.add(user)
    await db_session.flush()
    await create_memory(db_session, user.id, "User takes lisinopril daily", category="health", origin="auto")
    await db_session.commit()
    return user


def _injected(messages: list[dict]) -> bool:
    return any("## User memory" in str(message.get("content") or "") for message in messages)


async def test_browser_chat_still_gets_the_memories(db_session, keyholder) -> None:
    out = await augment_messages_with_memory(db_session, list(ASK), user_id=keyholder.id)
    assert _injected(out)


async def test_an_api_key_turn_gets_nothing_by_default(db_session, keyholder) -> None:
    out = await augment_messages_with_memory(db_session, list(ASK), user_id=keyholder.id, via_api_key=True)
    assert not _injected(out)
    assert out == ASK


async def test_an_api_key_turn_gets_them_once_the_user_opts_in(db_session, keyholder) -> None:
    await save_user_prefs(db_session, keyholder.id, {"memory_outside_chat": True})
    await db_session.commit()
    out = await augment_messages_with_memory(db_session, list(ASK), user_id=keyholder.id, via_api_key=True)
    assert _injected(out)


async def test_opting_in_does_not_override_the_master_switch(db_session, keyholder) -> None:
    await save_user_prefs(db_session, keyholder.id, {"memory_outside_chat": True, "memory_enabled": False})
    await db_session.commit()
    for via_api_key in (False, True):
        out = await augment_messages_with_memory(db_session, list(ASK), user_id=keyholder.id, via_api_key=via_api_key)
        assert not _injected(out)


async def test_private_mode_still_wins_over_the_opt_in(db_session, keyholder) -> None:
    await save_user_prefs(db_session, keyholder.id, {"memory_outside_chat": True})
    await db_session.commit()
    out = await augment_messages_with_memory(
        db_session, list(ASK), user_id=keyholder.id, private_mode=True, via_api_key=True
    )
    assert not _injected(out)
