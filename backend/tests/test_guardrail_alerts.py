"""Guardrails: alerts when a rule blocks, and how long events are kept."""

from __future__ import annotations

import asyncio
import datetime

from sqlalchemy import select

from app.models.guardrail import GuardrailEvent
from app.services import guardrail_alerts
from app.services.guardrail_alerts import alert_blocked, alert_text, purge_expired_events
from app.services.guardrail_policy import GuardrailSettings, save_settings


def event(**fields) -> GuardrailEvent:
    values = {
        "rule_id": 7,
        "rule_name": "API keys",
        "rule_version": 2,
        "action": "block",
        "channel": "chat",
        "destination": "OpenRouter · GPT",
        "destination_trust": "public",
        "username": "sara",
        "match_count": 1,
        "findings_json": '[{"ref": "lib:openai_key", "name": "OpenAI or Anthropic API key", "count": 1, "hints": ["sk-…123"]}]',
    }
    values.update(fields)
    return GuardrailEvent(**values)


async def test_an_alert_says_what_happened_and_never_the_value():
    subject, body = alert_text(event())
    assert subject == "Guardrails blocked a request: API keys"
    assert "Who: sara" in body and "OpenAI or Anthropic API key ×1" in body and "sk-" not in body


async def test_alerts_go_to_the_chosen_addresses_once_per_rule_per_interval(db_session, session_factory, monkeypatch):
    await save_settings(db_session, GuardrailSettings(alert_emails=["sec@x.io", "ciso@x.io"]))
    await db_session.commit()
    sent: list[dict] = []

    async def send_email(db, **kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("app.services.smtp_service.send_email", send_email)
    await alert_blocked([event(), event(action="redact", rule_id=8)], session_factory)
    await alert_blocked([event()], session_factory)  # the same rule again, within the interval
    await asyncio.gather(*list(guardrail_alerts._pending))
    assert [(m["to_address"], m["cc"]) for m in sent] == [("sec@x.io", ["ciso@x.io"])]


async def test_no_addresses_no_alert(db_session, session_factory, monkeypatch):
    sent: list[dict] = []

    async def send_email(db, **kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("app.services.smtp_service.send_email", send_email)
    await alert_blocked([event()], session_factory)
    await asyncio.gather(*list(guardrail_alerts._pending))
    assert sent == []


async def test_events_past_the_window_are_deleted(db_session):
    await save_settings(db_session, GuardrailSettings(event_retention_days=30))
    old = datetime.datetime.utcnow() - datetime.timedelta(days=31)
    db_session.add_all([event(created_at=old, rule_id=None), event(created_at=old, rule_id=None), event(rule_id=None)])
    await db_session.commit()
    assert await purge_expired_events(db_session) == {"events_deleted": 2, "retention_days": 30}
    assert len((await db_session.execute(select(GuardrailEvent))).scalars().all()) == 1
