"""Guardrails' decisions: which rules apply, what wins, what is masked, given back and recorded."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.models.guardrail import GuardrailEvent, GuardrailPattern, GuardrailRule, GuardrailRuleAssignment
from app.services import guardrail_policy
from app.services.guardrail_policy import (
    Destination,
    EventContext,
    GuardrailEngineError,
    GuardrailSettings,
    Masker,
    ReplyRestorer,
    Segment,
    bump_policy_version,
    inspect,
    mask_messages,
    mask_text,
    message_segments,
    restore_text,
    save_settings,
)

CARD = "6037991899123453"
PUBLIC = Destination(label="OpenRouter · GPT", trust="public", connection_id=None)
INTERNAL = Destination(label="Ollama · Llama", trust="internal")


async def rule(db, **fields) -> GuardrailRule:
    values = {
        "name": "Rule",
        "mode": "enforce",
        "position": 0,
        "patterns_json": json.dumps(["lib:bank_card"]),
        "match_mode": "any",
        "min_matches": 1,
        "channels_json": json.dumps(["chat", "attachments"]),
        "destinations_json": "[]",
        "action": "redact",
        "access_type": "public",
        "acl_version": 0,
        "version": 1,
    }
    for key in ("patterns", "channels", "destinations"):
        if key in fields:
            values[f"{key}_json"] = json.dumps(fields.pop(key))
    values.update(fields)
    row = GuardrailRule(**values)
    db.add(row)
    await bump_policy_version(db)
    await db.commit()
    await db.refresh(row)
    return row


def chat(text: str) -> list[Segment]:
    return message_segments([{"role": "user", "content": text}], channel="chat")


async def check(db, session_factory, segments, *, user=None, destination=PUBLIC, **kwargs):
    ctx = EventContext(user_id=user.id if user else None, username=user.username if user else None, source="t")
    return await inspect(db, segments, destination=destination, ctx=ctx, session_factory=session_factory, **kwargs)


async def events(session_factory) -> list[GuardrailEvent]:
    async with session_factory() as db:
        return list((await db.execute(select(GuardrailEvent).order_by(GuardrailEvent.id))).scalars().all())


class TestNothingUntilAnAdministratorSaysSo:
    async def test_no_rules_no_change_and_no_record(self, db_session, session_factory, user):
        verdict = await check(db_session, session_factory, chat(f"card {CARD}"), user=user)
        assert verdict.action is None
        assert await events(session_factory) == []

    async def test_a_rule_that_is_off_does_nothing(self, db_session, session_factory, user):
        await rule(db_session, mode="off")
        assert (await check(db_session, session_factory, chat(f"card {CARD}"), user=user)).action is None


class TestWhatARuleDoes:
    async def test_redact_masks_the_value_and_records_only_a_hint(self, db_session, session_factory, user):
        await rule(db_session, name="Cards", user_message="Cards were masked.")
        messages = [{"role": "user", "content": f"pay {CARD} and again {CARD}"}]
        verdict = await check(db_session, session_factory, message_segments(messages, channel="chat"), user=user)
        assert verdict.action == "redact"
        masker = Masker()
        masked = mask_messages(messages, verdict.to_mask, masker)
        assert masked[0]["content"] == "pay [CARD_1] and again [CARD_1]"
        assert messages[0]["content"] == f"pay {CARD} and again {CARD}"  # the original is not changed
        assert masker.values == {"[CARD_1]": CARD}
        assert verdict.notices() == ["Cards were masked."]
        (event,) = await events(session_factory)
        assert (event.action, event.channel, event.match_count, event.username) == ("redact", "chat", 2, user.username)
        assert CARD not in (event.findings_json or "")
        assert json.loads(event.findings_json)[0]["hints"] == ["603…453", "603…453"]

    async def test_block_outranks_redact_and_the_outranked_rule_is_recorded_as_would_have(
        self, db_session, session_factory, user
    ):
        await rule(db_session, name="Mask cards", action="redact", position=1)
        await rule(db_session, name="Stop cards", action="block", position=2, user_message="No cards, please.")
        verdict = await check(db_session, session_factory, chat(f"card {CARD}"), user=user)
        assert verdict.blocked and verdict.deciding.rule.name == "Stop cards"
        assert verdict.notices() == ["No cards, please."]
        rows = {e.rule_name: e for e in await events(session_factory)}
        assert rows["Stop cards"].action == "block"
        assert (rows["Mask cards"].action, rows["Mask cards"].intended_action) == ("monitor", "redact")

    async def test_monitor_changes_nothing_but_is_recorded(self, db_session, session_factory, user):
        await rule(db_session, mode="monitor", action="block")
        verdict = await check(db_session, session_factory, chat(f"card {CARD}"), user=user)
        assert verdict.action is None
        (event,) = await events(session_factory)
        assert (event.action, event.intended_action) == ("monitor", "block")

    async def test_route_names_the_model_and_is_not_routed_again_to_it(self, db_session, session_factory, user):
        from tests.test_extension_browser_tools import _model

        model = await _model(db_session, "llama-internal")
        await rule(db_session, action="route", route_model_id=model.id, user_message="Sent to {model}.")
        verdict = await check(db_session, session_factory, chat(f"card {CARD}"), user=user)
        assert verdict.action == "route" and verdict.deciding.rule.route_model_id == model.id
        assert verdict.notices("Llama") == ["Sent to Llama."]
        again = await check(db_session, session_factory, chat(f"card {CARD}"), user=user, ignore_route_to=model.id)
        assert again.action is None


class TestWhereARuleLooks:
    async def test_attached_files_are_a_channel_of_their_own(self, db_session, session_factory, user):
        await rule(db_session, channels=["attachments"])
        typed = chat(f"my card {CARD}")
        assert (await check(db_session, session_factory, typed, user=user)).action is None
        attached = chat(f"summarise this\n\n--- list.csv ---\n{CARD}")
        verdict = await check(db_session, session_factory, attached, user=user)
        assert verdict.action == "redact" and verdict.to_mask[0][0].channel == "attachments"

    async def test_a_rule_watches_only_the_destinations_it_names(self, db_session, session_factory, user):
        await rule(db_session, destinations=["public"])
        assert (await check(db_session, session_factory, chat(CARD), user=user, destination=INTERNAL)).action is None
        assert (await check(db_session, session_factory, chat(CARD), user=user, destination=PUBLIC)).action == "redact"

    async def test_all_patterns_and_at_least_n_finds(self, db_session, session_factory, user):
        await rule(db_session, patterns=["lib:bank_card", "lib:email"], match_mode="all", min_matches=3)
        assert (await check(db_session, session_factory, chat(f"{CARD} {CARD} {CARD}"), user=user)).action is None
        assert (await check(db_session, session_factory, chat(f"{CARD} a@b.com"), user=user)).action is None
        verdict = await check(db_session, session_factory, chat(f"{CARD} {CARD} a@b.com"), user=user)
        assert verdict.action == "redact"

    async def test_a_rule_naming_a_pattern_that_is_gone_is_not_applied(self, db_session, session_factory, user):
        await rule(db_session, patterns=["custom:999"])
        assert (await check(db_session, session_factory, chat(CARD), user=user)).action is None

    async def test_an_administrators_pattern(self, db_session, session_factory, user):
        pattern = GuardrailPattern(
            name="Contract",
            kind="regex",
            expression=r"\bCNT-\d{4}\b",
            case_sensitive=False,
            normalize=True,
            context_window=50,
            redact_label="CONTRACT",
            version=1,
        )
        db_session.add(pattern)
        await db_session.flush()
        await rule(db_session, patterns=[f"custom:{pattern.id}"])
        messages = [{"role": "user", "content": "see CNT-۲۰۲۵"}]
        verdict = await check(db_session, session_factory, message_segments(messages, channel="chat"), user=user)
        assert mask_messages(messages, verdict.to_mask, Masker())[0]["content"] == "see [CONTRACT_1]"


class TestWhoARuleAppliesTo:
    async def test_an_exception_for_one_person(self, db_session, session_factory, user):
        row = await rule(db_session)
        db_session.add(GuardrailRuleAssignment(rule_id=row.id, user_id=user.id, effect="deny"))
        await bump_policy_version(db_session)
        await db_session.commit()
        assert (await check(db_session, session_factory, chat(CARD), user=user)).action is None

    async def test_a_rule_for_named_people_only(self, db_session, session_factory, user, admin):
        row = await rule(db_session, access_type="private")
        db_session.add(GuardrailRuleAssignment(rule_id=row.id, user_id=admin.id, effect="allow"))
        await bump_policy_version(db_session)
        await db_session.commit()
        assert (await check(db_session, session_factory, chat(CARD), user=user)).action is None
        assert (await check(db_session, session_factory, chat(CARD), user=admin)).action == "redact"

    async def test_no_implicit_exception_for_a_super_admin(self, db_session, session_factory, admin):
        await rule(db_session, action="block")
        assert (await check(db_session, session_factory, chat(CARD), user=admin)).blocked


class TestWhenTheTextCannotBeChecked:
    async def test_fail_closed_stops_it_and_says_why(self, db_session, session_factory, user, monkeypatch):
        await rule(db_session)

        def broken(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(guardrail_policy, "decide", broken)
        with pytest.raises(GuardrailEngineError):
            await check(db_session, session_factory, chat(CARD), user=user)
        (event,) = await events(session_factory)
        assert event.action == "engine_error" and "boom" in event.message

    async def test_fail_open_lets_it_through(self, db_session, session_factory, user, monkeypatch):
        await rule(db_session)
        await save_settings(db_session, GuardrailSettings(fail_closed=False))
        await db_session.commit()
        monkeypatch.setattr(guardrail_policy, "decide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert (await check(db_session, session_factory, chat(CARD), user=user)).action is None


class TestMaskingAndGivingBack:
    def test_content_parts_and_a_query(self):
        masker = Masker()
        segment = Segment("chat", f"card {CARD}", message=0, part=1)
        from app.services.guardrail_patterns import LIBRARY_BY_REF, compile_pattern

        (match,) = compile_pattern(LIBRARY_BY_REF["lib:bank_card"]).find(segment.text)
        messages = [{"role": "user", "content": [{"type": "image_url"}, {"type": "text", "text": segment.text}]}]
        out = mask_messages(messages, [(segment, match, "CARD")], masker)
        assert out[0]["content"][1]["text"] == "card [CARD_1]"
        query = Segment("web_search", CARD)
        (m2,) = compile_pattern(LIBRARY_BY_REF["lib:bank_card"]).find(query.text)
        assert mask_text(query.text, [(query, m2, "CARD")], masker) == "[CARD_1]"

    def test_overlapping_finds_are_masked_as_one(self):
        masker = Masker()
        text = "Project Falcon-7731 is late"
        assert masker.mask(text, [(0, 14, "WORD"), (8, 19, "CODE")]) == "[WORD_1] is late"
        assert masker.values == {"[WORD_1]": "Project Falcon-7731"}
        assert Masker().mask("ab cd", [(0, 2, "A"), (0, 5, "B"), (3, 5, "C")]) == "[B_1]"

    def test_a_reply_gets_its_values_back_even_cut_between_chunks(self):
        restorer = ReplyRestorer({"[CARD_1]": CARD, "[EMAIL_2]": "a@b.com"})
        out = restorer.feed("Your card [CA") + restorer.feed("RD_1] and [EMA") + restorer.feed("IL_2]. [note")
        out += restorer.flush()
        assert out == f"Your card {CARD} and a@b.com. [note"
        assert restore_text("[UNKNOWN_1] stays", {"[CARD_1]": CARD}) == "[UNKNOWN_1] stays"
