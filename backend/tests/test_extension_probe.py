"""The browser_control probe: a made-up page, one button to click, and what the model's click says."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.security import SecurityAuditEvent
from app.services import extension_probe
from app.services.extension_probe import HEIGHT, WIDTH, load_results, parse_click, probe_page, run_probe
from app.services.secret_crypto import encrypt_secret

CSRF = "csrf-probe-token"
VISION_RAW = json.dumps({"architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}})


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.usage_logging_service.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.budget_notice_service.AsyncSessionLocal", session_factory)


async def _model(db, external_id: str, *, vision: bool = True) -> AIModel:
    connection = Connection(
        name=f"c-{external_id}", provider_type="openai", api_key_encrypted=encrypt_secret("sk-x"), is_active=True
    )
    db.add(connection)
    await db.flush()
    row = AIModel(
        connection_id=connection.id,
        external_id=external_id,
        display_name=external_id,
        provider_type="openai",
        is_enabled=True,
        pricing_raw=VISION_RAW if vision else None,
        input_cost_per_1k=0.001,
        output_cost_per_1k=0.002,
    )
    db.add(row)
    await db.commit()
    return row


async def _budget(db, user) -> None:
    plan = BudgetPlan(name="probe-plan", monthly_budget_usd=100)
    db.add(plan)
    await db.flush()
    db.add(PlanAssignment(user_id=user.id, plan_id=plan.id))
    await db.commit()


def _click_reply(x: int, y: int) -> SimpleNamespace:
    call = SimpleNamespace(
        function=SimpleNamespace(name="computer", arguments=json.dumps({"action": "left_click", "coordinate": [x, y]}))
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))], usage=None
    )


def _text_reply(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=None))], usage=None
    )


class TestThePage:
    def test_is_a_png_of_the_stated_size_with_the_target_inside_it(self):
        page = probe_page(7)
        assert page.png.startswith(b"\x89PNG")
        box = page.target
        assert box.x >= 0 and box.x + box.width <= WIDTH
        assert box.y >= 0 and box.y + box.height <= HEIGHT
        assert box.contains(box.x + box.width / 2, box.y + box.height / 2)
        assert not box.contains(box.x - 1, box.y)

    def test_the_same_seed_draws_the_same_page_and_another_seed_another(self):
        assert probe_page(7).png == probe_page(7).png
        assert probe_page(7).target == probe_page(7).target
        assert probe_page(7).png != probe_page(8).png


class TestTheClick:
    def test_a_left_click_with_a_point_is_read(self):
        assert parse_click(_click_reply(120, 300)) == (120, 300)

    @pytest.mark.parametrize(
        "reply",
        [
            _text_reply("I would click the Continue button."),
            SimpleNamespace(choices=[], usage=None),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(function=SimpleNamespace(name="computer", arguments="not json"))
                            ],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="computer",
                                        arguments=json.dumps({"action": "scroll", "coordinate": [1, 2]}),
                                    )
                                )
                            ],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="computer",
                                        arguments=json.dumps({"action": "left_click", "coordinate": [1]}),
                                    )
                                )
                            ],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[SimpleNamespace(function=SimpleNamespace(name="other", arguments="{}"))],
                        )
                    )
                ]
            ),
        ],
    )
    def test_anything_else_is_no_click(self, reply):
        assert parse_click(reply) is None


class TestTheProbe:
    async def test_a_model_that_clicks_the_button_passes(self, db_session, user, monkeypatch):
        await _budget(db_session, user)
        model = await _model(db_session, "gpt-vision")
        seeds = (11, 12, 13)
        centres = {seed: (probe_page(seed).target.x + 75, probe_page(seed).target.y + 22) for seed in seeds}
        answers = iter(centres.values())
        monkeypatch.setattr(
            extension_probe, "acompletion", AsyncMock(side_effect=lambda **kwargs: _click_reply(*next(answers)))
        )
        result = await run_probe(db_session, user=user, model_ref=f"model::{model.id}", seeds=seeds)
        await db_session.commit()
        assert (result.vision, result.tool_calling, result.hits, result.trials, result.passed) == (
            True,
            True,
            3,
            3,
            True,
        )
        assert result.detail == "Clicked inside the button in 3 of 3 trials."
        assert all(t.hit and t.called for t in result.results)
        # The last result is kept for the page, without the trials.
        kept = await load_results(db_session)
        assert kept[f"model::{model.id}"]["passed"] is True
        assert "results" not in kept[f"model::{model.id}"]

    async def test_a_model_that_misses_fails_and_says_how_often_it_hit(self, db_session, user, monkeypatch):
        await _budget(db_session, user)
        model = await _model(db_session, "gpt-vision-poor")
        seeds = (21, 22, 23)
        hit = probe_page(21).target
        answers = iter([(hit.x + 10, hit.y + 10), (1, 1), (2, 2)])
        monkeypatch.setattr(
            extension_probe, "acompletion", AsyncMock(side_effect=lambda **kwargs: _click_reply(*next(answers)))
        )
        result = await run_probe(db_session, user=user, model_ref=f"model::{model.id}", seeds=seeds)
        assert (result.tool_calling, result.hits, result.passed) == (True, 1, False)
        assert result.detail == "Clicked inside the button in 1 of 3 trials."

    async def test_a_model_that_answers_in_words_cannot_drive(self, db_session, user, monkeypatch):
        await _budget(db_session, user)
        model = await _model(db_session, "gpt-vision-talker")
        monkeypatch.setattr(extension_probe, "acompletion", AsyncMock(return_value=_text_reply("I see three buttons.")))
        result = await run_probe(db_session, user=user, model_ref=f"model::{model.id}", seeds=(1, 2, 3))
        assert (result.tool_calling, result.hits, result.passed) == (False, 0, False)
        assert "without calling the tool" in result.detail

    async def test_a_model_that_reads_no_images_is_not_asked(self, db_session, user, monkeypatch):
        model = await _model(db_session, "gpt-text", vision=False)
        called = AsyncMock()
        monkeypatch.setattr(extension_probe, "acompletion", called)
        result = await run_probe(db_session, user=user, model_ref=f"model::{model.id}")
        assert (result.vision, result.passed, result.trials) == (False, False, 0)
        assert result.detail == "This model does not read images."
        called.assert_not_called()

    async def test_a_provider_that_fails_is_reported(self, db_session, user, monkeypatch):
        await _budget(db_session, user)
        model = await _model(db_session, "gpt-vision-down")
        monkeypatch.setattr(extension_probe, "acompletion", AsyncMock(side_effect=RuntimeError("provider down")))
        result = await run_probe(db_session, user=user, model_ref=f"model::{model.id}", seeds=(1, 2, 3))
        assert (result.tool_calling, result.passed) == (False, False)
        assert result.detail  # the failure, in words
        assert all(t.error for t in result.results)


def _sign_in(client, user) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


class TestTheEndpoint:
    async def test_an_administrator_runs_it_and_the_page_shows_the_result(
        self, client, db_session, admin, session_factory, monkeypatch
    ):
        await _budget(db_session, admin)
        model = await _model(db_session, "gpt-vision")
        monkeypatch.setattr(extension_probe, "acompletion", AsyncMock(return_value=_click_reply(-5, -5)))
        headers = _sign_in(client, admin)
        resp = await client.post(f"/api/admin/extension/probe/model::{model.id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["model_ref"] == f"model::{model.id}"
        assert (body["vision"], body["tool_calling"], body["hits"], body["trials"], body["passed"]) == (
            True,
            True,
            0,
            3,
            False,
        )
        assert len(body["results"]) == 3
        settings = (await client.get("/api/admin/extension/settings")).json()
        assert settings["probes"][f"model::{model.id}"]["passed"] is False
        async with session_factory() as fresh:
            events = list(
                (
                    await fresh.execute(
                        select(SecurityAuditEvent).where(SecurityAuditEvent.action == "extension_model_probed")
                    )
                )
                .scalars()
                .all()
            )
        assert len(events) == 1
        assert json.loads(events[0].detail_json) == {
            "model": f"model::{model.id}",
            "passed": False,
            "hits": 0,
            "trials": 3,
        }

    async def test_a_bad_name_and_a_reader_are_refused(self, client, db_session, admin, user):
        headers = _sign_in(client, admin)
        assert (await client.post("/api/admin/extension/probe/gpt-4", headers=headers)).status_code == 400
        headers = _sign_in(client, user)
        resp = await client.post("/api/admin/extension/probe/model::1", headers=headers)
        assert resp.status_code in (401, 403)
