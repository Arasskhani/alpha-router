"""Admin: the Web Search fallback switch, the services a search asks, and the Test."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api import admin_web_search
from app.config import get_settings
from app.core.security import create_access_token
from app.models.connection import Connection
from app.models.security import SecurityAuditEvent
from app.services.secret_crypto import encrypt_secret
from app.services.web_search_providers import SearchResult, WebSearchError

CSRF = "csrf-token"
BASE = "/api/admin/web-search"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


def _sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


def _fake_search(monkeypatch, outcome):
    seen = []

    async def fake(target, query, limit, **kwargs):
        seen.append(target)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(admin_web_search, "run_search", fake)
    return seen


async def test_the_overview_and_the_fallback_switch(client, db_session, admin):
    headers = _sign_in(client, admin)
    db_session.add(
        Connection(name="Brave", kind="web_search", provider_type="brave", api_key_encrypted=encrypt_secret("k"))
    )
    await db_session.commit()
    data = (await client.get(BASE, headers=headers)).json()
    assert data["settings"] == {"duckduckgo_fallback": True}
    assert [step["label"] for step in data["plan"]] == ["Brave", "DuckDuckGo"]
    resp = await client.put(BASE, json={"duckduckgo_fallback": False}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert [step["label"] for step in resp.json()["plan"]] == ["Brave"]
    audit = (
        await db_session.execute(
            select(SecurityAuditEvent).where(SecurityAuditEvent.action == "web_search_settings_updated")
        )
    ).scalar_one()
    assert audit.actor_username == admin.username


async def test_a_plain_user_reaches_none_of_it(client, user):
    headers = _sign_in(client, user)
    assert (await client.get(BASE, headers=headers)).status_code == 403
    assert (await client.post(f"{BASE}/test", json={"provider_type": "duckduckgo"}, headers=headers)).status_code == 403


async def test_a_draft_is_tried_with_what_the_form_holds(client, admin, monkeypatch):
    seen = _fake_search(monkeypatch, [SearchResult(title="T", url="https://t.example", snippet="s")])
    headers = _sign_in(client, admin)
    body = {"provider_type": "google_pse", "api_key": "AIza", "config": {"cx": "abc"}, "query": "hello"}
    resp = await client.post(f"{BASE}/test", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True and data["count"] == 1 and data["query"] == "hello"
    assert (seen[0].provider, seen[0].api_key, seen[0].config) == ("google_pse", "AIza", {"cx": "abc"})


async def test_a_saved_connection_is_tried_with_its_stored_key(client, db_session, admin, monkeypatch):
    seen = _fake_search(monkeypatch, WebSearchError("auth", "Brave Search refused the API key."))
    conn = Connection(
        name="Brave", kind="web_search", provider_type="brave", api_key_encrypted=encrypt_secret("stored")
    )
    db_session.add(conn)
    await db_session.commit()
    headers = _sign_in(client, admin)
    resp = await client.post(f"{BASE}/test", json={"connection_id": conn.id}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is False
    assert resp.json()["error"]["code"] == "auth"
    assert seen[0].api_key == "stored"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"provider_type": "openai", "api_key": "sk"}, 400),
        ({"provider_type": "brave"}, 400),
        ({"provider_type": "google_pse", "api_key": "k"}, 400),
        ({"connection_id": 999}, 404),
    ],
)
async def test_what_cannot_be_tried_is_refused(client, admin, monkeypatch, body, status):
    _fake_search(monkeypatch, [])
    headers = _sign_in(client, admin)
    assert (await client.post(f"{BASE}/test", json=body, headers=headers)).status_code == status


async def test_a_model_connection_is_not_a_search_to_try(client, db_session, admin, monkeypatch):
    _fake_search(monkeypatch, [])
    conn = Connection(name="OpenAI", provider_type="openai", api_key_encrypted=encrypt_secret("sk"))
    db_session.add(conn)
    await db_session.commit()
    headers = _sign_in(client, admin)
    assert (await client.post(f"{BASE}/test", json={"connection_id": conn.id}, headers=headers)).status_code == 404
