"""A chat turn is fitted into the model's context window before it is sent.

A chat longer than the model's window went to the provider whole and came
back as a "context length exceeded" error. Now the oldest messages give way
to the newest: the system messages stay, the newest messages stay word for
word, and the model is told what was left out (or reads the chat's summary
in its place).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.system import SystemSetting
from app.services.chat_turn_context import build_turn_context
from app.services.context_fit_service import LEFT_OUT_NOTE, fit_turn_to_context, fittable, model_window

WINDOW = 4_000


def _model(context_length: int | None = WINDOW) -> SimpleNamespace:
    return SimpleNamespace(
        provider_type="openai",
        external_id="gpt-4o-mini",
        display_name="GPT",
        connection_id=7,
        context_length=context_length,
        input_cost_per_1k=0.001,
        output_cost_per_1k=0.002,
    )


def _chat(count: int, *, chars: int = 200) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": "Be brief."}]
    for index in range(1, count + 1):
        role = "user" if index % 2 else "assistant"
        messages.append({"role": role, "content": f"message {index} " + "word " * (chars // 5)})
    messages.append({"role": "user", "content": "What did I say first?"})
    return messages


async def _fit(db, messages, **kwargs):
    return await fit_turn_to_context(
        db, messages, ai_model=kwargs.pop("ai_model", _model()), provider_type="openai", model="gpt-4o-mini", **kwargs
    )


class TestFitting:
    async def test_a_turn_that_fits_is_sent_as_it_is(self, db_session):
        messages = _chat(6)
        fit = await _fit(db_session, messages)
        assert fit.messages is messages and fit.dropped == 0 and fit.metadata() is None

    async def test_the_oldest_give_way_to_the_newest(self, db_session):
        messages = _chat(200)
        fit = await _fit(db_session, messages)
        assert fit.window == WINDOW and fit.budget == WINDOW * 75 // 100
        assert fit.tokens_before > fit.budget >= fit.tokens_after
        kept = fit.messages
        assert kept[0] == {"role": "system", "content": "Be brief."}
        assert (
            kept[1]["role"] == "system" and "oldest messages of this conversation were left out" in kept[1]["content"]
        )
        # The newest 20 word for word, the new one last.
        assert kept[-20:] == messages[-20:]
        assert kept[-1]["content"] == "What did I say first?"
        assert fit.dropped == len(messages) - len(kept) + 1
        assert fit.metadata() == {"dropped": fit.dropped, "summarized": 0}
        assert LEFT_OUT_NOTE.format(count=fit.dropped) == kept[1]["content"]

    async def test_a_turn_over_the_share_that_leaves_room_to_answer_is_sent_whole(self, db_session):
        # About 3,300 tokens: over the 75% share (3,000) of a 4,000 window, with room left to answer.
        messages = _chat(16, chars=1_000)
        fit = await _fit(db_session, messages)
        assert fit.tokens_before > fit.budget
        assert fit.messages is messages and fit.dropped == 0

    async def test_a_turn_that_leaves_no_room_to_answer_is_brought_down_to_the_share(self, db_session):
        # About 3,800 tokens: past the 3,500 that leave the answer room in a 4,000 window.
        messages = _chat(60, chars=300)
        fit = await _fit(db_session, messages)
        assert fit.tokens_before > WINDOW - 500
        assert fit.dropped > 0 and fit.tokens_after <= fit.budget == WINDOW * 75 // 100

    async def test_a_summary_stands_in_for_what_it_covers(self, db_session):
        messages = _chat(200)
        summary = SimpleNamespace(covered=150, text="Summary of the earlier part: the user squats on Monday.")
        fit = await _fit(db_session, messages, summary=summary)
        assert fit.messages[1] == {"role": "system", "content": summary.text}
        assert fit.summarized == 150 and fit.dropped >= 150
        assert fit.messages[-20:] == messages[-20:]

    async def test_the_request_log_hears_which_summary_stood_in_and_what_was_left_out(self, db_session):
        messages = _chat(200)
        summary = SimpleNamespace(
            covered=150, text="Summary: squats on Monday.", up_to=150, version="2026-09-30T08:00:00"
        )
        details = (await _fit(db_session, messages, summary=summary)).log_details()
        assert details["summarized"] == 150 and details["dropped"] >= 150 and details["window"] == WINDOW
        assert details["summary"]["up_to"] == 150 and details["summary"]["version"] == "2026-09-30T08:00:00"
        assert details["summary"]["tokens"] > 0
        # Nothing left out: nothing to log.
        assert (await _fit(db_session, _chat(2))).log_details() is None

    async def test_the_answer_s_room_is_kept(self, db_session):
        messages = _chat(40)
        roomy = await _fit(db_session, messages)
        tight = await _fit(db_session, messages, reply_tokens=3_500)
        assert tight.budget == WINDOW - 3_500 < roomy.budget
        assert tight.dropped > roomy.dropped

    async def test_the_administrator_s_switch_and_share(self, db_session):
        db_session.add(SystemSetting(key="memory_context_fit_enabled", value="false"))
        await db_session.commit()
        messages = _chat(200)
        assert (await _fit(db_session, messages)).messages is messages

    async def test_a_model_of_unknown_window_is_sent_as_it_is_unless_a_default_is_set(self, db_session):
        unknown = SimpleNamespace(**{**vars(_model(None)), "external_id": "house-model"})
        messages = _chat(200)
        fit = await fit_turn_to_context(
            db_session, messages, ai_model=unknown, provider_type="openai", model="house-model"
        )
        assert fit.messages is messages and fit.window is None
        db_session.add(SystemSetting(key="memory_context_default_tokens", value="4000"))
        await db_session.commit()
        fit = await fit_turn_to_context(
            db_session, messages, ai_model=unknown, provider_type="openai", model="house-model"
        )
        assert fit.window == 4_000 and fit.dropped > 0

    async def test_a_failure_to_fit_never_stops_the_turn(self, db_session, monkeypatch):
        async def _broken(_db):
            raise RuntimeError("settings unreadable")

        monkeypatch.setattr("app.services.context_fit_service.get_memory_settings", _broken)
        messages = _chat(200)
        fit = await _fit(db_session, messages)
        assert fit.messages is messages and fit.dropped == 0

    async def test_the_count_is_made_off_the_event_loop(self, db_session, monkeypatch):
        import threading

        from app.services import context_fit_service

        counted_on: list[threading.Thread] = []
        real = context_fit_service.count_prompt_tokens

        def _count(**kwargs):
            counted_on.append(threading.current_thread())
            return real(**kwargs)

        monkeypatch.setattr(context_fit_service, "count_prompt_tokens", _count)
        await _fit(db_session, _chat(200))
        assert counted_on and counted_on[0] is not threading.main_thread()

    def test_the_window_comes_from_the_catalog_then_litellm(self, monkeypatch):
        assert model_window(_model(9_000), "gpt-4o-mini", 0) == 9_000
        assert model_window(_model(None), "gpt-4o-mini", 0) == 128_000
        # LiteLLM's max_tokens is often the longest answer, not the window: never taken for it.
        import litellm

        monkeypatch.setattr(litellm, "get_model_info", lambda _model: {"max_tokens": 8_192})
        assert model_window(_model(None), "answer-sized", 0) is None
        assert model_window(_model(None), "house-model", 0) is None
        assert model_window(_model(None), "house-model", 50_000) == 50_000

    def test_a_turn_with_tool_calls_or_tools_is_never_cut(self):
        assert fittable(_chat(2), None)
        assert not fittable(_chat(2), [{"type": "function", "function": {"name": "click"}}])
        assert not fittable([*_chat(2), {"role": "tool", "tool_call_id": "c1", "content": "ok"}], None)
        assert not fittable([{"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]}], None)


@pytest.fixture
def augment(monkeypatch):
    """The memory, profile and project layers left out: the turn's own history is what is measured."""

    async def _same(_db, messages, **_kwargs):
        return messages

    for name in (
        "augment_messages_with_profile",
        "augment_messages_with_memory",
        "augment_messages_with_project_context",
    ):
        monkeypatch.setattr(f"app.services.chat_turn_context.{name}", _same)


async def test_a_long_chat_goes_to_the_provider_fitted_and_the_reply_says_so(db_session, user, augment):
    resolved = SimpleNamespace(
        ai_model=_model(),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openai",
        model_id="gpt-4o-mini",
        budget_reservation_id=None,
        code_interpreter_capacity_permit=None,
        code_interpreter_workspace_files=None,
        agent_turn=None,
    )
    body = {"model": "model::1", "messages": _chat(200)[1:]}
    ctx = await build_turn_context(
        db_session,
        body,
        resolved,
        user_id=user.id,
        username=user.username,
        source="alpha_router_chat",
        skip_budget=True,
        alpha_router_api_key_id=None,
    )
    await ctx.lease.abandon("test over")
    sent = ctx.completion_kwargs["messages"]
    assert len(sent) < len(body["messages"])
    assert sent[-1]["content"] == "What did I say first?"
    assert ctx.context_fit is not None and ctx.context_fit["dropped"] > 0

    # An API client's turn through the gateway is its own: sent as it came.
    ctx = await build_turn_context(
        db_session,
        body,
        resolved,
        user_id=user.id,
        username=user.username,
        source="gateway",
        skip_budget=True,
        alpha_router_api_key_id=None,
    )
    await ctx.lease.abandon("test over")
    assert len(ctx.completion_kwargs["messages"]) == len(body["messages"])
    assert ctx.context_fit is None


@pytest.mark.parametrize(
    ("source", "cancelled", "shown"),
    [("alpha_router_chat", False, True), ("gateway", False, False), ("alpha_router_chat", True, False)],
)
async def test_the_reply_s_trailer_says_what_was_left_out(monkeypatch, db_session, source, cancelled, shown):
    from app.services import turn_settlement
    from app.services.turn_settlement import TurnIdentity, TurnOutcome, settle_turn

    async def _nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(turn_settlement, "_record_memory_usage", _nothing)
    monkeypatch.setattr(turn_settlement, "_persist_stream_usage", _nothing)
    monkeypatch.setattr(turn_settlement, "budget_notice_after_settlement", _nothing)
    identity = TurnIdentity(
        request=None,
        body={},
        user_id=1,
        username="u",
        model="gpt-4o-mini",
        prompt_lang="en",
        source=source,
        alpha_router_api_key_id=None,
        user_api_key_id=None,
        client_app=None,
        project_id_for_billing=None,
        stream_reservation_id=None,
        context_fit={"dropped": 12, "summarized": 10},
    )
    outcome = TurnOutcome(
        success=True,
        error_message=None,
        was_cancelled=cancelled,
        client_disconnected=False,
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        total_cost=0.0,
        usage_events=[],
        elapsed_ms=1.0,
    )
    trailer = await settle_turn(
        identity, outcome, db=db_session, persister=None, capacity_permit=None, capacity_heartbeat_task=None
    )
    assert ("context_fit" in trailer) is shown
    if shown:
        assert trailer["context_fit"] == {"dropped": 12, "summarized": 10}


async def _openrouter_turn(db, user, messages):
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(
            **{**vars(_model()), "provider_type": "openrouter", "external_id": "openai/gpt-4o-mini"}
        ),
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        provider_type="openrouter",
        model_id="openrouter/openai/gpt-4o-mini",
        budget_reservation_id=None,
        code_interpreter_capacity_permit=None,
        code_interpreter_workspace_files=None,
        agent_turn=None,
    )
    ctx = await build_turn_context(
        db,
        {"model": "model::1", "messages": messages},
        resolved,
        user_id=user.id,
        username=user.username,
        source="alpha_router_chat",
        skip_budget=True,
        alpha_router_api_key_id=None,
    )
    await ctx.lease.abandon("test over")
    return ctx


async def test_openrouter_does_not_cut_the_middle_out_of_a_measured_turn(db_session, user, augment):
    ctx = await _openrouter_turn(db_session, user, _chat(200)[1:])
    assert ctx.completion_kwargs["extra_body"]["transforms"] == []
    db_session.add(SystemSetting(key="memory_context_fit_enabled", value="false"))
    await db_session.commit()
    ctx = await _openrouter_turn(db_session, user, _chat(200)[1:])
    assert "transforms" not in (ctx.completion_kwargs.get("extra_body") or {})


async def test_the_message_says_what_was_left_out_and_keeps_it_when_the_chat_is_replaced(db_session, user):
    import uuid

    from app.models.chat import ChatMessage, ChatSession
    from app.services.user_chat_storage_service import list_session_messages, replace_session_messages

    session_id = str(uuid.uuid4())
    db_session.add(ChatSession(id=session_id, user_id=user.id, title="t", model_id="m", private_mode=False))
    await db_session.flush()
    fit = {"dropped": 30, "summarized": 20}
    for sequence, (role, meta) in enumerate([("user", {}), ("assistant", {"contextFit": fit})], start=1):
        db_session.add(
            ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                user_id=user.id,
                role=role,
                content=f"{role} words",
                sequence=sequence,
                client_message_id=f"c{sequence}",
                meta=meta,
            )
        )
    await db_session.commit()
    listed, _more = await list_session_messages(db_session, user.id, session_id)
    assert listed[1]["contextFit"] == fit
    await replace_session_messages(
        db_session,
        user.id,
        session_id,
        [
            {"role": "user", "content": "user words", "clientMessageId": "c1"},
            {"role": "assistant", "content": "assistant words", "clientMessageId": "c2", "contextFit": {"dropped": 0}},
        ],
    )
    await db_session.commit()
    listed, _more = await list_session_messages(db_session, user.id, session_id)
    assert listed[1]["contextFit"] == fit


async def test_the_turn_s_request_log_keeps_what_it_was_given(monkeypatch, db_session, session_factory, user):
    from sqlalchemy import select

    from app.models.logging import RequestLog
    from app.services import turn_settlement
    from app.services.turn_settlement import TurnIdentity, TurnOutcome, settle_turn

    async def _nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(turn_settlement, "_record_memory_usage", _nothing)
    monkeypatch.setattr(turn_settlement, "budget_notice_after_settlement", _nothing)
    monkeypatch.setattr(turn_settlement, "AsyncSessionLocal", session_factory)
    context = {"memories": 2, "context_fit": {"dropped": 12, "summarized": 10, "summary": {"up_to": 10}}}
    identity = TurnIdentity(
        request=SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.1")),
        body={},
        user_id=user.id,
        username=user.username,
        model="gpt-4o-mini",
        prompt_lang="en",
        source="alpha_router_chat",
        alpha_router_api_key_id=None,
        user_api_key_id=None,
        client_app=None,
        project_id_for_billing=None,
        stream_reservation_id=None,
        context_fit={"dropped": 12, "summarized": 10},
        memory_context=context,
    )
    outcome = TurnOutcome(
        success=True,
        error_message=None,
        was_cancelled=False,
        client_disconnected=False,
        prompt_tokens=1,
        completion_tokens=1,
        cached_tokens=0,
        total_cost=0.0,
        usage_events=[],
        elapsed_ms=1.0,
    )
    await settle_turn(
        identity, outcome, db=db_session, persister=None, capacity_permit=None, capacity_heartbeat_task=None
    )
    row = (await db_session.execute(select(RequestLog).where(RequestLog.user_id == user.id))).scalar_one()
    assert row.memory_context == context
