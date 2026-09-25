"""The browser agent's trail (``/api/extension/events``) and its reviewer (``/api/extension/review-action``)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.api.admin_logs import list_admin_logs
from app.config import get_settings
from app.core.security import create_access_token
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.connection import Connection
from app.models.extension import ExtensionEvent
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.services import extension_agent, extension_tokens
from app.services.chat_tool_access_service import set_chat_tool_access
from app.services.extension_agent import clean_detail, parse_verdict
from app.services.extension_settings import ExtensionSettings, save_extension_settings
from app.services.extension_tokens import create_session
from app.services.secret_crypto import encrypt_secret

CSRF = "csrf-token"


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    monkeypatch.setattr(extension_tokens, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.usage_logging_service.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.budget_notice_service.AsyncSessionLocal", session_factory)


@pytest.fixture
async def agent_on(db_session, user) -> None:
    await set_chat_tool_access(db_session, "browser_agent", access_type="public", grants=[])
    plan = BudgetPlan(name="agent-plan", monthly_budget_usd=100)
    db_session.add(plan)
    await db_session.flush()
    db_session.add(PlanAssignment(user_id=user.id, plan_id=plan.id))
    await db_session.commit()


@pytest.fixture
async def browser(db_session, user) -> SimpleNamespace:
    pair = await create_session(db_session, user=user, device_name="Chrome", user_agent="UA", ip="10.0.0.5")
    await db_session.commit()
    return SimpleNamespace(session_id=pair.session_id, headers={"Authorization": f"Bearer {pair.access_token}"})


def _sign_in(client, user) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _events(session_factory) -> list[ExtensionEvent]:
    async with session_factory() as fresh:
        return list((await fresh.execute(select(ExtensionEvent).order_by(ExtensionEvent.id))).scalars().all())


STEP = {
    "kind": "agent_step",
    "site": "Shop.Example.com",
    "action": "type_text",
    "outcome": "ok",
    "detail": {
        "task_id": "run-1",
        "step": 3,
        "mode": "ask",
        "class": "act",
        "approval": "user",
        "role": "textbox",
        "label": "Delivery address",
        "chars": 24,
        # Never kept: what was typed, a full URL, anything unknown.
        "text": "12 Secret Street, London",
        "url": "https://shop.example.com/checkout?token=abc",
        "note": "free text",
    },
}
TASK = {
    "kind": "agent_task",
    "site": "shop.example.com",
    "outcome": "done",
    "detail": {"task_id": "run-1", "steps": 7, "mode": "ask", "model": "model::4", "duration_ms": 41000},
}


# --- events ---------------------------------------------------------------------------


@pytest.mark.usefixtures("agent_on")
class TestEvents:
    async def test_steps_and_runs_are_recorded_for_admin_logs(self, client, browser, user, session_factory):
        resp = await client.post("/api/extension/events", json={"events": [STEP, TASK]}, headers=browser.headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"recorded": 2}
        step, task = await _events(session_factory)
        assert (step.kind, step.site, step.action, step.outcome) == (
            "agent_step",
            "shop.example.com",
            "type_text",
            "ok",
        )
        assert step.actor_user_id == user.id
        assert step.actor_username == user.username
        assert step.session_id == browser.session_id
        assert step.actor_ip == "127.0.0.1"
        assert json.loads(step.detail_json) == {
            "task_id": "run-1",
            "step": 3,
            "mode": "ask",
            "class": "act",
            "approval": "user",
            "role": "textbox",
            "label": "Delivery address",
            "chars": 24,
        }
        assert "Secret Street" not in step.detail_json
        assert "token=abc" not in step.detail_json
        assert (task.kind, task.outcome) == ("agent_task", "done")
        assert json.loads(task.detail_json)["steps"] == 7

    async def test_they_appear_in_admin_logs(self, client, browser, db_session):
        await client.post("/api/extension/events", json={"events": [STEP]}, headers=browser.headers)
        logs = await list_admin_logs(
            db=db_session,
            _=None,
            limit=100,
            offset=0,
            actor=None,
            action=None,
            resource_type=None,
            start_date=None,
            end_date=None,
            source="browser_extension",
        )
        [row] = logs["items"]
        assert row["action"] == "agent_step"
        assert row["resource_id"] == "shop.example.com"
        assert row["outcome"] == "ok"
        assert row["detail"]["label"] == "Delivery address"

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            (lambda e: e.update(site="https://shop.example.com/path"), "host name"),
            (lambda e: e.update(outcome="done"), "how an agent_step ends"),
            (lambda e: e.update(action="Click Me"), "tool name"),
            (lambda e: e["detail"].update(label="x" * 5000), "at most 4096 bytes"),
        ],
    )
    async def test_an_event_that_does_not_fit_is_refused(self, client, browser, session_factory, change, message):
        event = json.loads(json.dumps(STEP))
        change(event)
        resp = await client.post("/api/extension/events", json={"events": [TASK, event]}, headers=browser.headers)
        assert resp.status_code == 400, resp.text
        assert message in resp.json()["detail"]["message"]
        # Nothing of the batch is kept.
        assert await _events(session_factory) == []

    @pytest.mark.parametrize(
        "body",
        [
            {"events": []},
            {"events": [STEP] * 51},
            {"events": [{**STEP, "kind": "page_context"}]},
            {"events": [{**STEP, "extra": 1}]},
        ],
    )
    async def test_a_batch_that_does_not_fit_is_refused(self, client, browser, body):
        resp = await client.post("/api/extension/events", json=body, headers=browser.headers)
        assert resp.status_code == 422

    async def test_from_the_web_app(self, client, user):
        headers = _sign_in(client, user)
        resp = await client.post("/api/extension/events", json={"events": [STEP]}, headers=headers)
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "extension_only"

    async def test_one_browser_is_held_to_120_calls_a_minute(self, client, browser):
        for _ in range(120):
            ok = await client.post("/api/extension/events", json={"events": [TASK]}, headers=browser.headers)
            assert ok.status_code == 200
        refused = await client.post("/api/extension/events", json={"events": [TASK]}, headers=browser.headers)
        assert refused.status_code == 429


async def test_events_need_the_agent(client, browser, session_factory):
    resp = await client.post("/api/extension/events", json={"events": [STEP]}, headers=browser.headers)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "agent_not_permitted"
    assert await _events(session_factory) == []


class TestTheDetail:
    def test_only_known_fields_with_good_values_are_kept(self):
        assert clean_detail(
            {
                "step": True,
                "steps": -1,
                "mode": "turbo",
                "approval": "admin",
                "error": "Stale Ref!",
                "key": "Enter",
                "to_site": "Other.Example.org.",
                "model": "gpt-4o",
                "label": "Pay\n now\x00",
                "reason": "purchase",
            }
        ) == {"key": "Enter", "to_site": "other.example.org", "label": "Pay  now", "reason": "purchase"}


# --- the reviewer ---------------------------------------------------------------------


async def _review_model(db) -> AIModel:
    connection = Connection(
        name="c-review", provider_type="openai", api_key_encrypted=encrypt_secret("sk-x"), is_active=True
    )
    db.add(connection)
    await db.flush()
    row = AIModel(
        connection_id=connection.id,
        external_id="gpt-review",
        display_name="Reviewer",
        provider_type="openai",
        is_enabled=True,
        input_cost_per_1k=0.001,
        output_cost_per_1k=0.002,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
async def auto_mode(db_session, agent_on) -> AIModel:
    model = await _review_model(db_session)
    await save_extension_settings(
        db_session, ExtensionSettings(agent_auto_mode=True, agent_review_model=f"model::{model.id}")
    )
    await db_session.commit()
    return model


REVIEW = {
    "task": "Fill in the delivery form with my work address and stop before paying.",
    "tool": "type_text",
    "site": "shop.example.com",
    "target": "textbox: Delivery address",
    "arguments": {"ref": "e12", "text": "Silk Road Tower, Floor 3"},
    "history": ["read_page on shop.example.com", "click button 'Checkout' on shop.example.com"],
}


def _reply(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None)


class TestReview:
    async def test_an_action_that_fits_is_allowed(self, client, browser, auto_mode, monkeypatch, session_factory):
        model = AsyncMock(return_value=_reply('{"decision": "allow", "reason": "The user asked for this."}'))
        monkeypatch.setattr(extension_agent, "acompletion", model)
        resp = await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"decision": "allow", "reason": "The user asked for this."}
        [call] = model.await_args_list
        prompt = call.kwargs["messages"][1]["content"]
        assert REVIEW["task"] in prompt
        assert "Silk Road Tower" in prompt
        assert call.kwargs["messages"][0]["role"] == "system"
        # A billed helper call, named as the extension's.
        async with session_factory() as fresh:
            [log] = (await fresh.execute(select(RequestLog))).scalars().all()
        assert log.client_app == "Alpharouter Extension (helper:review)"
        assert log.success is True

    @pytest.mark.parametrize(
        "content",
        [
            '{"decision": "ask", "reason": "Paying was not asked for."}',
            "Sure, go ahead!",
            '{"decision": "ALLOW"}',
            '["allow"]',
            "",
        ],
    )
    async def test_anything_but_a_clear_allow_is_ask(self, client, browser, auto_mode, monkeypatch, content):
        monkeypatch.setattr(extension_agent, "acompletion", AsyncMock(return_value=_reply(content)))
        resp = await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        assert resp.status_code == 200
        assert resp.json()["decision"] == "ask"
        assert resp.json()["reason"]

    async def test_a_failing_reviewer_means_ask(self, client, browser, auto_mode, monkeypatch, session_factory):
        monkeypatch.setattr(extension_agent, "acompletion", AsyncMock(side_effect=RuntimeError("provider down")))
        resp = await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        assert resp.status_code == 200
        assert resp.json() == {"decision": "ask", "reason": "The reviewer could not be reached."}
        async with session_factory() as fresh:
            [log] = (await fresh.execute(select(RequestLog))).scalars().all()
        assert log.success is False

    async def test_a_missing_review_model_means_ask(self, client, browser, auto_mode, db_session, monkeypatch):
        auto_mode.is_enabled = False
        await db_session.commit()
        model = AsyncMock()
        monkeypatch.setattr(extension_agent, "acompletion", model)
        resp = await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        assert resp.json()["decision"] == "ask"
        model.assert_not_awaited()

    async def test_no_budget_means_ask(self, client, browser, auto_mode, db_session, monkeypatch):
        await db_session.execute(BudgetPlan.__table__.update().values(monthly_budget_usd=0.0))
        await db_session.commit()
        model = AsyncMock()
        monkeypatch.setattr(extension_agent, "acompletion", model)
        resp = await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        assert resp.json()["decision"] == "ask"
        model.assert_not_awaited()

    async def test_auto_mode_off_is_refused(self, client, browser, agent_on, monkeypatch):
        model = AsyncMock()
        monkeypatch.setattr(extension_agent, "acompletion", model)
        resp = await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "auto_mode_off"
        model.assert_not_awaited()

    async def test_without_the_agent(self, client, browser):
        resp = await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "agent_not_permitted"

    async def test_from_the_web_app(self, client, user, auto_mode):
        headers = _sign_in(client, user)
        resp = await client.post("/api/extension/review-action", json=REVIEW, headers=headers)
        assert resp.status_code == 400

    async def test_one_browser_is_held_to_60_reviews_a_minute(self, client, browser, auto_mode, monkeypatch):
        model = AsyncMock(return_value=_reply('{"decision": "allow", "reason": "ok"}'))
        monkeypatch.setattr(extension_agent, "acompletion", model)
        for _ in range(60):
            await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        over = await client.post("/api/extension/review-action", json=REVIEW, headers=browser.headers)
        assert over.status_code == 200
        assert over.json()["decision"] == "ask"
        assert model.await_count == 60

    @pytest.mark.parametrize(
        "change",
        [
            lambda body: body.update(arguments={"text": "x" * 5000}),
            lambda body: body.update(history=["step"] * 21),
            lambda body: body.update(tool="Type Text"),
            lambda body: body.update(task=""),
        ],
    )
    async def test_a_request_that_does_not_fit_is_refused(self, client, browser, auto_mode, change):
        body = json.loads(json.dumps(REVIEW))
        change(body)
        resp = await client.post("/api/extension/review-action", json=body, headers=browser.headers)
        assert resp.status_code == 422


class TestTheVerdict:
    def test_allow_needs_the_exact_word(self):
        assert parse_verdict('Verdict: {"decision": "allow", "reason": "fits"}').decision == "allow"
        assert parse_verdict('{"decision": "allow "}').decision == "ask"
        assert parse_verdict('{"decision": true}').decision == "ask"

    def test_the_reason_is_cut_short(self):
        verdict = parse_verdict(json.dumps({"decision": "ask", "reason": "x" * 1000}))
        assert len(verdict.reason) == 200
