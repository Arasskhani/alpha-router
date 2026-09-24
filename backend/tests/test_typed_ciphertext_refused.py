"""A stored token typed where a secret goes is refused, and never kept as it is.

``encrypt_secret`` keeps a value that already is valid ciphertext unchanged, so
a record can be saved again without encrypting twice. Applied to a secret typed
into a form, that was a hole: whoever holds a copy of a stored token (a database
backup, an export) could submit it as a connection's API key, an LDAP bind
password or an OIDC client secret. Saved unchanged, it was later decrypted into
the real secret it holds - another connection's key, the SMTP password - and
sent to the server the form names. The SMTP password was closed the same way;
these are the others.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.api.admin import ENCRYPTED_API_KEY_TYPED
from app.api.authentication import ENCRYPTED_BIND_PASSWORD_TYPED, ENCRYPTED_CLIENT_SECRET_TYPED
from app.config import get_settings
from app.core.security import create_access_token
from app.models.auth_provider import AuthProviderConfig
from app.models.connection import Connection
from app.services.auth_config import decrypt_provider_config, save_provider_config
from app.services.secret_crypto import decrypt_secret, encrypt_secret, reset_fernet_cache

CONNECTIONS = "/api/admin/connections"
LDAP = "/api/admin/authentication/ldap"
OIDC = "/api/admin/authentication/oidc"


@pytest.fixture(autouse=True)
def _stable_data_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "data_encryption_key", "test-only-dedicated-data-encryption-key")
    reset_fernet_cache()
    yield
    reset_fernet_cache()


@pytest.fixture(autouse=True)
def _guard_on_the_test_engine(session_factory, monkeypatch):
    from app.services import admin_ip_allowlist_service

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    admin_ip_allowlist_service.invalidate_restriction_cache()
    yield
    admin_ip_allowlist_service.invalidate_restriction_cache()


def _sign_in(client, username: str) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(username, "user"))
    client.cookies.set(settings.csrf_cookie_name, "csrf-token")
    return {settings.csrf_header_name: "csrf-token"}


def _stolen_token() -> str:
    """What a database backup holds for some other secret, the SMTP password say."""
    return encrypt_secret("the-real-smtp-password")


async def _connections(db) -> list[Connection]:
    return list((await db.execute(select(Connection))).scalars())


class TestConnectionApiKey:
    async def test_a_stored_token_typed_as_the_key_is_refused_and_nothing_is_saved(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        resp = await client.post(
            CONNECTIONS,
            json={"name": "Exfil", "provider_type": "openai", "api_key": _stolen_token()},
            headers=headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ENCRYPTED_API_KEY_TYPED
        assert await _connections(db_session) == []

    async def test_a_typed_key_is_encrypted_as_typed(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        resp = await client.post(
            CONNECTIONS,
            json={"name": "OpenAI", "provider_type": "openai", "api_key": "sk-typed-by-a-person"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        [conn] = await _connections(db_session)
        assert conn.api_key_encrypted != "sk-typed-by-a-person"
        assert decrypt_secret(conn.api_key_encrypted) == "sk-typed-by-a-person"

    async def test_a_key_that_merely_looks_encrypted_is_kept_as_a_key(self, client, admin, db_session):
        """Only a token this deployment decrypts is refused; anything else is a key like any other."""
        lookalike = "gAAAAAB" + "Q" * 93
        headers = _sign_in(client, admin.username)
        resp = await client.post(
            CONNECTIONS, json={"name": "Odd", "provider_type": "openai", "api_key": lookalike}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        [conn] = await _connections(db_session)
        assert decrypt_secret(conn.api_key_encrypted) == lookalike

    async def test_no_key_stays_no_key(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        resp = await client.post(
            CONNECTIONS, json={"name": "Local", "provider_type": "ollama", "api_key": ""}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        [conn] = await _connections(db_session)
        assert conn.api_key_encrypted == ""

    async def test_editing_a_connection_refuses_a_stored_token_and_changes_nothing(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        created = await client.post(
            CONNECTIONS, json={"name": "OpenAI", "provider_type": "openai", "api_key": "sk-original"}, headers=headers
        )
        conn_id = created.json()["id"]
        resp = await client.patch(
            f"{CONNECTIONS}/{conn_id}", json={"name": "Renamed", "api_key": _stolen_token()}, headers=headers
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ENCRYPTED_API_KEY_TYPED
        db_session.expire_all()
        [conn] = await _connections(db_session)
        assert conn.name == "OpenAI"
        assert decrypt_secret(conn.api_key_encrypted) == "sk-original"

    async def test_editing_with_a_new_typed_key_encrypts_it(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        created = await client.post(
            CONNECTIONS, json={"name": "OpenAI", "provider_type": "openai", "api_key": "sk-original"}, headers=headers
        )
        conn_id = created.json()["id"]
        resp = await client.patch(f"{CONNECTIONS}/{conn_id}", json={"api_key": "sk-rotated"}, headers=headers)
        assert resp.status_code == 200, resp.text
        db_session.expire_all()
        [conn] = await _connections(db_session)
        assert decrypt_secret(conn.api_key_encrypted) == "sk-rotated"


class TestLdapBindPassword:
    @pytest.mark.parametrize("path", [LDAP, f"{LDAP}/test"])
    async def test_a_stored_token_typed_as_the_password_is_refused(self, client, admin, db_session, path):
        headers = _sign_in(client, admin.username)
        body = {"enabled": True, "dc_host": "dc.example.com", "bind_username": "svc", "bind_password": _stolen_token()}
        send = client.put if path == LDAP else client.post
        resp = await send(path, json=body, headers=headers)
        assert resp.status_code == 400
        assert resp.json()["detail"] == ENCRYPTED_BIND_PASSWORD_TYPED
        assert await db_session.get(AuthProviderConfig, "ldap") is None


class TestOidcClientSecret:
    async def test_a_stored_token_typed_as_the_client_secret_is_refused(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        body = {
            "enabled": True,
            "issuer": "https://idp.example.com",
            "client_id": "alpharouter",
            "client_secret": _stolen_token(),
        }
        resp = await client.put(OIDC, json=body, headers=headers)
        assert resp.status_code == 400
        assert resp.json()["detail"] == ENCRYPTED_CLIENT_SECRET_TYPED
        assert await db_session.get(AuthProviderConfig, "oidc") is None


class TestSavedProviderConfig:
    async def test_a_value_that_is_a_stored_token_is_encrypted_again_not_kept(self, db_session):
        """Below the API check, the save path itself never keeps a token as it is:
        it decrypts back to the token text, never to the secret the token holds."""
        token = _stolen_token()
        await save_provider_config(
            db_session, "oidc", True, {"issuer": "https://idp.example.com", "client_secret": token}
        )
        row = await db_session.get(AuthProviderConfig, "oidc")
        stored = json.loads(row.config_json)["client_secret"]
        assert stored != token
        assert decrypt_provider_config("oidc", {"client_secret": stored})["client_secret"] == token

    async def test_a_plain_secret_round_trips(self, db_session):
        await save_provider_config(db_session, "ldap", True, {"bind_password": "p@ss"})
        row = await db_session.get(AuthProviderConfig, "ldap")
        stored = json.loads(row.config_json)["bind_password"]
        assert stored != "p@ss"
        assert decrypt_provider_config("ldap", {"bind_password": stored})["bind_password"] == "p@ss"
