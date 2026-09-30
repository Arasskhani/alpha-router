"""A turn's history made whole on the server.

A chat opened from the list holds only its latest page in the web app; a
turn built from that page sent the model a chat that started in the middle.
The client says where its history starts (``history_from_sequence``) and the
server puts the chat's older messages in front.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api import chat as chat_api
from app.config import get_settings
from app.core.security import create_access_token, hash_password
from app.models.chat import ChatMessage, ChatSession
from app.models.system import SystemSetting
from app.models.user import User
from app.services.chat_history_service import complete_chat_history, message_text_for_model
from app.services.chat_markers import (
    ATTACHMENT_MESSAGE_PREFIX,
    AUDIO_MESSAGE_PREFIX,
    IMAGE_MESSAGE_PREFIX,
    IMAGE_PENDING_MARKER,
)


async def _chat(
    db, user, count: int, *, private: bool = False, first: str = "My workout plan: squats on Monday."
) -> str:
    session_id = str(uuid.uuid4())
    db.add(ChatSession(id=session_id, user_id=user.id, title="Workout", private_mode=private))
    await db.flush()
    for sequence in range(1, count + 1):
        role = "user" if sequence % 2 else "assistant"
        content = first if sequence == 1 else f"{role} message {sequence}"
        db.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                user_id=user.id,
                role=role,
                content=content,
                sequence=sequence,
            )
        )
    await db.commit()
    return session_id


def _page(count: int, start: int) -> list[dict]:
    """What the web app sends for a chat opened on its latest page: messages start..count, then the new one."""
    out = [
        {"role": "user" if s % 2 else "assistant", "content": f"{'user' if s % 2 else 'assistant'} message {s}"}
        for s in range(start, count + 1)
    ]
    return [*out, {"role": "user", "content": "What was my workout plan?"}]


class TestCompletion:
    async def test_puts_the_older_messages_in_front(self, db_session, user):
        session_id = await _chat(db_session, user, 60)
        sent = [{"role": "system", "content": "Be brief."}, *_page(60, 11)]
        messages, added = await complete_chat_history(
            db_session, user=user, chat_session_id=session_id, messages=sent, history_from_sequence=11
        )
        assert added == 10
        assert [m["role"] for m in messages[:2]] == ["system", "user"]
        assert messages[1]["content"] == "My workout plan: squats on Monday."
        assert messages[10]["content"] == "assistant message 10"
        assert messages[11]["content"] == "user message 11"
        assert messages[-1]["content"] == "What was my workout plan?"
        assert len(messages) == len(sent) + 10

    async def test_leaves_a_whole_history_alone(self, db_session, user):
        session_id = await _chat(db_session, user, 20)
        sent = _page(20, 1)
        for start in (None, 1):
            messages, added = await complete_chat_history(
                db_session, user=user, chat_session_id=session_id, messages=sent, history_from_sequence=start
            )
            assert (messages, added) == (sent, 0)

    async def test_never_for_a_private_chat_or_someone_else_s(self, db_session, user):
        private = await _chat(db_session, user, 30, private=True)
        other = User(
            username="other",
            email="other@test",
            hashed_password=hash_password("x-password-1"),
            auth_provider="local",
            is_active=True,
        )
        db_session.add(other)
        await db_session.commit()
        theirs = await _chat(db_session, other, 30, first="Their secret.")
        for session_id in (private, theirs, "no-such-chat"):
            messages, added = await complete_chat_history(
                db_session, user=user, chat_session_id=session_id, messages=_page(30, 11), history_from_sequence=11
            )
            assert added == 0
            assert all("secret" not in m["content"] for m in messages)

    async def test_not_while_the_administrator_turned_it_off(self, db_session, user):
        session_id = await _chat(db_session, user, 30)
        db_session.add(SystemSetting(key="memory_history_completion_enabled", value="false"))
        await db_session.commit()
        _messages, added = await complete_chat_history(
            db_session, user=user, chat_session_id=session_id, messages=_page(30, 11), history_from_sequence=11
        )
        assert added == 0

    async def test_reads_back_only_as_much_as_a_window_could_hold(self, db_session, user, monkeypatch):
        from app.services import chat_history_service

        session_id = await _chat(db_session, user, 400)
        sent = _page(400, 391)
        # Read back in batches, every one of them in order when there is room.
        whole, added = await complete_chat_history(
            db_session, user=user, chat_session_id=session_id, messages=sent, history_from_sequence=391
        )
        assert added == 390 and whole[0]["content"] == "My workout plan: squats on Monday."
        assert [m["content"] for m in whole[1:390]] == [
            f"{'user' if n % 2 else 'assistant'} message {n}" for n in range(2, 391)
        ]
        monkeypatch.setattr(chat_history_service, "MAX_COMPLETED_CHARS", 1_000)
        messages, added = await complete_chat_history(
            db_session, user=user, chat_session_id=session_id, messages=sent, history_from_sequence=391
        )
        older = messages[:added]
        assert 0 < added < 390 and sum(len(m["content"]) for m in older) <= 1_000
        # The ones nearest the turn are the ones kept, in order.
        assert older[-1]["content"] == "assistant message 390"
        assert [m["content"] for m in older] == [
            f"{m['role']} message {n}" for n, m in zip(range(391 - added, 391), older, strict=True)
        ]

    async def test_a_failure_to_read_leaves_the_turn_and_its_transaction_as_they_were(
        self, db_session, user, monkeypatch
    ):
        from sqlalchemy import text

        from app.services import chat_history_service

        session_id = await _chat(db_session, user, 30)

        async def _broken(db, *_args, **_kwargs):
            await db.execute(text("SELECT no_such_column FROM chat_messages"))

        monkeypatch.setattr(chat_history_service, "older_chat_messages", _broken)
        db_session.add(SystemSetting(key="turn_marker", value="kept"))
        sent = _page(30, 11)
        messages, added = await complete_chat_history(
            db_session, user=user, chat_session_id=session_id, messages=sent, history_from_sequence=11
        )
        assert (messages, added) == (sent, 0)
        await db_session.commit()  # the turn's own transaction goes on (on PostgreSQL too)
        assert (await db_session.get(SystemSetting, "turn_marker")).value == "kept"


class TestTheModelsReading:
    def test_attachments_voice_and_media(self):
        attach = ATTACHMENT_MESSAGE_PREFIX + json.dumps(
            {
                "userText": "See the plan",
                "attachments": [
                    {"name": "plan.txt", "kind": "document", "text": "Monday: squats"},
                    {"name": "photo.jpg", "kind": "image", "url": "/api/chat/media/1"},
                    {"name": "data.bin", "kind": "file"},
                ],
            }
        )
        text = message_text_for_model(attach)
        assert "See the plan" in text and "--- plan.txt ---\nMonday: squats" in text
        assert "[Attached image(s): photo.jpg]" in text and "[Attached file: data.bin]" in text
        assert message_text_for_model(AUDIO_MESSAGE_PREFIX + json.dumps({"transcript": "Hello coach"})) == "Hello coach"
        assert (
            message_text_for_model(IMAGE_MESSAGE_PREFIX + json.dumps({"prompt": "a gym"})) == "[Generated image: a gym]"
        )
        assert message_text_for_model(IMAGE_PENDING_MARKER) == ""
        assert message_text_for_model("  plain words ") == "plain words"
        assert message_text_for_model(ATTACHMENT_MESSAGE_PREFIX + "{broken") == ATTACHMENT_MESSAGE_PREFIX + "{broken"


class TestTheEndpoint:
    @pytest.fixture
    def signed_in(self, client, user):
        settings = get_settings()
        client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
        client.cookies.set(settings.csrf_cookie_name, "csrf-token")
        return {settings.csrf_header_name: "csrf-token"}

    async def test_the_turn_goes_ahead_with_the_whole_chat(self, client, db_session, user, signed_in):
        session_id = await _chat(db_session, user, 60)
        seen: dict = {}

        async def preflight(_db, payload, **_kwargs):
            seen["messages"] = list(payload["messages"])
            raise HTTPException(status_code=418, detail="stop here")

        with patch.object(chat_api, "preflight_stream_chat", AsyncMock(side_effect=preflight)):
            resp = await client.post(
                "/api/chat/completions",
                json={
                    "model": "model::1",
                    "messages": _page(60, 11),
                    "chat_session_id": session_id,
                    "persist_chat": True,
                    "history_from_sequence": 11,
                },
                headers=signed_in,
            )
        assert resp.status_code == 418, resp.text
        assert seen["messages"][0]["content"] == "My workout plan: squats on Monday."
        assert len(seen["messages"]) == 61

    async def test_a_private_turn_is_never_completed(self, client, db_session, user, signed_in):
        session_id = await _chat(db_session, user, 60)
        seen: dict = {}

        async def preflight(_db, payload, **_kwargs):
            seen["messages"] = list(payload["messages"])
            raise HTTPException(status_code=418, detail="stop here")

        with patch.object(chat_api, "preflight_stream_chat", AsyncMock(side_effect=preflight)):
            await client.post(
                "/api/chat/completions",
                json={
                    "model": "model::1",
                    "messages": _page(60, 11),
                    "chat_session_id": session_id,
                    "private_mode": True,
                    "history_from_sequence": 11,
                },
                headers=signed_in,
            )
        assert len(seen["messages"]) == 51
