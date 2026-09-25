"""A reply cut short is billed for what it streamed.

When the client goes away, uvicorn cancels the response task: the stream gets
CancelledError at an await, or GeneratorExit at a yield when the generator is
closed. Providers report usage in a stream's last chunk, and both handlers used
to book the attempt in flight without estimating its tokens, so it was priced
at nothing: stopping a reply just before that last chunk made it free, and so
did stopping one of the browser agent's steps, whose tool calls are all it
generates.

The provider is faked with LiteLLM stream chunks that carry no usage. The turn,
its settlement and its budget hold are real, on the test database.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from litellm.types.utils import ChatCompletionDeltaToolCall, Delta, Function, ModelResponseStream, StreamingChoices
from sqlalchemy import select

from app.models.budget import BudgetPlan, PlanAssignment
from app.models.budget_reservation import BudgetReservation
from app.models.connection import Connection
from app.models.cost_accounting import UsageEvent
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services import chat_turn_context, proxy_service, turn_settlement
from app.services.budget_reservation_service import reserve
from app.services.chat_markers import BROWSER_TOOLS_BODY_KEY
from app.services.provider_stream import ProviderAttempt
from app.services.secret_crypto import encrypt_secret

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click the element with this ref.",
            "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]},
        },
    }
]


def _chunk(delta: Delta) -> ModelResponseStream:
    return ModelResponseStream(id="chatcmpl-cut", model="gpt-a", choices=[StreamingChoices(index=0, delta=delta)])


def _text(content: str) -> ModelResponseStream:
    return _chunk(Delta(content=content))


def _call(*, call_id: str | None = None, name: str | None = None, arguments: str = "") -> ModelResponseStream:
    return _chunk(
        Delta(
            content=None,
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    id=call_id,
                    type="function" if call_id else None,
                    index=0,
                    function=Function(name=name, arguments=arguments),
                )
            ],
        )
    )


#: Each reply streams more than a client reads before it goes away, and never its usage.
REPLIES = {
    "words": [_text("Once upon a time, "), _text("a budget was spent "), *[_text("and spent ") for _ in range(20)]],
    "tool calls": [
        _call(call_id="call_1", name="click"),
        _call(arguments='{"ref":'),
        *[_call(arguments=" ") for _ in range(20)],
    ],
}


class _Stream:
    """A provider stream: two chunks, then ``then`` if given, else the rest of the reply."""

    def __init__(self, chunks: list, *, then: BaseException | None = None) -> None:
        self._chunks = list(chunks[:2]) if then is not None else list(chunks)
        self._then = then

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._chunks:
            return self._chunks.pop(0)
        if self._then is not None:
            raise self._then
        raise StopAsyncIteration

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _stack(monkeypatch, session_factory):
    # The turn opens sessions of its own for the stream and its settlement.
    for module in (proxy_service, chat_turn_context, turn_settlement):
        monkeypatch.setattr(module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.budget_notice_service.AsyncSessionLocal", session_factory)

    async def passthrough(_db, messages, *_args, **_kwargs):
        return messages

    for name in (
        "augment_messages_with_tools",
        "augment_messages_with_profile",
        "augment_messages_with_memory",
        "augment_messages_with_project_context",
    ):
        monkeypatch.setattr(chat_turn_context, name, passthrough)


@pytest.fixture
async def turn(db_session, user) -> SimpleNamespace:
    """A priced model, and the user's hold for one turn out of a $10.00 budget."""
    connection = Connection(
        name="c-cut", provider_type="openai", api_key_encrypted=encrypt_secret("sk-x"), is_active=True
    )
    plan = BudgetPlan(name="cut-plan", monthly_budget_usd=10)
    db_session.add_all([connection, plan])
    await db_session.flush()
    db_session.add(PlanAssignment(user_id=user.id, plan_id=plan.id))
    model = AIModel(
        connection_id=connection.id,
        external_id="gpt-a",
        display_name="Model A",
        provider_type="openai",
        is_enabled=True,
        input_cost_per_1k=0.01,
        output_cost_per_1k=0.03,
    )
    db_session.add(model)
    await db_session.flush()
    hold = await reserve(
        db_session,
        user_id=user.id,
        alpha_router_api_key_id=None,
        amount_usd=0.5,
        operation="chat",
        model_id="gpt-a",
        idempotency_key="cut-short",
        cost_is_estimated=True,
    )
    await db_session.commit()
    return SimpleNamespace(model=model, hold_id=hold.id, user=user)


def _stream(turn: SimpleNamespace, reply: str):
    request = MagicMock()
    request.client = SimpleNamespace(host="203.0.113.7")
    request.headers = {}
    request.is_disconnected = AsyncMock(return_value=False)
    body: dict = {"model": f"model::{turn.model.id}", "messages": [{"role": "user", "content": "Tell me a story."}]}
    if reply == "tool calls":
        body[BROWSER_TOOLS_BODY_KEY] = TOOLS
    resolved = SimpleNamespace(
        ai_model=turn.model,
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openai",
        model_id="gpt-a",
        budget_reservation_id=turn.hold_id,
        code_interpreter_capacity_permit=None,
        code_interpreter_workspace_files=None,
        agent_turn=None,
    )
    return proxy_service.stream_chat(
        request,
        body,
        user_id=turn.user.id,
        username=turn.user.username,
        source="alpha_router_chat",
        skip_budget=False,
        resolved=resolved,
    )


async def _cancel_mid_stream(monkeypatch, turn: SimpleNamespace, reply: str) -> list[bytes]:
    """The cancellation reaches the stream while it waits for the provider's next chunk."""
    provider = _Stream(REPLIES[reply], then=asyncio.CancelledError())
    monkeypatch.setattr(proxy_service, "acompletion", AsyncMock(return_value=provider))
    frames: list[bytes] = []
    with pytest.raises(asyncio.CancelledError):
        async for frame in _stream(turn, reply):
            frames.append(frame)
    return frames


async def _close_mid_stream(monkeypatch, turn: SimpleNamespace, reply: str) -> list[bytes]:
    """The server closes the generator while it waits at a yield (GeneratorExit)."""
    monkeypatch.setattr(proxy_service, "acompletion", AsyncMock(return_value=_Stream(REPLIES[reply])))
    frames: list[bytes] = []
    stream = _stream(turn, reply)
    async for frame in stream:
        frames.append(frame)
        if len(frames) == 2:
            break
    await stream.aclose()
    return frames


async def _settlement(session_factory, turn: SimpleNamespace) -> SimpleNamespace:
    async with session_factory() as fresh:
        return SimpleNamespace(
            logs=list((await fresh.execute(select(RequestLog))).scalars().all()),
            events=list((await fresh.execute(select(UsageEvent))).scalars().all()),
            hold=await fresh.get(BudgetReservation, turn.hold_id),
            user=await fresh.get(User, turn.user.id),
        )


@pytest.mark.parametrize("reply", ["words", "tool calls"])
@pytest.mark.parametrize(
    ("cut_short", "error_code"),
    [(_cancel_mid_stream, "cancelled"), (_close_mid_stream, "client_disconnected")],
    ids=["cancelled", "closed"],
)
async def test_a_reply_cut_short_is_billed_for_what_it_streamed(
    monkeypatch, session_factory, turn, reply, cut_short, error_code
):
    frames = await cut_short(monkeypatch, turn, reply)
    assert len(frames) == 2, "the client received part of the reply"
    assert all(b"[DONE]" not in frame for frame in frames)

    done = await _settlement(session_factory, turn)
    [log] = done.logs
    assert log.success is False
    assert log.error_code == error_code
    assert log.prompt_tokens > 0
    assert log.completion_tokens > 0
    assert float(log.total_cost_usd) > 0
    [event] = done.events
    assert event.status == "cancelled"
    assert event.completion_tokens > 0
    assert float(event.final_cost_usd) > 0
    # The hold is settled at the cost, and the user's budget carries it.
    assert done.hold.status == "settled"
    assert float(done.hold.actual_usd) == pytest.approx(float(log.total_cost_usd))
    assert float(done.user.budget_used_usd) == pytest.approx(float(log.total_cost_usd))
    assert float(done.user.budget_reserved_usd) == pytest.approx(0.0)


async def test_a_failed_estimate_still_settles_the_turn(monkeypatch, session_factory, turn):
    """No estimate is better than no settlement: the hold is still settled and the turn still logged."""

    def broken(_self) -> None:
        raise RuntimeError("tokenizer unavailable")

    monkeypatch.setattr(ProviderAttempt, "finish", broken)
    await _close_mid_stream(monkeypatch, turn, "words")

    done = await _settlement(session_factory, turn)
    [log] = done.logs
    assert log.error_code == "client_disconnected"
    [event] = done.events
    assert event.status == "cancelled"
    assert done.hold.status == "settled"
    assert float(done.user.budget_reserved_usd) == pytest.approx(0.0)
