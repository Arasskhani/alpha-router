# ruff: noqa: F811 -- the turn fixtures are imported from the web tools tests and taken as arguments
"""Guardrails on a chat turn: masked before it leaves and given back, blocked, routed; the platform's context too."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.chat import ChatMessage
from app.models.connection import Connection
from app.models.guardrail import GuardrailEvent, GuardrailRule
from app.services import guardrail_policy
from app.services.guardrail_policy import GuardrailSettings, bump_policy_version, save_settings
from app.services.guardrail_turn import (
    GUARDRAIL_BODY_KEY,
    MODEL_PINNED_BODY_KEY,
    VIA_EXTENSION_BODY_KEY,
    guard_context,
    guard_request,
    guardrail_reply_state,
    turn_channel,
)
from app.services.user_chat_storage_service import create_chat_session
from tests.test_chat_web_tools import _server, provider, turn  # noqa: F401 -- fixtures
from tests.test_extension_browser_tools import _frames, _model, _text

CARD = "6037991899123453"


@pytest.fixture(autouse=True)
def _events_session(monkeypatch, session_factory):
    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)


async def add_rule(db, **fields) -> GuardrailRule:
    values = {
        "name": "Cards",
        "mode": "enforce",
        "position": 1,
        "patterns_json": json.dumps(["lib:bank_card"]),
        "match_mode": "any",
        "min_matches": 1,
        "channels_json": json.dumps(["chat", "attachments", "context", "gateway", "extension"]),
        "destinations_json": "[]",
        "action": "redact",
        "access_type": "public",
        "acl_version": 0,
        "version": 1,
        "user_message": "Card numbers were masked before sending.",
    }
    if "channels" in fields:
        values["channels_json"] = json.dumps(fields.pop("channels"))
    values.update(fields)
    row = GuardrailRule(**values)
    db.add(row)
    await bump_policy_version(db)
    await db.commit()
    return row


def ask(model, text: str, **extra) -> dict:
    return {"model": f"model::{model.id}", "messages": [{"role": "user", "content": text}], **extra}


def words(frames: list) -> str:
    return "".join(
        (f["choices"][0]["delta"].get("content") or "") for f in frames if isinstance(f, dict) and f.get("choices")
    )


def shown(frames: list) -> list[dict]:
    return [
        f["alpha_router"]["guardrail"]
        for f in frames
        if isinstance(f, dict) and "guardrail" in (f.get("alpha_router") or {})
    ]


async def events(session_factory) -> list[GuardrailEvent]:
    async with session_factory() as db:
        return list((await db.execute(select(GuardrailEvent).order_by(GuardrailEvent.id))).scalars().all())


class TestAMaskedTurn:
    async def test_the_model_never_sees_the_value_and_the_person_gets_it_back(
        self, client, db_session, session_factory, user, turn, provider
    ):
        await add_rule(db_session)
        await create_chat_session(db_session, user.id, {"id": "g1", "title": "Pay", "model": "gpt-a"})
        await db_session.commit()
        # The model writes the placeholder back, cut between two chunks.
        provider.reply(_text("I will charge [CA"), _text("RD_1] today.", "stop"))
        resp = await client.post(
            "/api/chat/completions",
            json=ask(
                turn.model,
                f"charge my card {CARD} please",
                chat_session_id="g1",
                persist_chat=True,
                user_message={"role": "user", "content": f"charge my card {CARD} please", "clientMessageId": "u1"},
                assistant_client_message_id="a1",
            ),
            headers=turn.headers,
        )
        assert resp.status_code == 200, resp.text
        sent = json.dumps(provider.calls[0]["messages"], ensure_ascii=False)
        assert CARD not in sent and "[CARD_1]" in sent
        frames = _frames(resp.text)
        assert words(frames) == f"I will charge {CARD} today."
        assert shown(frames) == [
            {"notices": [{"action": "redact", "message": "Card numbers were masked before sending."}]}
        ]
        answer = (
            await db_session.execute(
                select(ChatMessage).where(ChatMessage.session_id == "g1", ChatMessage.role == "assistant")
            )
        ).scalar_one()
        await db_session.refresh(answer)
        assert answer.content == f"I will charge {CARD} today."
        assert answer.meta["guardrailNotices"] == [
            {"action": "redact", "message": "Card numbers were masked before sending."}
        ]
        (event,) = await events(session_factory)
        assert (event.action, event.channel, event.user_id) == ("redact", "chat", user.id)
        assert CARD not in (event.findings_json or "")

    async def test_an_administrator_may_keep_the_placeholders_in_the_reply(self, client, db_session, turn, provider):
        await add_rule(db_session)
        await save_settings(db_session, GuardrailSettings(restore_replies=False))
        await db_session.commit()
        provider.reply(_text("Charging [CARD_1].", "stop"))
        resp = await client.post("/api/chat/completions", json=ask(turn.model, f"card {CARD}"), headers=turn.headers)
        assert words(_frames(resp.text)) == "Charging [CARD_1]."


class TestABlockedTurn:
    async def test_nothing_is_sent_and_the_person_is_told_why(
        self, client, db_session, session_factory, turn, provider
    ):
        await add_rule(db_session, action="block", user_message="Card numbers may not be sent to AI models.")
        resp = await client.post("/api/chat/completions", json=ask(turn.model, f"card {CARD}"), headers=turn.headers)
        assert resp.status_code == 422
        assert resp.json()["detail"] == {
            "code": "guardrail_blocked",
            "message": "Card numbers may not be sent to AI models.",
            "persisted": False,
            "user_content": "card 603…453",
        }
        assert provider.calls == []
        assert [e.action for e in await events(session_factory)] == ["block"]

    async def test_a_turn_that_cannot_be_checked_is_not_sent(self, client, db_session, turn, provider, monkeypatch):
        await add_rule(db_session)
        monkeypatch.setattr(guardrail_policy, "decide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        resp = await client.post("/api/chat/completions", json=ask(turn.model, "hello"), headers=turn.headers)
        assert resp.status_code == 503 and resp.json()["detail"]["code"] == "guardrail_unavailable"
        assert provider.calls == []

    async def test_a_rule_for_another_channel_lets_it_through(self, client, db_session, turn, provider):
        await add_rule(db_session, action="block", channels=["attachments"])
        provider.reply(_text("ok", "stop"))
        resp = await client.post("/api/chat/completions", json=ask(turn.model, f"card {CARD}"), headers=turn.headers)
        assert resp.status_code == 200 and words(_frames(resp.text)) == "ok"


class TestARoutedTurn:
    async def test_it_goes_to_the_model_the_administrator_chose(
        self, client, db_session, session_factory, turn, provider
    ):
        internal = await _model(db_session, "llama-internal")
        await add_rule(
            db_session,
            action="route",
            route_model_id=internal.id,
            user_message="Answered by {model}, as your organisation requires.",
            destinations_json=json.dumps(["public"]),
        )
        conn = await db_session.get(Connection, internal.connection_id)
        conn.trust_level = "internal"
        await bump_policy_version(db_session)
        await db_session.commit()
        provider.reply(_text("Handled internally.", "stop"))
        resp = await client.post("/api/chat/completions", json=ask(turn.model, f"card {CARD}"), headers=turn.headers)
        assert resp.status_code == 200, resp.text
        assert provider.calls[0]["model"].endswith("llama-internal")
        # The value is not masked: the internal model may see it.
        assert CARD in json.dumps(provider.calls[0]["messages"])
        assert shown(_frames(resp.text)) == [
            {
                "notices": [
                    {"action": "route", "message": "Answered by Model llama-internal, as your organisation requires."}
                ]
            }
        ]
        assert [e.action for e in await events(session_factory)] == ["route"]


class TestTheChannels:
    def test_which_channel_a_turn_travels_in(self):
        assert turn_channel({}, "alpha_router_chat") == "chat"
        assert turn_channel({VIA_EXTENSION_BODY_KEY: True}, "alpha_router_chat") == "extension"
        assert turn_channel({}, "gateway") == "gateway"

    async def test_a_gateway_turn_is_masked_in_the_gateway_channel(self, db_session, session_factory, user):
        model = await _model(db_session, "gpt-g")
        await add_rule(db_session, channels=["gateway"])
        body = {"messages": [{"role": "user", "content": f"card {CARD}"}]}
        assert await guard_request(db_session, body, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="gateway") is None  # fmt: skip
        assert body["messages"][0]["content"] == "card [CARD_1]"
        assert body[GUARDRAIL_BODY_KEY]["values"] == {"[CARD_1]": CARD}
        chat_body = {"messages": [{"role": "user", "content": f"card {CARD}"}]}
        await guard_request(db_session, chat_body, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="alpha_router_chat")  # fmt: skip
        assert chat_body["messages"][0]["content"] == f"card {CARD}"

    async def test_what_the_platform_adds_is_the_context_channel(self, db_session, user):
        model = await _model(db_session, "gpt-c")
        await add_rule(db_session, channels=["context"])
        body = {"messages": [{"role": "user", "content": "what do you remember?"}]}
        messages = [
            {"role": "system", "content": f"Memory: the user's card is {CARD}."},
            {"role": "user", "content": "what do you remember?"},
        ]
        out, refusal = await guard_context(db_session, body, messages, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="alpha_router_chat")  # fmt: skip
        assert refusal is None
        assert out[0]["content"] == "Memory: the user's card is [CARD_1]."
        assert out[1] == messages[1]

    async def test_a_block_in_the_context_ends_the_turn_with_its_message(self, db_session, user):
        model = await _model(db_session, "gpt-d")
        await add_rule(db_session, channels=["context"], action="block", user_message="Memory holds a card.")
        body = {"messages": [{"role": "user", "content": "hi"}]}
        messages = [{"role": "system", "content": f"Memory: {CARD}"}, {"role": "user", "content": "hi"}]
        _, refusal = await guard_context(db_session, body, messages, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="alpha_router_chat")  # fmt: skip
        assert refusal == "Memory holds a card."

    async def test_a_masked_turn_keeps_numbering_across_both_checks(self, db_session, user):
        model = await _model(db_session, "gpt-e")
        await add_rule(db_session)
        other = "4111111111111111"
        body = {"messages": [{"role": "user", "content": f"card {CARD}"}]}
        await guard_request(db_session, body, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="alpha_router_chat")  # fmt: skip
        messages = [{"role": "system", "content": f"Memory: {other} and {CARD}"}, *body["messages"]]
        out, _ = await guard_context(db_session, body, messages, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="alpha_router_chat")  # fmt: skip
        assert out[0]["content"] == "Memory: [CARD_2] and [CARD_1]"
        assert body[GUARDRAIL_BODY_KEY]["values"] == {"[CARD_1]": CARD, "[CARD_2]": other}


class TestWhatComesBack:
    async def test_a_value_the_platform_added_is_never_given_back(self, db_session, user):
        model = await _model(db_session, "gpt-h")
        await add_rule(db_session)
        other = "4111111111111111"
        body = {"messages": [{"role": "user", "content": f"card {CARD}; repeat [CARD_2]"}]}
        await guard_request(db_session, body, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="alpha_router_chat")  # fmt: skip
        messages = [{"role": "system", "content": f"Agent secret: {other}"}, *body["messages"]]
        await guard_context(db_session, body, messages, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="alpha_router_chat")  # fmt: skip
        values, _ = await guardrail_reply_state(db_session, body)
        assert values == {"[CARD_1]": CARD}


class TestARouteThatCannotBeTaken:
    async def test_a_model_pinned_for_shared_pages_is_not_swapped(self, db_session, user):
        model = await _model(db_session, "gpt-p")
        internal = await _model(db_session, "llama-p")
        await add_rule(db_session, action="route", route_model_id=internal.id)
        body = {"messages": [{"role": "user", "content": f"card {CARD}"}], MODEL_PINNED_BODY_KEY: True}
        with pytest.raises(HTTPException) as raised:
            await guard_request(db_session, body, ai_model=model, user_id=user.id, alpha_router_api_key_id=None, source="alpha_router_chat")  # fmt: skip
        assert raised.value.status_code == 422

    async def test_a_turn_already_on_the_chosen_model_still_says_so(self, client, db_session, turn, provider):
        await add_rule(
            db_session,
            action="route",
            route_model_id=turn.model.id,
            user_message="Answered by {model}.",
        )
        provider.reply(_text("ok", "stop"))
        resp = await client.post("/api/chat/completions", json=ask(turn.model, f"card {CARD}"), headers=turn.headers)
        assert resp.status_code == 200, resp.text
        assert len(shown(_frames(resp.text))) == 1


class TestTheEndOfAReply:
    async def test_words_held_back_come_before_the_finish(self, client, db_session, turn, provider):
        await add_rule(db_session)
        provider.reply(_text("Charged [CARD_1], see [ref"), _text("", "stop"))
        resp = await client.post("/api/chat/completions", json=ask(turn.model, f"card {CARD}"), headers=turn.headers)
        frames = [f for f in _frames(resp.text) if isinstance(f, dict) and f.get("choices")]
        assert words(frames) == f"Charged {CARD}, see [ref"
        finish = next(i for i, f in enumerate(frames) if f["choices"][0].get("finish_reason"))
        assert words(frames[: finish + 1]) == f"Charged {CARD}, see [ref"


class TestARefusedTurnInTheChat:
    async def test_it_is_kept_with_the_value_hidden_and_never_sent_again(self, client, db_session, turn, provider):
        await add_rule(db_session, action="block", user_message="Card numbers may not be sent to AI models.")
        resp = await client.post(
            "/api/chat/completions",
            json=ask(
                turn.model,
                f"refund {CARD}",
                chat_session_id="r1",
                persist_chat=True,
                user_message={"role": "user", "content": f"refund {CARD}", "clientMessageId": "u1"},
                assistant_client_message_id="a1",
            ),
            headers=turn.headers,
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["persisted"] is True and detail["user_content"] == "refund 603…453"
        rows = (
            (
                await db_session.execute(
                    select(ChatMessage).where(ChatMessage.session_id == "r1").order_by(ChatMessage.sequence)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await db_session.refresh(row)
        question, refusal = rows
        assert question.content == "refund 603…453" and question.meta["guardrailHeldBack"] is True
        assert CARD not in json.dumps([r.content for r in rows])
        assert refusal.content == "" and refusal.meta["guardrailBlocked"] == {
            "message": "Card numbers may not be sent to AI models."
        }
        assert refusal.meta["streaming"] is False
        # The next turn goes on: the refused question is not read back into its history.
        provider.reply(_text("Hello.", "stop"))
        resp = await client.post(
            "/api/chat/completions",
            json=ask(
                turn.model,
                "hello",
                chat_session_id="r1",
                persist_chat=True,
                history_from_sequence=3,
                user_message={"role": "user", "content": "hello", "clientMessageId": "u2"},
                assistant_client_message_id="a2",
            ),
            headers=turn.headers,
        )
        assert resp.status_code == 200, resp.text
        assert "603" not in json.dumps(provider.calls[0]["messages"])

    async def test_a_client_rewriting_the_chat_cannot_put_the_value_back(self, db_session, user):
        from app.services.user_chat_storage_service import replace_session_messages

        await create_chat_session(db_session, user.id, {"id": "r2", "title": "t"})
        await db_session.commit()
        row = ChatMessage(id="m1", session_id="r2", user_id=user.id, role="user", content="refund 603…453", sequence=1,
                          client_message_id="u1", meta={"guardrailHeldBack": True})  # fmt: skip
        db_session.add(row)
        await db_session.commit()
        await replace_session_messages(
            db_session, user.id, "r2", [{"role": "user", "content": f"refund {CARD}", "clientMessageId": "u1"}]
        )
        await db_session.commit()
        kept = (await db_session.execute(select(ChatMessage).where(ChatMessage.session_id == "r2"))).scalar_one()
        assert kept.content == "refund 603…453" and kept.meta["guardrailHeldBack"] is True

    async def test_a_refusal_of_what_the_platform_added_is_shown_in_the_chat(
        self, client, db_session, turn, provider, monkeypatch
    ):
        from app.services import chat_turn_context

        async def refused(db, body, messages, **kwargs):
            return messages, "Memory holds a card."

        monkeypatch.setattr(chat_turn_context, "guard_context", refused)
        resp = await client.post(
            "/api/chat/completions",
            json=ask(
                turn.model,
                "what do you remember?",
                chat_session_id="r3",
                persist_chat=True,
                user_message={"role": "user", "content": "what do you remember?", "clientMessageId": "u3"},
                assistant_client_message_id="a3",
            ),
            headers=turn.headers,
        )
        assert resp.status_code == 200
        assert shown(_frames(resp.text)) == [{"blocked": {"message": "Memory holds a card.", "persisted": True}}]
        assert provider.calls == []
        rows = (
            (
                await db_session.execute(
                    select(ChatMessage).where(ChatMessage.session_id == "r3").order_by(ChatMessage.sequence)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await db_session.refresh(row)
        question, refusal = rows
        assert question.content == "what do you remember?" and not question.meta.get("guardrailHeldBack")
        assert refusal.meta["guardrailBlocked"] == {"message": "Memory holds a card."}
