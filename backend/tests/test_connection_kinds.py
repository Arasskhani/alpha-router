"""Connection kinds: a web search connection is never taken for a model provider."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.core.security import create_access_token
from app.models.api_key import AlphaRouterApiKey
from app.models.connection import Connection
from app.services.connection_kinds import kind_mismatch
from app.services.secret_crypto import encrypt_secret

CSRF = "csrf-token"


@pytest.fixture(autouse=True)
def _guards(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


def _sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _connection(db, name: str, provider: str, kind: str = "models") -> Connection:
    row = Connection(name=name, provider_type=provider, kind=kind, api_key_encrypted=encrypt_secret("k-test"))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


class TestTheRules:
    @pytest.mark.parametrize(
        ("kind", "provider", "refused"),
        [
            ("models", "openai", False),
            ("models", "custom", False),
            ("web_search", "brave", False),
            ("web_search", "searxng", False),
            ("web_search", "openai", True),
            ("models", "tavily", True),
            # Gemini's provider id is "google": a model provider, never taken for Google's search.
            ("models", "google", False),
            ("web_search", "google", True),
            ("search", "brave", True),
        ],
    )
    def test_a_provider_belongs_to_one_kind(self, kind, provider, refused):
        assert (kind_mismatch(kind, provider) is not None) is refused


class TestWhereModelsAreChosen:
    async def test_an_api_key_cannot_be_allowed_a_search_connection(self, db_session):
        from app.services.api_key_connection_policy import replace_key_allowed_connections

        search = await _connection(db_session, "Brave", "brave", "web_search")
        key = AlphaRouterApiKey(name="k", key_hash="h", key_prefix="alpha_router_ab", is_active=True)
        db_session.add(key)
        await db_session.flush()
        with pytest.raises(ValueError, match="Unknown connection"):
            await replace_key_allowed_connections(db_session, key, restrict=True, connection_ids=[search.id])

    async def test_the_extension_offers_and_takes_only_model_connections(self, db_session):
        from app.services.extension_settings import (
            ExtensionSettings,
            ExtensionSettingsError,
            _connection_list,
            connection_choices,
        )

        model = await _connection(db_session, "OpenAI", "openai")
        search = await _connection(db_session, "Brave", "brave", "web_search")
        assert [c["id"] for c in await connection_choices(db_session, ExtensionSettings())] == [model.id]
        assert await _connection_list(db_session, [model.id]) == (model.id,)
        with pytest.raises(ExtensionSettingsError, match="does not exist"):
            await _connection_list(db_session, [search.id])

    async def test_the_admin_api_keeps_search_connections_out_of_model_pickers(self, client, db_session, admin):
        model = await _connection(db_session, "OpenAI", "openai")
        search = await _connection(db_session, "Brave", "brave", "web_search")
        headers = _sign_in(client, admin)
        resp = await client.get("/api/admin/api-keys/connection-options", headers=headers)
        assert resp.status_code == 200, resp.text
        assert [item["id"] for item in resp.json()["items"]] == [model.id]
        resp = await client.post(f"/api/admin/connections/{search.id}/sync", headers=headers)
        assert resp.status_code == 400
        assert "no models to sync" in resp.json()["detail"]

    async def test_a_search_connection_alone_is_no_model_provider(self, client, db_session, admin):
        await _connection(db_session, "Brave", "brave", "web_search")
        headers = _sign_in(client, admin)
        resp = await client.get("/api/admin/models", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == [] or resp.json().get("items") == []


class TestTheAdminApi:
    async def test_a_search_connection_is_made_and_listed_with_its_fields(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        body = {
            "name": "Google search",
            "kind": "web_search",
            "provider_type": "google_pse",
            "api_key": "AIza-test-key",
            "config": {"cx": "a1b2c3:xyz", "ignored": "x"},
            "priority": 5,
            "price_per_request_usd": 0.005,
        }
        resp = await client.post("/api/admin/connections", json=body, headers=headers)
        assert resp.status_code == 200, resp.text
        row = await db_session.get(Connection, resp.json()["id"])
        assert (row.kind, row.sync_enabled, row.priority) == ("web_search", False, 5)
        assert row.config_json == '{"cx": "a1b2c3:xyz"}'
        listed = (await client.get("/api/admin/connections", headers=headers)).json()
        assert listed[0]["kind"] == "web_search"
        assert listed[0]["config"] == {"cx": "a1b2c3:xyz"}
        assert listed[0]["price_per_request_usd"] == pytest.approx(0.005)
        changelog = (await client.get(f"/api/admin/connections/{row.id}/changelog", headers=headers)).json()
        assert "Kind" in str(changelog)

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ({"kind": "web_search", "provider_type": "openai", "api_key": "sk-x"}, "web search connection is one of"),
            ({"kind": "models", "provider_type": "tavily", "api_key": "tvly-x"}, "is a web search service"),
            ({"kind": "web_search", "provider_type": "brave", "api_key": ""}, "needs its API key"),
            ({"kind": "web_search", "provider_type": "google_pse", "api_key": "k"}, "search engine id"),
            ({"kind": "web_search", "provider_type": "searxng"}, "address of your SearXNG"),
            ({"kind": "web_search", "provider_type": "brave", "api_key": "k", "priority": 0}, "Priority"),
            ({"kind": "web_search", "provider_type": "brave", "api_key": "k", "price_per_request_usd": -1}, "price"),
        ],
    )
    async def test_a_connection_that_does_not_fit_its_kind_is_refused(self, client, admin, body, message):
        headers = _sign_in(client, admin)
        resp = await client.post("/api/admin/connections", json={"name": "x", **body}, headers=headers)
        assert resp.status_code == 400, resp.text
        assert message in resp.json()["detail"]

    async def test_duckduckgo_takes_no_key(self, client, admin):
        headers = _sign_in(client, admin)
        body = {"name": "DDG", "kind": "web_search", "provider_type": "duckduckgo"}
        resp = await client.post("/api/admin/connections", json=body, headers=headers)
        assert resp.status_code == 200, resp.text

    async def test_a_kind_never_changes_and_a_provider_stays_within_it(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        search = await _connection(db_session, "Brave", "brave", "web_search")
        model = await _connection(db_session, "OpenAI", "openai")
        url = f"/api/admin/connections/{search.id}"
        assert (await client.patch(url, json={"kind": "models"}, headers=headers)).status_code == 400
        assert (await client.patch(url, json={"provider_type": "openai"}, headers=headers)).status_code == 400
        resp = await client.patch(
            f"/api/admin/connections/{model.id}", json={"provider_type": "brave"}, headers=headers
        )
        assert resp.status_code == 400
        resp = await client.patch(f"/api/admin/connections/{model.id}", json={"priority": 3}, headers=headers)
        assert resp.status_code == 400
        resp = await client.patch(url, json={"priority": 7, "price_per_request_usd": 0.01}, headers=headers)
        assert resp.status_code == 200, resp.text
        await db_session.refresh(search)
        assert (search.priority, float(search.price_per_request_usd)) == (7, pytest.approx(0.01))
        # Switching to Google needs its engine id.
        resp = await client.patch(url, json={"provider_type": "google_pse"}, headers=headers)
        assert resp.status_code == 400
        resp = await client.patch(
            url,
            json={"provider_type": "google_pse", "config": {"cx": "abc"}, "api_key": "AIza-google"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        await db_session.refresh(search)
        assert search.config_json == '{"cx": "abc"}'

    async def test_a_key_is_not_carried_to_another_search_service(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        search = await _connection(db_session, "Brave", "brave", "web_search")
        url = f"/api/admin/connections/{search.id}"
        # Brave's key would be sent to Tavily: Tavily's own is asked for.
        resp = await client.patch(url, json={"provider_type": "tavily"}, headers=headers)
        assert resp.status_code == 400, resp.text
        resp = await client.patch(url, json={"provider_type": "tavily", "api_key": "tvly-own"}, headers=headers)
        assert resp.status_code == 200, resp.text
        # The same service keeps its stored key.
        assert (await client.patch(url, json={"priority": 5}, headers=headers)).status_code == 200


class TestATrustLevelBelongsToItsEndpoint:
    async def test_pointing_a_connection_elsewhere_makes_it_public_again(self, client, db_session, admin):
        headers = _sign_in(client, admin)
        conn = await _connection(db_session, "Ours", "openai")
        conn.trust_level = "internal"
        await db_session.commit()
        url = f"/api/admin/connections/{conn.id}"
        assert (await client.patch(url, json={"name": "Ours, renamed"}, headers=headers)).status_code == 200
        await db_session.refresh(conn)
        assert conn.trust_level == "internal"
        assert (await client.patch(url, json={"provider_type": "anthropic"}, headers=headers)).status_code == 200
        await db_session.refresh(conn)
        assert conn.trust_level == "public"
