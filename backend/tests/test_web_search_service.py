"""The search chain: services in priority order, the DuckDuckGo fallback, and what each attempt cost."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.connection import Connection
from app.models.cost_accounting import UsageEvent
from app.services import web_search_service as service
from app.services.secret_crypto import encrypt_secret
from app.services.web_search_providers import SearchResult, WebSearchError
from app.services.web_search_service import (
    WebSearchSettings,
    WebSearchUnavailable,
    save_web_search_settings,
    search_plan,
    search_web,
    web_search_availability,
)


@pytest.fixture(autouse=True)
def _sessions(monkeypatch, session_factory):
    for target in (
        "app.database.AsyncSessionLocal",
        "app.services.metered_usage_service.AsyncSessionLocal",
        "app.services.usage_logging_service.AsyncSessionLocal",
        "app.services.budget_reservation_service.AsyncSessionLocal",
    ):
        monkeypatch.setattr(target, session_factory, raising=False)


async def _search_connection(db, name, provider, *, priority=100, price=0.0, active=True, key="key") -> Connection:
    row = Connection(
        name=name,
        kind="web_search",
        provider_type=provider,
        api_key_encrypted=encrypt_secret(key),
        is_active=active,
        priority=priority,
        price_per_request_usd=price,
        sync_enabled=False,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _answers(by_provider: dict[str, object]):
    """A run_search stand-in: per provider, results to return or an error to raise."""
    asked: list[tuple[str, str]] = []

    async def fake(target, query, limit, **kwargs):
        asked.append((target.provider, target.api_key))
        outcome = by_provider[target.provider]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return fake, asked


ROW = [SearchResult(title="T", url="https://t.example", snippet="s")]


class TestThePlan:
    async def test_active_connections_by_priority_then_duckduckgo(self, db_session):
        await _search_connection(db_session, "Tavily", "tavily", priority=20)
        await _search_connection(db_session, "Brave", "brave", priority=10)
        await _search_connection(db_session, "Off", "google_pse", priority=1, active=False)
        steps = await search_plan(db_session)
        assert [(s.label, s.target.provider) for s in steps] == [
            ("Brave", "brave"),
            ("Tavily", "tavily"),
            ("DuckDuckGo", "duckduckgo"),
        ]
        assert steps[0].target.api_key == "key"

    async def test_without_the_fallback_and_without_connections_web_search_is_off(self, db_session):
        assert await web_search_availability(db_session) is None
        await save_web_search_settings(db_session, WebSearchSettings(duckduckgo_fallback=False))
        await db_session.commit()
        assert await search_plan(db_session) == []
        assert "Connections" in (await web_search_availability(db_session) or "")

    async def test_a_model_connection_is_never_asked(self, db_session):
        db_session.add(Connection(name="OpenAI", provider_type="openai", api_key_encrypted=encrypt_secret("sk")))
        await db_session.commit()
        await save_web_search_settings(db_session, WebSearchSettings(duckduckgo_fallback=False))
        await db_session.commit()
        assert await search_plan(db_session) == []


class TestTheChain:
    async def test_the_first_that_answers_is_used_and_each_attempt_is_recorded(self, db_session, monkeypatch, user):
        brave = await _search_connection(db_session, "Brave", "brave", priority=1, price=0.003)
        tavily = await _search_connection(db_session, "Tavily", "tavily", priority=2, price=0.008)
        fake, asked = _answers({"brave": WebSearchError("quota", "Brave's quota is used up."), "tavily": ROW})
        monkeypatch.setattr(service, "run_search", fake)
        outcome = await search_web("q", 5, user_id=user.id, username=user.username, reserve_budget=False)
        assert outcome.label == "Tavily"
        assert outcome.results == ROW
        assert [(f.label, f.code) for f in outcome.failures] == [("Brave", "quota")]
        assert [p for p, _ in asked] == ["brave", "tavily"]
        events = (await db_session.execute(select(UsageEvent).order_by(UsageEvent.started_at))).scalars().all()
        by_connection = {e.connection_id: e for e in events}
        assert by_connection[brave.id].status == "failed"
        assert "quota" in (by_connection[brave.id].error_message or "")
        assert by_connection[tavily.id].service_type == "web_search"
        assert float(by_connection[tavily.id].final_cost_usd) == pytest.approx(0.008)

    async def test_when_nobody_answers_every_reason_is_given(self, db_session, monkeypatch):
        await _search_connection(db_session, "Brave", "brave", priority=1)
        fake, _ = _answers(
            {
                "brave": WebSearchError("auth", "Brave Search refused the API key."),
                "duckduckgo": WebSearchError("rate_limited", "DuckDuckGo is rate limiting."),
            }
        )
        monkeypatch.setattr(service, "run_search", fake)
        with pytest.raises(WebSearchUnavailable) as raised:
            await search_web("q", 5)
        assert raised.value.code == "auth"
        assert "refused the API key" in raised.value.message and "rate limiting" in raised.value.message

    async def test_nothing_set_up_is_said_as_such(self, db_session, monkeypatch):
        await save_web_search_settings(db_session, WebSearchSettings(duckduckgo_fallback=False))
        await db_session.commit()
        with pytest.raises(WebSearchUnavailable) as raised:
            await search_web("q", 5)
        assert raised.value.code == "not_configured"
        assert "Connections" in raised.value.message

    async def test_a_free_search_costs_nothing(self, db_session, monkeypatch, user):
        fake, _ = _answers({"duckduckgo": ROW})
        monkeypatch.setattr(service, "run_search", fake)
        await search_web("q", 5, user_id=user.id, reserve_budget=False)
        [event] = (await db_session.execute(select(UsageEvent))).scalars().all()
        assert event.provider_type == "duckduckgo"
        assert not float(event.final_cost_usd or 0)
