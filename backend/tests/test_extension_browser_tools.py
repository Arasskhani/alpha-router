"""The browser extension's agent in a chat turn: its tools go to the model, its tool calls come back.

Each step of the agent is one ``/api/chat/completions`` call from a connected
browser carrying ``browser_tools``. The provider is faked at ``acompletion``;
the endpoint, the preflight (model, access, budget hold), the turn and its
settlement are real, on the test database.
"""

from __future__ import annotations

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
from app.services import budget_reservation_service, chat_turn_context, extension_tokens, proxy_service, turn_settlement
from app.services.budget_reservation_service import reservation_hold_usd
from app.services.chat_markers import BROWSER_TOOL_CHOICE_BODY_KEY, BROWSER_TOOLS_BODY_KEY
from app.services.chat_tool_access_service import set_chat_tool_access
from app.services.chat_turn_context import build_turn_context
from app.services.extension_settings import ExtensionSettings, save_extension_settings
from app.services.extension_tokens import create_session
from app.services.provider_stream import ProviderAttempt
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
        self.replies: list[_Stream] = []
        self.calls: list[dict] = []

    def reply(self, *chunks, fail: Exception | None = None) -> Provider:
        self.replies.append(_Stream(list(chunks), fail=fail))
        return self

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


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
        assert call["messages"] == TASK

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
        assert provider.calls[0]["messages"] == FOLLOW_UP
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

    async def test_a_broken_stream_is_not_retried_without_streaming(
        self, client, browser, models, provider, session_factory
    ):
        # The retry would read only the words and lose the tool calls.
        broken = RuntimeError("Attempted to access streaming response content, without having called read()")
        provider.reply(fail=broken).reply(_text("never"))
        resp = await client.post("/api/chat/completions", json=_body(models.a), headers=browser.headers)
        frames = _frames(resp.text)
        assert len(provider.calls) == 1
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
        assert detail["code"] == "model_not_allowed"
        assert "browser agent" in detail["message"]
        assert provider.calls == []

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
        assert ctx.completion_kwargs["messages"] == FOLLOW_UP

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
