# ruff: noqa: F811 -- the turn fixtures are imported from the web tools tests and taken as arguments
"""Guardrails on what goes to a model outside a chat turn: titles, prompts, embeddings, summaries, memory, media."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.guardrail import GuardrailRule
from app.services import chat_title_service
from app.services.guardrail_policy import GuardrailBlocked, bump_policy_version
from app.services.guardrail_turn import guard_media_prompt, guard_texts
from app.services.proxy_service import _guard_embedding_input
from tests.test_chat_web_tools import _server, provider, turn  # noqa: F401 -- fixtures
from tests.test_extension_browser_tools import _model

CARD = "6037991899123453"


@pytest.fixture(autouse=True)
def _events_session(monkeypatch, session_factory):
    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)


async def add_rule(db, *, channels=("chat", "gateway", "context", "extension"), **fields) -> GuardrailRule:
    values = {
        "name": "Cards",
        "mode": "enforce",
        "position": 1,
        "patterns_json": json.dumps(["lib:bank_card"]),
        "match_mode": "any",
        "min_matches": 1,
        "channels_json": json.dumps(list(channels)),
        "destinations_json": "[]",
        "action": "redact",
        "access_type": "public",
        "acl_version": 0,
        "version": 1,
        "user_message": "No card numbers.",
    }
    values.update(fields)
    row = GuardrailRule(**values)
    db.add(row)
    await bump_policy_version(db)
    await db.commit()
    return row


def _reply(text: str) -> SimpleNamespace:
    message = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)


class TestTheHelper:
    async def test_masked_blocked_and_a_route_that_cannot_be_taken(self, db_session, user):
        model = await _model(db_session, "gpt-s1")
        assert (await guard_texts(db_session, [CARD], channel="chat", ai_model=model, user_id=user.id, source="t")).texts == [CARD]  # fmt: skip
        await add_rule(db_session)
        masked = await guard_texts(db_session, [f"card {CARD}", "hi"], channel="chat", ai_model=model, user_id=user.id, source="t")  # fmt: skip
        assert masked.texts == ["card [CARD_1]", "hi"] and masked.restore("[CARD_1]") == CARD
        other = await _model(db_session, "llama-s1")
        await add_rule(db_session, action="route", route_model_id=other.id, position=2)
        routed = await guard_texts(db_session, [CARD], channel="chat", ai_model=model, user_id=user.id, source="t")
        assert routed.refusal
        with pytest.raises(HTTPException) as raised:
            routed.raise_if_refused()
        assert raised.value.status_code == 422


class TestEmbeddings:
    async def test_texts_to_embed_are_masked_and_a_block_refuses_them(self, db_session, user):
        model = await _model(db_session, "embed-1")
        await add_rule(db_session, channels=["gateway"])
        body = {"input": [f"card {CARD}", "plain"]}
        await _guard_embedding_input(db_session, body, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="gateway")  # fmt: skip
        assert body["input"] == ["card [CARD_1]", "plain"]
        tokens = {"input": [[1, 2, 3]]}
        await _guard_embedding_input(db_session, tokens, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="gateway")  # fmt: skip
        assert tokens["input"] == [[1, 2, 3]]
        await add_rule(db_session, channels=["gateway"], action="block", position=2)
        with pytest.raises(HTTPException) as raised:
            await _guard_embedding_input(db_session, {"input": CARD}, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="gateway")  # fmt: skip
        assert raised.value.detail["code"] == "guardrail_blocked"


class TestTitlesAndPrompts:
    async def test_a_refused_chat_is_titled_without_a_model(self, db_session, user, turn, monkeypatch):
        await add_rule(db_session, action="block")

        async def never(**kwargs):
            raise AssertionError("the title model must not be asked")

        monkeypatch.setattr(chat_title_service, "acompletion", never)
        title = await chat_title_service.generate_chat_title(
            db_session, user, f"model::{turn.model.id}", [{"role": "user", "content": f"pay {CARD}"}]
        )
        assert title

    async def test_a_masked_chat_is_titled_with_its_values_back(self, db_session, user, turn, monkeypatch):
        await add_rule(db_session)
        seen: list[str] = []

        async def model(**kwargs):
            seen.append(kwargs["messages"][1]["content"])
            return _reply("Paying [CARD_1]")

        monkeypatch.setattr(chat_title_service, "acompletion", model)
        title = await chat_title_service.generate_chat_title(
            db_session, user, f"model::{turn.model.id}", [{"role": "user", "content": f"pay {CARD}"}]
        )
        assert CARD not in seen[0] and "[CARD_1]" in seen[0]
        assert CARD in title

    async def test_improving_a_prompt_is_refused_like_a_turn(self, client, db_session, turn):
        await add_rule(db_session, action="block")
        resp = await client.post(
            "/api/chat/enhance-prompt",
            json={"model": f"model::{turn.model.id}", "prompt": f"card {CARD}", "mode": "improve", "context": "chat"},
            headers=turn.headers,
        )
        assert resp.status_code == 422 and resp.json()["detail"]["message"] == "No card numbers."

    async def test_a_media_prompt(self, db_session, user):
        model = await _model(db_session, "image-1")
        await add_rule(db_session)
        assert await guard_media_prompt(db_session, f"draw {CARD}", ai_model=model, user_id=user.id) == "draw [CARD_1]"
        assert await guard_media_prompt(db_session, "draw", ai_model=None, user_id=user.id) == "draw"


class TestWhatThePlatformSends:
    async def test_a_summary_is_refused_and_a_memory_gets_its_values_back(self, db_session, user, monkeypatch):
        import litellm

        from app.services import chat_summary_service, memory_extraction_service
        from app.services.memory_extraction_service import ExtractionBilling

        model = await _model(db_session, "summary-1")
        await add_rule(db_session, channels=["context"])
        seen: list[str] = []

        async def fake(**kwargs):
            seen.append(kwargs["messages"][-1]["content"])
            return _reply('{"operations": [{"op": "add", "content": "card [CARD_1]"}]}')

        monkeypatch.setattr(litellm, "acompletion", fake)
        monkeypatch.setattr(memory_extraction_service, "record_extraction_usage", _noop)

        async def settings(db):
            return {"extraction_model_id": model.id}

        monkeypatch.setattr(memory_extraction_service, "get_memory_settings", settings)
        billing = ExtractionBilling(
            user_id=user.id,
            username=user.username,
            project_id=None,
            subject_type=None,
            key_prefix="k",
            operation_type="m",
        )
        answer = await memory_extraction_service.ask_extractor(
            db_session, system_prompt="s", user_content=f"user: my card {CARD}", parse=json.loads, billing=billing
        )
        assert CARD not in seen[0]
        assert answer["operations"][0]["content"] == f"card {CARD}"

        await add_rule(db_session, channels=["context"], action="block", position=2)
        row = SimpleNamespace(user_id=user.id, session_id="s1", attempt_count=0, project_id=None)
        with pytest.raises(GuardrailBlocked):
            await chat_summary_service._complete(
                db_session,
                row,
                system="s",
                user_content=CARD,
                model_id=model.id,
                completer=None,
                first_sequence=1,
                max_tokens=50,  # fmt: skip
            )


async def _noop(**kwargs) -> None:
    return None
