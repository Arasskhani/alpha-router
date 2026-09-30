"""Memories are looked up with the whole question, not its last line.

The lookup used the last message alone, and every word of it: "and on
Wednesday?" found nothing about the workout plan the question before it was
about, and "what", "the", "برای" matched anything. It now reads the chat's
title and its last three questions, newest first, without the words too
common to mean anything.
"""

from __future__ import annotations

import uuid

from app.models.chat import ChatSession
from app.services.user_memory_service import _lexical_rows, create_memory, extract_query_text
from app.utils.text_normalize import search_terms

CHAT = [
    {"role": "user", "content": "Tell me about my workout plan"},
    {"role": "assistant", "content": "It has squats and running."},
    {"role": "user", "content": "What do I do on Monday?"},
    {"role": "assistant", "content": "Squats."},
    {"role": "user", "content": "And on Wednesday?"},
]


def test_the_question_is_the_title_and_the_last_three_questions_newest_last():
    many = [*CHAT, {"role": "user", "content": "  "}, {"role": "user", "content": "And Friday?"}]
    assert extract_query_text(many, title="Gym") == "Gym\nWhat do I do on Monday?\nAnd on Wednesday?\nAnd Friday?"
    assert extract_query_text([]) == ""
    assert extract_query_text(CHAT, questions=1) == "And on Wednesday?"


def test_the_words_looked_for_leave_out_the_common_ones_and_start_from_the_newest():
    assert search_terms("Gym\nWhat is the plan for this week?\nبرنامه ورزشی من برای امروز چی بود؟") == [
        "برنامه",
        "ورزشی",
        "امروز",
        "plan",
        "week",
        "gym",
    ]
    assert search_terms("كد پستي ۱۲۳۴۵، لطفا") == ["پستی", "12345"]
    assert len(search_terms(" ".join(f"word{n}" for n in range(30)))) == 12


async def test_a_follow_up_question_finds_what_the_conversation_is_about(db_session, user):
    for content in (
        "User's workout plan: squats on Monday, running on Tuesday",
        "User prefers black coffee",
        "User lives in Tehran",
    ):
        await create_memory(db_session, user.id, content, origin="manual")
    await db_session.commit()
    last_line_only = await _lexical_rows(db_session, user.id, extract_query_text(CHAT, questions=1), limit=5)
    assert last_line_only == []
    found = await _lexical_rows(db_session, user.id, extract_query_text(CHAT), limit=5)
    assert [row.content for row in found] == ["User's workout plan: squats on Monday, running on Tuesday"]


async def test_a_turn_looks_memories_up_with_its_own_chat_s_title(db_session, user, monkeypatch):
    from types import SimpleNamespace

    from app.services.chat_turn_context import build_turn_context

    seen: dict = {}

    async def _memory(_db, messages, **kwargs):
        seen["query"] = kwargs["query"]
        return messages

    async def _same(_db, messages, **_kwargs):
        return messages

    monkeypatch.setattr("app.services.chat_turn_context.augment_messages_with_memory", _memory)
    for name in ("augment_messages_with_profile", "augment_messages_with_project_context"):
        monkeypatch.setattr(f"app.services.chat_turn_context.{name}", _same)
    session = ChatSession(id=str(uuid.uuid4()), user_id=user.id, title="Gym", model_id="m", private_mode=False)
    db_session.add(session)
    await db_session.commit()
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(provider_type="openai", external_id="gpt-4o-mini", display_name="G", connection_id=7),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openai",
        model_id="gpt-4o-mini",
        budget_reservation_id=None,
        code_interpreter_capacity_permit=None,
        code_interpreter_workspace_files=None,
        agent_turn=None,
    )
    ctx = await build_turn_context(
        db_session,
        {"model": "model::1", "messages": CHAT, "chat_session_id": session.id},
        resolved,
        user_id=user.id,
        username=user.username,
        source="alpha_router_chat",
        skip_budget=True,
        alpha_router_api_key_id=None,
    )
    await ctx.lease.abandon("test over")
    assert seen["query"] == "Gym\nTell me about my workout plan\nWhat do I do on Monday?\nAnd on Wednesday?"


async def test_a_failure_to_read_the_title_leaves_the_turn_s_transaction_usable(db_session, user, monkeypatch):
    from sqlalchemy import text

    from app.models.system import SystemSetting
    from app.services.chat_turn_context import own_session_title

    async def _broken(*_args, **_kwargs):
        await db_session.execute(text("SELECT no_such_column FROM chat_sessions"))

    db_session.add(SystemSetting(key="turn_marker", value="kept"))
    monkeypatch.setattr(db_session, "get", _broken)
    assert await own_session_title(db_session, "any-chat", user.id) is None
    monkeypatch.undo()
    await db_session.commit()  # on PostgreSQL too: the failed read took only its savepoint with it
    assert (await db_session.get(SystemSetting, "turn_marker")).value == "kept"
