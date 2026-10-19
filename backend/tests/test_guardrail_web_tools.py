"""Guardrails on what Web Search sends to a search service and the addresses Web Fetch reads."""

from __future__ import annotations

import json

import pytest

from app.models.connection import Connection
from app.models.guardrail import GuardrailPattern, GuardrailRule
from app.services import chat_tools_service
from app.services import web_search_service as service
from app.services.chat_web_tools import ToolCall, WebToolLoop
from app.services.guardrail_policy import GuardrailBlocked, bump_policy_version
from app.services.secret_crypto import encrypt_secret
from app.services.web_search_providers import SearchResult
from app.services.web_search_service import (
    WebSearchSettings,
    WebSearchUnavailable,
    save_web_search_settings,
    search_web,
)

CARD = "6037991899123453"
ROW = [SearchResult(title="T", url="https://t.example", snippet="s")]


@pytest.fixture(autouse=True)
def _sessions(monkeypatch, session_factory):
    for target in (
        "app.database.AsyncSessionLocal",
        "app.services.metered_usage_service.AsyncSessionLocal",
        "app.services.usage_logging_service.AsyncSessionLocal",
        "app.services.budget_reservation_service.AsyncSessionLocal",
    ):
        monkeypatch.setattr(target, session_factory, raising=False)


async def add_rule(db, **fields) -> GuardrailRule:
    values = {
        "name": "Searches",
        "mode": "enforce",
        "position": 1,
        "patterns_json": json.dumps(["lib:bank_card"]),
        "match_mode": "any",
        "min_matches": 1,
        "channels_json": json.dumps(["web_search"]),
        "destinations_json": json.dumps(["public"]),
        "action": "block",
        "access_type": "public",
        "acl_version": 0,
        "version": 1,
        "user_message": "Card numbers are not searched for outside.",
    }
    values.update(fields)
    row = GuardrailRule(**values)
    db.add(row)
    await bump_policy_version(db)
    await db.commit()
    return row


async def search_connection(db, name, provider, *, priority, trust) -> None:
    db.add(
        Connection(
            name=name,
            kind="web_search",
            provider_type=provider,
            api_key_encrypted=encrypt_secret("key"),
            base_url="https://searx.internal" if provider == "searxng" else None,
            is_active=True,
            priority=priority,
            sync_enabled=False,
            trust_level=trust,
        )
    )
    await db.commit()


def fake_search(monkeypatch) -> list[tuple[str, str]]:
    asked: list[tuple[str, str]] = []

    async def fake(target, query, limit, **kwargs):
        asked.append((target.provider, query))
        return ROW

    monkeypatch.setattr(service, "run_search", fake)
    return asked


class TestSearch:
    async def test_a_query_skips_the_services_the_rule_watches(self, db_session, monkeypatch, user):
        await search_connection(db_session, "Brave", "brave", priority=1, trust="public")
        await search_connection(db_session, "Our SearXNG", "searxng", priority=2, trust="internal")
        await add_rule(db_session)
        asked = fake_search(monkeypatch)
        outcome = await search_web(f"who owns card {CARD}", 5, user_id=user.id, reserve_budget=False)
        assert asked == [("searxng", f"who owns card {CARD}")]
        assert outcome.label == "Our SearXNG"
        assert [(f.label, f.code, f.message) for f in outcome.failures] == [
            ("Brave", "blocked", "Card numbers are not searched for outside.")
        ]

    async def test_a_masked_query(self, db_session, monkeypatch, user):
        await search_connection(db_session, "Brave", "brave", priority=1, trust="public")
        await add_rule(db_session, action="redact")
        asked = fake_search(monkeypatch)
        await search_web(f"card {CARD} owner", 5, user_id=user.id, reserve_budget=False)
        assert asked == [("brave", "card [CARD_1] owner")]

    async def test_when_every_service_is_ruled_out_the_model_is_told_why(self, db_session, monkeypatch, user):
        await save_web_search_settings(db_session, WebSearchSettings(duckduckgo_fallback=True))
        await db_session.commit()
        await add_rule(db_session)
        asked = fake_search(monkeypatch)
        with pytest.raises(WebSearchUnavailable) as raised:
            await search_web(CARD, 5, user_id=user.id, reserve_budget=False)
        assert asked == []
        assert "Card numbers are not searched for outside." in raised.value.message

    async def test_an_ordinary_query_goes_as_before(self, db_session, monkeypatch, user):
        await search_connection(db_session, "Brave", "brave", priority=1, trust="public")
        await add_rule(db_session)
        asked = fake_search(monkeypatch)
        await search_web("weather in Tehran", 5, user_id=user.id, reserve_budget=False)
        assert asked == [("brave", "weather in Tehran")]


class TestFetch:
    async def test_an_internal_address_is_not_read_and_the_model_is_told(self, db_session, monkeypatch, user):
        pattern = GuardrailPattern(
            name="Intranet",
            kind="domains",
            entries_json=json.dumps(["intranet.example"]),
            case_sensitive=False,
            normalize=True,
            context_window=50,
            redact_label="HOST",
            version=1,
        )
        db_session.add(pattern)
        await db_session.flush()
        await add_rule(
            db_session,
            patterns_json=json.dumps([f"custom:{pattern.id}"]),
            channels_json=json.dumps(["web_fetch"]),
            user_message="Intranet pages are not read for AI models.",
        )
        read: list[str] = []

        async def fetch_page(url, **kwargs):
            read.append(url)
            raise AssertionError("must not be fetched")

        monkeypatch.setattr(chat_tools_service, "fetch_page", fetch_page)
        with pytest.raises(GuardrailBlocked, match="Intranet pages are not read"):
            await chat_tools_service.fetch_url_text("https://wiki.intranet.example/hr", user_id=user.id)
        loop = WebToolLoop(search=False, fetch=True, user_id=user.id, readable={"https://wiki.intranet.example/hr"})
        text = await loop.run(ToolCall("f1", "web_fetch", json.dumps({"url": "https://wiki.intranet.example/hr"})))
        assert "Intranet pages are not read for AI models" in text
        assert read == []
