"""The browser extension's agent in a chat turn: its tools go to the model, its tool calls come back.

Each step of the agent is one ``/api/chat/completions`` call from a connected
browser carrying ``browser_tools``. The provider is faked at ``acompletion``;
the endpoint, the preflight (model, access, budget hold), the turn and its
settlement are real, on the test database.
"""

from __future__ import annotations

import asyncio
import datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from litellm.types.utils import ChatCompletionDeltaToolCall, Delta, Function, ModelResponseStream, StreamingChoices
from sqlalchemy import select, update

from app.config import get_settings
from app.core.security import create_access_token
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.budget_reservation import BudgetReservation
from app.models.connection import Connection
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services import (
    budget_reservation_service,
    chat_turn_context,
    extension_tokens,
    provider_stream,
    proxy_service,
    turn_settlement,
)
from app.services.budget_reservation_service import reservation_hold_usd
from app.services.chat_markers import BROWSER_TOOL_CHOICE_BODY_KEY, BROWSER_TOOLS_BODY_KEY
from app.services.chat_tool_access_service import set_chat_tool_access
from app.services.chat_turn_context import build_turn_context
from app.services.extension_settings import ExtensionSettings, save_extension_settings
from app.services.extension_tokens import create_session
from app.services.provider_stream import KEEP_ALIVE, ProviderAttempt, chunks_kept_alive
from app.services.secret_crypto import encrypt_secret

SERVER = "https://ai.example.com"
CSRF = "csrf-token"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click the element with this ref.",
            "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Finish the task with a summary for the user.",
            "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
        },
    },
]
TASK = [
    {"role": "system", "content": "You act in the user's browser with the tools you are given."},
    {"role": "user", "content": "Open the pricing page."},
]
#: What an agent sends after the model asked for a click and the page answered.
FOLLOW_UP = [
    *TASK,
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "click", "arguments": '{"ref":"e12"}'}}
        ],
    },
    {"role": "tool", "tool_call_id": "call_1", "content": "Clicked. The page is now https://example.com/pricing."},
]


def _cached(messages: list) -> list:
    """``messages`` as the provider gets them: the agent's instructions end the part its cache keeps."""
    return [{**m, "cache_control": {"type": "ephemeral"}} if i == 0 else m for i, m in enumerate(messages)]


# --- the provider -------------------------------------------------------------


def _chunk(delta: Delta, finish: str | None = None) -> ModelResponseStream:
    return ModelResponseStream(
        id="chatcmpl-agent",
        model="gpt-a",
        choices=[StreamingChoices(index=0, delta=delta, finish_reason=finish)],
    )


def _text(content: str, finish: str | None = None) -> ModelResponseStream:
    return _chunk(Delta(content=content), finish)


def _call(
    index: int,
    *,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str = "",
    finish: str | None = None,
) -> ModelResponseStream:
    """One piece of a streamed tool call: the first names it, the rest carry its arguments."""
    return _chunk(
        Delta(
            content=None,
            tool_calls=[
                ChatCompletionDeltaToolCall(
                    id=call_id,
                    type="function" if call_id else None,
                    index=index,
                    function=Function(name=name, arguments=arguments),
                )
            ],
        ),
        finish,
    )


def _finish(reason: str) -> ModelResponseStream:
    return _chunk(Delta(content=None), reason)


CLICK_REPLY = [
    _call(0, call_id="call_1", name="click"),
    _call(0, arguments='{"ref":'),
    _call(0, arguments='"e12"}'),
    _finish("tool_calls"),
]


class _Stream:
    def __init__(self, chunks: list, *, fail: Exception | None = None) -> None:
        self._chunks = list(chunks)
        self._fail = fail

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._fail is not None:
            raise self._fail
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self) -> None:
        return None


class Provider:
    """Answers each call with the next scripted reply, and keeps what each call asked for."""

    def __init__(self) -> None:
        self.replies: list = []
        self.calls: list[dict] = []

    def reply(self, *chunks, fail: Exception | None = None) -> Provider:
        self.replies.append(_Stream(list(chunks), fail=fail))
        return self

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        # A whole reply (a call without streaming) may fail as the provider refuses it.
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def provider(monkeypatch) -> Provider:
    fake = Provider()
    monkeypatch.setattr(proxy_service, "acompletion", fake)
    return fake


# --- the stack ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    monkeypatch.setattr(extension_tokens, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.budget_notice_service.AsyncSessionLocal", session_factory)
    # The turn opens sessions of its own for the stream, for growing its budget hold and for its settlement.
    for module in (proxy_service, chat_turn_context, turn_settlement, budget_reservation_service):
        monkeypatch.setattr(module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(get_settings(), "frontend_url", f"{SERVER}/")


async def _model(db, external_id: str) -> AIModel:
    connection = Connection(
        name=f"c-{external_id}", provider_type="openai", api_key_encrypted=encrypt_secret("sk-x"), is_active=True
    )
    db.add(connection)
    await db.flush()
    row = AIModel(
        connection_id=connection.id,
        external_id=external_id,
        display_name=f"Model {external_id}",
        provider_type="openai",
        is_enabled=True,
        input_cost_per_1k=0.01,
        output_cost_per_1k=0.03,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
async def models(db_session) -> SimpleNamespace:
    return SimpleNamespace(a=await _model(db_session, "gpt-a"), b=await _model(db_session, "gpt-b"))


async def _give_budget(db, user) -> None:
    plan = BudgetPlan(name="agent-plan", monthly_budget_usd=100)
    db.add(plan)
    await db.flush()
    db.add(PlanAssignment(user_id=user.id, plan_id=plan.id))
    await db.commit()


@pytest.fixture
async def agent_on(db_session, user) -> None:
    """The agent is off for everyone until an administrator turns it on; the user has a budget."""
    await set_chat_tool_access(db_session, "browser_agent", access_type="public", grants=[])
    await _give_budget(db_session, user)


@pytest.fixture
async def browser(db_session, user) -> SimpleNamespace:
    pair = await create_session(db_session, user=user, device_name="Chrome", user_agent="UA", ip="10.0.0.5")
    await db_session.commit()
    return SimpleNamespace(session_id=pair.session_id, headers={"Authorization": f"Bearer {pair.access_token}"})


def _body(model: AIModel | str, messages: list | None = None, **extra) -> dict:
    ref = model if isinstance(model, str) else f"model::{model.id}"
    return {"model": ref, "messages": messages or TASK, "browser_tools": TOOLS, **extra}


def _frames(raw: str) -> list:
    out: list = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            data = block[5:].strip()
            out.append(data if data == "[DONE]" else json.loads(data))
    return out


def _tool_calls(frames: list) -> list[dict]:
    """The tool calls the client can put together from the streamed deltas."""
    calls: dict[int, dict] = {}
    for frame in frames:
        if not isinstance(frame, dict) or "choices" not in frame:
            continue
        for delta in frame["choices"][0]["delta"].get("tool_calls") or []:
            call = calls.setdefault(delta["index"], {"id": None, "name": "", "arguments": ""})
            call["id"] = call["id"] or delta.get("id")
            call["name"] += delta["function"].get("name") or ""
            call["arguments"] += delta["function"].get("arguments") or ""
    return [calls[index] for index in sorted(calls)]


async def _logs(session_factory) -> list[RequestLog]:
    async with session_factory() as fresh:
        return list((await fresh.execute(select(RequestLog).order_by(RequestLog.id))).scalars().all())


async def _reservations(session_factory) -> list[BudgetReservation]:
    async with session_factory() as fresh:
        return list((await fresh.execute(select(BudgetReservation))).scalars().all())


def _sign_in(client, user) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


# --- a step ---------------------------------------------------------------------


#: What httpx says when a provider refused a stream and its error body was never read.
UNREAD_STREAM = Exception("Attempted to access streaming response content, without having called read()")


def _whole_click() -> object:
    from litellm.types.utils import ChatCompletionMessageToolCall, Choices, Message, ModelResponse, Usage

    call = ChatCompletionMessageToolCall(
        id="call_9", type="function", function=Function(name="click", arguments='{"ref":"e3"}')
    )
    return ModelResponse(
        choices=[Choices(index=0, finish_reason="tool_calls", message=Message(content=None, tool_calls=[call]))],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


@pytest.mark.usefixtures("agent_on")
class TestCaching:
    async def test_the_tools_and_instructions_are_marked_for_the_provider_s_cache(
        self, client, browser, models, provider
    ):
        provider.reply(*CLICK_REPLY)
        await client.post("/api/chat/completions", json=_body(models.a, messages=FOLLOW_UP), headers=browser.headers)
        [call] = provider.calls
        # The system message ends the cached prefix; the tools come before it.
        assert call["messages"][0]["role"] == "system"
        assert call["messages"][0]["cache_control"] == {"type": "ephemeral"}
        assert not any("cache_control" in m for m in call["messages"][1:])

    async def test_a_step_is_never_kept_in_the_response_cache(self, client, browser, models, provider):
        provider.reply(*CLICK_REPLY)
        await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        [call] = provider.calls
        assert call["caching"] is False


class _SlowStream(_Stream):
    """A model that thinks a while before its first chunk."""

    def __init__(self, chunks: list, *, think: float) -> None:
        super().__init__(chunks)
        self._think = think

    async def __anext__(self):
        if self._think:
            await asyncio.sleep(self._think)
            self._think = 0
        return await super().__anext__()


class _Attempt:
    """What ``chunks_kept_alive`` needs of a provider attempt, and whether its wait was called off."""

    def __init__(self, stream: _Stream) -> None:
        self.stream = stream
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def chunks(self):
        async for chunk in self.stream:
            yield chunk


@pytest.mark.usefixtures("agent_on")
class TestASlowStep:
    async def test_the_connection_is_kept_alive_until_the_model_s_first_chunk(
        self, client, browser, models, provider, monkeypatch
    ):
        monkeypatch.setattr(provider_stream, "KEEP_ALIVE_SECONDS", 0.02)
        provider.replies.append(_SlowStream(list(CLICK_REPLY), think=0.2))
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 200, resp.text
        before, _, _ = resp.text.partition("data:")
        # SSE comments, which clients skip, and only before the model began.
        assert before.count(": keep-alive\n\n") >= 2
        assert ": keep-alive" not in resp.text[len(before) :]
        assert _tool_calls(_frames(resp.text)) == [{"id": "call_1", "name": "click", "arguments": '{"ref":"e12"}'}]
        assert _frames(resp.text)[-1] == "[DONE]"

    async def test_a_quick_step_has_none(self, client, browser, models, provider, monkeypatch):
        monkeypatch.setattr(provider_stream, "KEEP_ALIVE_SECONDS", 0.5)
        provider.reply(*CLICK_REPLY)
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert ": keep-alive" not in resp.text

    async def test_a_turn_without_tools_is_not_kept_alive(self, monkeypatch):
        monkeypatch.setattr(provider_stream, "KEEP_ALIVE_SECONDS", 0.01)
        attempt = _Attempt(_SlowStream([_text("Hi"), _finish("stop")], think=0.1))
        got = [chunk async for chunk in chunks_kept_alive(attempt, keep_alive=False)]  # type: ignore[arg-type]
        assert KEEP_ALIVE not in got
        assert len(got) == 2

    async def test_a_model_that_says_nothing_ends_the_stream(self, monkeypatch):
        monkeypatch.setattr(provider_stream, "KEEP_ALIVE_SECONDS", 0.01)
        attempt = _Attempt(_SlowStream([], think=0.05))
        got = [chunk async for chunk in chunks_kept_alive(attempt, keep_alive=True)]  # type: ignore[arg-type]
        assert got and set(map(id, got)) == {id(KEEP_ALIVE)}

    async def test_the_wait_is_called_off_when_nobody_listens(self, monkeypatch):
        monkeypatch.setattr(provider_stream, "KEEP_ALIVE_SECONDS", 0.01)
        called_off = asyncio.Event()

        class _Forever(_Stream):
            async def __anext__(self):
                try:
                    await asyncio.sleep(60)
                except asyncio.CancelledError:
                    called_off.set()
                    raise
                return None

        chunks = chunks_kept_alive(_Attempt(_Forever([])), keep_alive=True)  # type: ignore[arg-type]
        assert await chunks.__anext__() is KEEP_ALIVE
        await chunks.aclose()
        await asyncio.wait_for(called_off.wait(), timeout=1)

    async def test_a_provider_that_fails_before_its_first_chunk_fails_the_step(self, monkeypatch):
        monkeypatch.setattr(provider_stream, "KEEP_ALIVE_SECONDS", 0.01)

        class _Refuses(_Attempt):
            async def start(self) -> None:
                await asyncio.sleep(0.05)
                raise RuntimeError("No endpoints found that support tool use.")

        chunks = chunks_kept_alive(_Refuses(_Stream([])), keep_alive=True)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="No endpoints"):
            async for chunk in chunks:
                assert chunk is KEEP_ALIVE


@pytest.mark.usefixtures("agent_on")
class TestAStreamTheProviderRefused:
    async def test_is_asked_again_whole_and_its_tool_calls_go_out_in_one_frame(self, client, browser, models, provider):
        provider.reply(fail=UNREAD_STREAM)
        provider.replies.append(_whole_click())
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 200, resp.text
        frames = _frames(resp.text)
        whole = [f for f in frames if isinstance(f, dict) and "choices" in f and "message" in f["choices"][0]]
        assert whole == [
            {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_9",
                                    "type": "function",
                                    "function": {"name": "click", "arguments": '{"ref":"e3"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        ]
        assert not [f for f in frames if isinstance(f, dict) and "error" in f]
        assert frames[-1] == "[DONE]"
        # The same step, the same tools, without streaming.
        assert [call.get("stream") for call in provider.calls] == [True, False]
        assert provider.calls[1]["tools"] == TOOLS

    async def test_says_the_provider_s_own_reason_when_it_refuses_again(self, client, browser, models, provider):
        provider.reply(fail=UNREAD_STREAM)
        provider.replies.append(Exception("No endpoints found that support tool use."))
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        errors = [f["error"]["message"] for f in _frames(resp.text) if isinstance(f, dict) and "error" in f]
        assert errors == ["No endpoints found that support tool use."]

    async def test_is_not_asked_again_once_part_of_it_reached_the_browser(self, client, browser, models, provider):
        # A stream that fails after its first chunk went out: asking again could send a second, different reply.
        class _Breaks(_Stream):
            async def __anext__(self):
                if self._chunks:
                    return self._chunks.pop(0)
                raise UNREAD_STREAM

        provider.replies.append(_Breaks([_call(0, call_id="call_1", name="click")]))
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert [call.get("stream") for call in provider.calls] == [True]
        assert [f for f in _frames(resp.text) if isinstance(f, dict) and "error" in f]


@pytest.mark.usefixtures("agent_on")
class TestAStep:
    async def test_the_model_s_tool_calls_stream_to_the_browser(
        self, client, browser, models, provider, session_factory
    ):
        provider.reply(*CLICK_REPLY)
        resp = await client.post(
            "/api/chat/completions", json=_body(models.a, browser_tool_choice="auto"), headers=browser.headers
        )
        assert resp.status_code == 200, resp.text
        frames = _frames(resp.text)
        assert _tool_calls(frames) == [{"id": "call_1", "name": "click", "arguments": '{"ref":"e12"}'}]
        assert [f["choices"][0]["finish_reason"] for f in frames if isinstance(f, dict) and "choices" in f][
            -1
        ] == "tool_calls"
        assert not [f for f in frames if isinstance(f, dict) and "error" in f]
        assert frames[-1] == "[DONE]"
        # The provider was offered the tools, as the extension described them.
        [call] = provider.calls
        assert call["tools"] == TOOLS
        assert call["tool_choice"] == "auto"
        assert call["messages"] == _cached(TASK)

    async def test_a_reply_of_tool_calls_alone_is_a_success(self, client, browser, models, provider, session_factory):
        provider.reply(*CLICK_REPLY)
        await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        [log] = await _logs(session_factory)
        assert log.success is True
        assert log.error_code is None
        assert log.client_app == "Alpharouter Extension"
        [hold] = await _reservations(session_factory)
        assert hold.status == "settled"

    async def test_the_calls_are_billed_when_the_provider_reports_no_usage(
        self, client, browser, models, provider, session_factory
    ):
        provider.reply(*CLICK_REPLY)
        await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        [log] = await _logs(session_factory)
        # No words at all, yet the tool call is output the provider charges for.
        assert log.completion_tokens > 0
        assert log.prompt_tokens > 0
        assert float(log.total_cost_usd) > 0

    async def test_the_tools_are_counted_as_prompt(self, client, browser, models, provider, session_factory):
        provider.reply(_text("Hello", "stop")).reply(_text("Hello", "stop"))
        with_tools = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        plain = {"model": f"model::{models.a.id}", "messages": TASK}
        without = await client.post("/api/chat/completions", json=plain, headers=browser.headers)
        assert with_tools.status_code == without.status_code == 200
        first, second = await _logs(session_factory)
        assert first.prompt_tokens > second.prompt_tokens

    async def test_a_follow_up_step_carries_the_tool_results(self, client, browser, models, provider, session_factory):
        provider.reply(_text("The pricing page is open."), _finish("stop"))
        resp = await client.post("/api/chat/completions", json=_body(models.a, FOLLOW_UP), headers=browser.headers)
        assert resp.status_code == 200, resp.text
        # Nothing was added to or taken from the conversation: no memory, no profile.
        assert provider.calls[0]["messages"] == _cached(FOLLOW_UP)
        [log] = await _logs(session_factory)
        assert log.success is True

    async def test_no_memory_or_profile_is_looked_up(self, client, browser, models, provider):
        provider.reply(*CLICK_REPLY)
        profile = AsyncMock(side_effect=lambda db, messages, **_: messages)
        memory = AsyncMock(side_effect=lambda db, messages, **_: messages)
        project = AsyncMock(side_effect=lambda db, messages, **_: messages)
        with (
            patch.object(chat_turn_context, "augment_messages_with_profile", profile),
            patch.object(chat_turn_context, "augment_messages_with_memory", memory),
            patch.object(chat_turn_context, "augment_messages_with_project_context", project),
        ):
            resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 200, resp.text
        profile.assert_not_awaited()
        memory.assert_not_awaited()
        project.assert_not_awaited()

    async def test_the_turn_goes_to_the_model_that_was_checked(self, client, browser, models, provider, db_session):
        await save_extension_settings(db_session, ExtensionSettings(agent_models=(f"model::{models.a.id}",)))
        await db_session.commit()
        provider.reply(*CLICK_REPLY)
        # Named by its external id: checked as the turn resolves it, then pinned.
        resp = await client.post("/api/chat/completions", json=_body("gpt-a"), headers=browser.headers)
        assert resp.status_code == 200, resp.text
        assert provider.calls[0]["model"].endswith("gpt-a")

    async def test_a_broken_stream_that_breaks_again_without_streaming_fails(
        self, client, browser, models, provider, session_factory
    ):
        # Asked once more, whole (tool calls and all), the provider still cannot answer: the step failed.
        provider.reply(fail=UNREAD_STREAM)
        provider.replies.append(RuntimeError("upstream unavailable"))
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        frames = _frames(resp.text)
        assert [call.get("stream") for call in provider.calls] == [True, False]
        assert [f for f in frames if isinstance(f, dict) and "error" in f]
        [log] = await _logs(session_factory)
        assert log.success is False

    async def test_long_tool_calls_count_against_the_budget(
        self, client, browser, models, provider, session_factory, db_session, user
    ):
        # $0.20 left pays for about 6,600 output tokens; these arguments run to several times that.
        await db_session.execute(update(BudgetPlan).values(monthly_budget_usd=0.2))
        await db_session.commit()
        words = [f"w{n}" for n in range(12_000)]
        pieces = [" ".join(words[i : i + 200]) for i in range(0, len(words), 200)]
        provider.reply(
            _call(0, call_id="call_1", name="done", arguments='{"summary":"'),
            *[_call(0, arguments=piece + " ") for piece in pieces],
            _call(0, arguments='"}'),
            _finish("tool_calls"),
        )
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        errors = [f for f in _frames(resp.text) if isinstance(f, dict) and "error" in f]
        assert errors and "budget" in errors[0]["error"]["message"]
        [log] = await _logs(session_factory)
        assert log.error_code == "budget_exceeded"
        # The hold grew with the calls and is settled at what they cost; nothing stays held.
        [hold] = await _reservations(session_factory)
        assert hold.status == "settled"
        assert float(hold.actual_usd) == pytest.approx(float(log.total_cost_usd))
        async with session_factory() as fresh:
            assert float((await fresh.get(User, user.id)).budget_reserved_usd) == pytest.approx(0.0)


# --- refused --------------------------------------------------------------------


SHOT = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
VISION_RAW = json.dumps({"architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}})


def _with_shot(*urls: str) -> list:
    """A step that carries screenshots after the tool answers, as the panel sends them."""
    parts = [
        {"type": "text", "text": "Here is the page now."},
        *({"type": "image_url", "image_url": {"url": u}} for u in urls),
    ]
    return [*TASK, {"role": "user", "content": parts}]


class TestScreenshots:
    """Screenshots reach the model only under full control, only to a vision model, and bounded."""

    @pytest.fixture
    async def control_on(self, db_session, user, agent_on) -> None:
        from app.services.resource_access_service import AccessGrant

        await set_chat_tool_access(
            db_session,
            "browser_control",
            access_type="private",
            grants=[AccessGrant(target_type="user", target=user.id)],
        )
        await save_extension_settings(db_session, ExtensionSettings(full_control=True))
        await db_session.commit()

    @pytest.fixture
    async def vision(self, db_session) -> AIModel:
        row = await _model(db_session, "gpt-vision")
        row.pricing_raw = VISION_RAW
        await db_session.commit()
        return row

    @pytest.mark.usefixtures("agent_on")
    async def test_without_full_control(self, client, browser, models, provider):
        resp = await client.post(
            "/api/chat/completions", json=_body(models.a, _with_shot(SHOT)), headers=browser.headers
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "control_not_permitted"
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    async def test_the_switch_without_the_grant(self, client, browser, models, provider, db_session):
        await save_extension_settings(db_session, ExtensionSettings(full_control=True))
        await db_session.commit()
        resp = await client.post(
            "/api/chat/completions", json=_body(models.a, _with_shot(SHOT)), headers=browser.headers
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "control_not_permitted"

    @pytest.mark.usefixtures("control_on")
    async def test_a_model_that_cannot_read_images(self, client, browser, models, provider):
        resp = await client.post(
            "/api/chat/completions", json=_body(models.a, _with_shot(SHOT)), headers=browser.headers
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "model_not_vision"
        assert provider.calls == []

    @pytest.mark.usefixtures("control_on")
    async def test_a_vision_model_gets_the_screenshot(self, client, browser, vision, provider):
        resp = await client.post("/api/chat/completions", json=_body(vision, _with_shot(SHOT)), headers=browser.headers)
        assert resp.status_code == 200, resp.text
        assert len(provider.calls) == 1
        sent = provider.calls[0]["messages"][-1]["content"]
        assert any(part.get("type") == "image_url" for part in sent)

    @pytest.mark.usefixtures("control_on")
    @pytest.mark.parametrize(
        ("urls", "code"),
        [
            pytest.param([SHOT] * 5, "too_many_images", id="too many"),
            pytest.param(["https://evil.example/shot.jpg"], "image_not_inline", id="remote"),
            pytest.param(["data:image/gif;base64,R0lGOD"], "image_not_inline", id="not jpeg/png/webp"),
            pytest.param(["data:image/jpeg;base64," + "A" * 1_600_000], "image_too_large", id="huge"),
        ],
    )
    async def test_bounds(self, client, browser, vision, provider, urls, code):
        resp = await client.post(
            "/api/chat/completions", json=_body(vision, _with_shot(*urls)), headers=browser.headers
        )
        assert resp.status_code in (400, 413), resp.text
        assert resp.json()["detail"]["code"] == code
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    async def test_a_step_without_images_is_untouched(self, client, browser, models, provider):
        # No screenshot, no full-control requirement: the ref-based agent works as before.
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 200, resp.text


class TestRefused:
    """Every refusal comes before anything is spent: the provider is never called."""

    async def test_without_the_agent_permission(self, client, browser, models, provider, db_session, user):
        await _give_budget(db_session, user)
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "agent_not_permitted"
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    async def test_from_the_web_app(self, client, user, models, provider):
        headers = _sign_in(client, user)
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=headers)
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "extension_only"
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    @pytest.mark.parametrize(
        ("extra", "message"),
        [
            ({"tools": {"code_interpreter": True}}, "chat tools"),
            ({"tools": {"web_fetch": True}}, "chat tools"),
            ({"web_search": True}, "chat tools"),
            ({"agent_id": "agent-1"}, "Agent Studio"),
            ({"alpharouter": {"agent": "auto"}}, "Agent Studio"),
            ({"extension_page_context": {"sites": [{"host": "example.com", "chars": 10}]}}, "its own tools"),
            ({"persist_chat": True}, "not saved"),
            ({"chat_session_id": "c-1"}, "not saved"),
            ({"project_id": "p-1"}, "not saved"),
            ({"assistant_client_message_id": "a-1"}, "not saved"),
        ],
    )
    async def test_with_anything_else_in_the_turn(self, client, browser, models, provider, extra, message):
        resp = await client.post("/api/chat/completions", json=_body(models.a, **extra), headers=browser.headers)
        assert resp.status_code == 400, resp.text
        detail = resp.json()["detail"]
        assert detail["code"] == "browser_tools_conflict"
        assert message in detail["message"]
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    @pytest.mark.parametrize("ref", ["id", "external"])
    async def test_a_model_outside_the_agent_list(self, client, browser, models, provider, db_session, ref):
        await save_extension_settings(db_session, ExtensionSettings(agent_models=(f"model::{models.a.id}",)))
        await db_session.commit()
        model = models.b if ref == "id" else "gpt-b"
        resp = await client.post("/api/chat/completions", json=_body(model), headers=browser.headers)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "agent_model_not_allowed"
        assert "browser agent" in detail["message"]
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    async def test_without_a_list_the_models_that_passed_the_probe(self, client, browser, models, provider, db_session):
        # No list of the administrator's, and a probe that passed one model: the agent uses that one only.
        from app.services.extension_probe import PROBES_KEY
        from app.models.system import SystemSetting

        passed = {f"model::{models.a.id}": {"passed": True, "hits": 3, "trials": 3, "vision": True}}
        db_session.add(SystemSetting(key=PROBES_KEY, value=json.dumps(passed)))
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(models.b), headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "agent_model_not_allowed"
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    async def test_never_auto_router_whatever_the_lists_say(self, client, browser, models, provider, db_session):
        router = await _model(db_session, "openrouter/auto")
        await save_extension_settings(db_session, ExtensionSettings(agent_models=(f"model::{router.id}",)))
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(router), headers=browser.headers)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "agent_model_not_allowed"
        assert "Auto Router" in detail["message"]
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    async def test_with_no_list_and_no_probe_any_model(self, client, browser, models, provider):
        resp = await client.post("/api/chat/completions", json=_body(models.b), headers=browser.headers)
        assert resp.status_code == 200, resp.text

    @pytest.mark.usefixtures("agent_on")
    async def test_a_model_outside_the_page_content_list(self, client, browser, models, provider, db_session):
        # The agent sends what it reads on pages to the model.
        await save_extension_settings(db_session, ExtensionSettings(page_content_models=(f"model::{models.a.id}",)))
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(models.b), headers=browser.headers)
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "model_not_allowed"
        assert "pages" in detail["message"]
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    async def test_no_model_when_the_lists_are_set(self, client, browser, models, provider, db_session):
        await save_extension_settings(db_session, ExtensionSettings(agent_models=(f"model::{models.a.id}",)))
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body("no-such-model"), headers=browser.headers)
        assert resp.status_code == 403
        assert provider.calls == []

    @pytest.mark.usefixtures("agent_on")
    @pytest.mark.parametrize(
        "change",
        [
            pytest.param(lambda body: body.update(browser_tools=[*TOOLS] * 17), id="too many"),
            pytest.param(lambda body: body.update(browser_tools=[TOOLS[0], TOOLS[0]]), id="one name twice"),
            pytest.param(
                lambda body: body.update(
                    browser_tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "big",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        f"p{n}": {"type": "string", "description": "x" * 400} for n in range(90)
                                    },
                                },
                            },
                        }
                    ]
                ),
                id="larger than 32 KB",
            ),
            pytest.param(
                lambda body: body["browser_tools"][0]["function"].update(parameters={"type": "string"}),
                id="parameters not an object",
            ),
            pytest.param(lambda body: body["browser_tools"][0].update(type="code"), id="not a function"),
            pytest.param(lambda body: body["browser_tools"][0]["function"].update(name="a b"), id="bad name"),
            pytest.param(lambda body: body.update(browser_tool_choice="click"), id="unknown choice"),
            pytest.param(
                lambda body: (body.pop("browser_tools"), body.update(browser_tool_choice="auto")), id="choice alone"
            ),
        ],
    )
    async def test_tools_that_do_not_fit(self, client, browser, models, provider, change):
        body = json.loads(json.dumps(_body(models.a)))
        change(body)
        resp = await client.post("/api/chat/completions", json=body, headers=browser.headers)
        assert resp.status_code == 422, resp.text
        assert provider.calls == []


# --- the pieces -------------------------------------------------------------------


class TestTheHold:
    async def test_it_counts_the_tools_and_the_calls(self, db_session, models):
        async def hold(body: dict) -> float:
            return await reservation_hold_usd(
                db_session, service_type="llm", ai_model=models.a, provider_type="openai", body=body
            )

        plain = await hold({"messages": TASK})
        with_tools = await hold({"messages": TASK, BROWSER_TOOLS_BODY_KEY: TOOLS})
        with_calls = await hold({"messages": FOLLOW_UP, BROWSER_TOOLS_BODY_KEY: TOOLS})
        assert plain < with_tools < with_calls


class TestTheTurn:
    @staticmethod
    def _resolved() -> SimpleNamespace:
        return SimpleNamespace(
            ai_model=SimpleNamespace(provider_type="openai", external_id="gpt-a", display_name="A", connection_id=7),
            api_key="sk-test",
            base_url="https://example.com/v1",
            provider_type="openai",
            model_id="gpt-a",
            budget_reservation_id=None,
            code_interpreter_capacity_permit=None,
            code_interpreter_workspace_files=None,
            agent_turn=None,
        )

    async def _turn(self, db, user, body: dict):
        ctx = await build_turn_context(
            db,
            body,
            self._resolved(),
            user_id=user.id,
            username=user.username,
            source="alpha_router_chat",
            skip_budget=True,
            alpha_router_api_key_id=None,
        )
        await ctx.lease.abandon("test over")
        return ctx

    async def test_the_tools_go_to_the_provider(self, db_session, user):
        ctx = await self._turn(
            db_session,
            user,
            {"messages": FOLLOW_UP, BROWSER_TOOLS_BODY_KEY: TOOLS, BROWSER_TOOL_CHOICE_BODY_KEY: "required"},
        )
        assert ctx.completion_kwargs["tools"] == TOOLS
        assert ctx.completion_kwargs["tool_choice"] == "required"
        assert ctx.completion_kwargs["messages"] == _cached(FOLLOW_UP)

    @pytest.mark.parametrize("choice", [None, "any", 3])
    async def test_an_unknown_choice_is_left_to_the_provider(self, db_session, user, choice):
        ctx = await self._turn(
            db_session, user, {"messages": TASK, BROWSER_TOOLS_BODY_KEY: TOOLS, BROWSER_TOOL_CHOICE_BODY_KEY: choice}
        )
        assert "tool_choice" not in ctx.completion_kwargs

    @pytest.mark.parametrize("value", [None, [], "click", [1, 2]])
    async def test_only_a_list_of_tools_counts(self, db_session, user, value):
        ctx = await self._turn(db_session, user, {"messages": TASK, BROWSER_TOOLS_BODY_KEY: value})
        assert "tools" not in ctx.completion_kwargs


class TestTheAttempt:
    @staticmethod
    def _attempt() -> ProviderAttempt:
        return ProviderAttempt(
            ai_model=SimpleNamespace(),
            provider_type="openai",
            model="gpt-a",
            completion_kwargs={"messages": TASK, "tools": TOOLS},
            completion_fn=AsyncMock(),
        )

    async def test_it_puts_the_calls_together(self):
        attempt = self._attempt()
        attempt.response = _Stream(
            [
                _call(0, call_id="call_1", name="click"),
                _call(1, call_id="call_2", name="done"),
                _call(0, arguments='{"ref":"e1"}'),
                _call(1, arguments='{"summary":"ok"}'),
            ]
        )
        async for _ in attempt.chunks():
            pass
        assert attempt.has_tool_calls
        assert attempt.tool_call_text == 'click({"ref":"e1"})\ndone({"summary":"ok"})'
        assert attempt.tool_call_chars == len('click{"ref":"e1"}done{"summary":"ok"}')
        assert attempt.billable_text == attempt.tool_call_text

    async def test_words_and_calls_are_both_billed(self):
        attempt = self._attempt()
        attempt.record_text("Clicking it.")
        attempt.response = _Stream([_call(0, call_id="call_1", name="click", arguments="{}")])
        async for _ in attempt.chunks():
            pass
        assert attempt.billable_text == "Clicking it.\nclick({})"

    async def test_calls_as_plain_dicts_count_too(self):
        attempt = self._attempt()
        chunk = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None, tool_calls=[{"index": 0, "function": {"name": "done", "arguments": "{}"}}]
                    )
                )
            ],
            usage=None,
        )
        attempt.response = _Stream([chunk])
        async for _ in attempt.chunks():
            pass
        assert attempt.tool_call_text == "done({})"

    async def test_a_reply_of_words_has_no_calls(self):
        attempt = self._attempt()
        attempt.response = _Stream([_text("Hello")])
        async for chunk in attempt.chunks():
            attempt.record_text(ProviderAttempt.delta_text(chunk))
        assert not attempt.has_tool_calls
        assert attempt.billable_text == "Hello"


class TestAnAdministratorsStop:
    """A stop ends the runs that were under way, and leaves later ones alone."""

    @staticmethod
    def _at(offset_seconds: int) -> str:
        return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=offset_seconds)).isoformat()

    async def test_a_run_that_began_before_the_stop_is_refused(
        self, client, browser, models, provider, db_session, agent_on
    ):
        await save_extension_settings(db_session, ExtensionSettings(stop_runs_before=self._at(0)))
        await db_session.commit()
        provider.reply(*CLICK_REPLY)
        began = int((datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)).timestamp() * 1000)
        resp = await client.post(
            "/api/chat/completions",
            json=_body(models.a, browser_run_started_at=began),
            headers=browser.headers,
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "runs_stopped"
        assert provider.calls == []

    async def test_a_run_that_began_after_the_stop_goes_on(
        self, client, browser, models, provider, db_session, agent_on
    ):
        await save_extension_settings(db_session, ExtensionSettings(stop_runs_before=self._at(-60)))
        await db_session.commit()
        provider.reply(*CLICK_REPLY)
        began = int(datetime.datetime.now(datetime.UTC).timestamp() * 1000)
        resp = await client.post(
            "/api/chat/completions",
            json=_body(models.a, browser_run_started_at=began),
            headers=browser.headers,
        )
        assert resp.status_code == 200, resp.text

    async def test_a_step_that_does_not_say_when_it_began_is_refused_while_a_stop_stands(
        self, client, browser, models, provider, db_session, agent_on
    ):
        """An older extension cannot outlast a stop by leaving the field out."""
        await save_extension_settings(db_session, ExtensionSettings(stop_runs_before=self._at(0)))
        await db_session.commit()
        provider.reply(*CLICK_REPLY)
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "runs_stopped"

    async def test_without_a_stop_nothing_changes(self, client, browser, models, provider, db_session, agent_on):
        provider.reply(*CLICK_REPLY)
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 200, resp.text


def _began(minutes_ago: float) -> int:
    return int((datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=minutes_ago)).timestamp() * 1000)


@pytest.mark.usefixtures("agent_on")
class TestTheRunsLimits:
    """The administrator's limits on a run, checked at each step before anything is spent."""

    async def test_a_run_past_its_time_is_refused_and_one_within_it_goes_on(
        self, client, browser, models, provider, db_session
    ):
        await save_extension_settings(db_session, ExtensionSettings(agent_max_minutes=5))
        await db_session.commit()
        provider.reply(*CLICK_REPLY)
        resp = await client.post(
            "/api/chat/completions", json=_body(models.a, browser_run_started_at=_began(8)), headers=browser.headers
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "run_too_long"
        assert "5 minutes" in resp.json()["detail"]["message"]
        assert provider.calls == []
        # Inside the limit, and a little past it (the extension ends the run itself; clocks differ).
        resp = await client.post(
            "/api/chat/completions", json=_body(models.a, browser_run_started_at=_began(6)), headers=browser.headers
        )
        assert resp.status_code == 200, resp.text

    async def test_the_days_runs_are_counted_from_admin_logs(self, client, browser, models, provider, db_session, user):
        from app.models.extension import ExtensionEvent

        await save_extension_settings(db_session, ExtensionSettings(agent_runs_per_day=2))
        for _ in range(2):
            db_session.add(
                ExtensionEvent(actor_user_id=user.id, actor_username=user.username, kind="agent_task", outcome="done")
            )
        # Somebody else's run, and one of yesterday's, do not count.
        other = User(username="someone", email="s@test", hashed_password="x", auth_provider="local", is_active=True)
        db_session.add(other)
        await db_session.flush()
        db_session.add(
            ExtensionEvent(actor_user_id=other.id, actor_username="someone", kind="agent_task", outcome="done")
        )
        db_session.add(
            ExtensionEvent(
                actor_user_id=user.id,
                actor_username=user.username,
                kind="agent_task",
                outcome="done",
                created_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                - datetime.timedelta(days=1, minutes=1),
            )
        )
        await db_session.commit()
        provider.reply(*CLICK_REPLY)
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "daily_runs_reached"
        assert provider.calls == []
        # One run fewer, and the step goes through.
        await save_extension_settings(db_session, ExtensionSettings(agent_runs_per_day=3))
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 200, resp.text

    async def test_the_newest_package_can_be_required(self, client, browser, models, provider, db_session, monkeypatch):
        from types import SimpleNamespace as NS

        from app.api import chat as chat_api

        monkeypatch.setattr(chat_api, "current_build", AsyncMock(return_value=NS(version="1.0.0.9")))
        await save_extension_settings(db_session, ExtensionSettings(require_newest_package=True))
        await db_session.commit()
        provider.reply(*CLICK_REPLY)
        # This browser never said which package it runs: treated as older.
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "package_outdated"
        assert "1.0.0.9" in resp.json()["detail"]["message"]
        assert provider.calls == []
        from app.models.extension import ExtensionSession

        await db_session.execute(
            update(ExtensionSession)
            .where(ExtensionSession.id == browser.session_id)
            .values(extension_version="1.0.0.8")
        )
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 403
        await db_session.execute(
            update(ExtensionSession)
            .where(ExtensionSession.id == browser.session_id)
            .values(extension_version="1.0.0.9")
        )
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 200, resp.text

    async def test_without_the_switch_an_old_package_is_not_refused(
        self, client, browser, models, provider, db_session
    ):
        provider.reply(*CLICK_REPLY)
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        assert resp.status_code == 200, resp.text


def _with_page(site: str, *, images: bool = False) -> list:
    """A step whose tool answer carries page content from `site`, as the panel wraps it."""
    page = f'<untrusted_page_content_ab12cd34 site="{site}">\nWelcome\n</untrusted_page_content_ab12cd34>'
    messages = [
        *TASK,
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_page", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": page},
    ]
    if images:
        messages.append(
            {
                "role": "user",
                "content": [{"type": "text", "text": "The page."}, {"type": "image_url", "image_url": {"url": SHOT}}],
            }
        )
    return messages


class TestDataLocationOnTheServer:
    """The rules the extension keeps, read off the step the server was sent."""

    @pytest.fixture
    async def control_on(self, db_session, user, agent_on) -> None:
        from app.services.resource_access_service import AccessGrant

        await set_chat_tool_access(
            db_session,
            "browser_control",
            access_type="private",
            grants=[AccessGrant(target_type="user", target=user.id)],
        )

    @pytest.fixture
    async def vision(self, db_session) -> AIModel:
        row = await _model(db_session, "gpt-vision")
        row.pricing_raw = VISION_RAW
        await db_session.commit()
        return row

    @pytest.mark.usefixtures("agent_on")
    async def test_an_internal_sites_page_goes_only_to_a_model_inside_the_organisation(
        self, client, browser, models, provider, db_session
    ):
        await save_extension_settings(
            db_session,
            ExtensionSettings(internal_sites=("*.corp.example",), internal_connections=(models.b.connection_id,)),
        )
        await db_session.commit()
        provider.reply(*CLICK_REPLY)
        resp = await client.post(
            "/api/chat/completions", json=_body(models.a, _with_page("app.corp.example")), headers=browser.headers
        )
        assert resp.status_code == 403
        assert resp.json()["detail"] == {
            "code": "internal_site_not_allowed",
            "message": "Your administrator keeps app.corp.example inside the organisation: this model may not see it.",
            "site": "app.corp.example",
        }
        assert provider.calls == []
        # A model on a connection inside the organisation may; and any model may see another site.
        resp = await client.post(
            "/api/chat/completions", json=_body(models.b, _with_page("app.corp.example")), headers=browser.headers
        )
        assert resp.status_code == 200, resp.text
        provider.reply(*CLICK_REPLY)
        resp = await client.post(
            "/api/chat/completions", json=_body(models.a, _with_page("shop.example.com")), headers=browser.headers
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.usefixtures("control_on")
    async def test_screenshots_go_only_to_a_model_on_the_screenshot_list(
        self, client, browser, models, vision, provider, db_session
    ):
        await save_extension_settings(
            db_session, ExtensionSettings(full_control=True, screenshot_models=(f"model::{models.a.id}",))
        )
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(vision, _with_shot(SHOT)), headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "screenshots_not_allowed"
        assert provider.calls == []

    @pytest.mark.usefixtures("control_on")
    async def test_screenshots_kept_inside_the_organisation(
        self, client, browser, models, vision, provider, db_session
    ):
        await save_extension_settings(
            db_session,
            ExtensionSettings(
                full_control=True, internal_connections=(models.a.connection_id,), external_screenshots=False
            ),
        )
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(vision, _with_shot(SHOT)), headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "screenshots_not_allowed"
        # The vision model moved inside the organisation: allowed.
        await save_extension_settings(
            db_session,
            ExtensionSettings(
                full_control=True, internal_connections=(vision.connection_id,), external_screenshots=False
            ),
        )
        await db_session.commit()
        resp = await client.post("/api/chat/completions", json=_body(vision, _with_shot(SHOT)), headers=browser.headers)
        assert resp.status_code == 200, resp.text
