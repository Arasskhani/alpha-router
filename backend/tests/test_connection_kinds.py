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
