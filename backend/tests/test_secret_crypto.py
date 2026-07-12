"""Phase 3 — at-rest secret encryption.

Covers the ``secret_crypto`` primitive (round-trip, plaintext fallback, and
idempotent encryption), the admin write/read paths (connections stored as
ciphertext, masking decrypts first), and the one-time startup migration that
encrypts legacy plaintext rows in place.

Async cases use the same ``asyncio.run`` wrapper pattern the rest of the suite
uses (no pytest-asyncio dependency).
"""

import asyncio
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base
from app.services.auth_config import (
    _SENSITIVE_FIELDS,
    decrypt_provider_config,
    get_provider_config,
    save_provider_config,
)
from app.services.secret_crypto import (
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
    mask_secret,
    reset_fernet_cache,
)


@pytest.fixture(autouse=True)
def _stable_secret_key(monkeypatch):
    """Pin SECRET_KEY for the whole suite so the derived Fernet key is stable."""
    monkeypatch.setattr(get_settings(), "secret_key", "test-secret-key-for-phase3")
    reset_fernet_cache()
    yield
    reset_fernet_cache()


# ---------------------------------------------------------------------------
# Primitive: encrypt / decrypt / detect
# ---------------------------------------------------------------------------


def test_round_trip_returns_original_plaintext():
    plain = "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"
    cipher = encrypt_secret(plain)
    assert cipher != plain
    assert is_encrypted(cipher)
    assert decrypt_secret(cipher) == plain


def test_encrypt_is_idempotent_does_not_double_encrypt():
    plain = "my-secret-api-key"
    once = encrypt_secret(plain)
    twice = encrypt_secret(once)
    assert once == twice, "re-encrypting ciphertext must return the same ciphertext"
    assert decrypt_secret(twice) == plain


def test_decrypt_falls_back_for_plaintext():
    assert decrypt_secret("sk-or-v1-plain-legacy-key") == "sk-or-v1-plain-legacy-key"
    assert decrypt_secret("") == ""
    assert decrypt_secret(None) is None


def test_decrypt_falls_back_for_unrecognized_ciphertext():
    bogus = "gAAAAABm" + "A" * 90  # looks like a token but won't decrypt
    assert decrypt_secret(bogus) == bogus


def test_is_encrypted_detection():
    assert not is_encrypted(None)
    assert not is_encrypted("")
    assert not is_encrypted("sk-or-v1-plaintext")
    assert not is_encrypted("short")
    assert is_encrypted(encrypt_secret("anything"))


def test_mask_secret_decrypts_then_masks():
    plain = "sk-or-v1-1234567890abcdef"
    cipher = encrypt_secret(plain)
    masked = mask_secret(cipher)
    assert masked.endswith(plain[-4:])
    assert "*" in masked
    assert plain not in masked
    assert mask_secret(None) == ""
    assert mask_secret("") == ""


# ---------------------------------------------------------------------------
# In-memory DB helper
# ---------------------------------------------------------------------------


async def _make_db() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = Session()
    setattr(session, "_test_engine", engine)
    return session


async def _dispose_db(session: AsyncSession) -> None:
    engine = getattr(session, "_test_engine")
    await session.close()
    await engine.dispose()


# ---------------------------------------------------------------------------
# auth_config: LDAP / Keycloak config_json secrets
# ---------------------------------------------------------------------------


async def _test_save_and_load_provider_config_encrypts_secrets():
    from app.models.auth_provider import AuthProviderConfig

    db = await _make_db()
    try:
        await save_provider_config(
            db,
            "keycloak",
            enabled=True,
            config={
                "server_url": "http://kc:8080",
                "realm": "demo",
                "client_id": "nitro",
                "client_secret": "super-secret-client-secret",
                "admin_client_secret": "super-secret-admin-secret",
            },
        )

        row = await db.get(AuthProviderConfig, "keycloak")
        stored = json.loads(row.config_json)
        assert "super-secret-client-secret" not in row.config_json
        assert "super-secret-admin-secret" not in row.config_json
        assert is_encrypted(stored["client_secret"])
        assert is_encrypted(stored["admin_client_secret"])
        assert stored["server_url"] == "http://kc:8080"
        assert stored["realm"] == "demo"

        cfg = await get_provider_config(db, "keycloak")
        assert cfg["client_secret"] == "super-secret-client-secret"
        assert cfg["admin_client_secret"] == "super-secret-admin-secret"
        assert cfg["server_url"] == "http://kc:8080"
    finally:
        await _dispose_db(db)


def test_save_and_load_provider_config_encrypts_secrets():
    asyncio.run(_test_save_and_load_provider_config_encrypts_secrets())


def test_decrypt_provider_config_helper_handles_plaintext_and_cipher():
    plain = "bind-password-plaintext"
    cipher = encrypt_secret(plain)
    out = decrypt_provider_config("ldap", {"bind_password": cipher, "dc_host": "h"})
    assert out["bind_password"] == plain
    assert out["dc_host"] == "h"
    out2 = decrypt_provider_config("ldap", {"bind_password": plain})
    assert out2["bind_password"] == plain
    out3 = decrypt_provider_config("unknown", {"foo": "bar"})
    assert out3 == {"foo": "bar"}


def test_sensitive_fields_catalog():
    assert "bind_password" in _SENSITIVE_FIELDS["ldap"]
    assert "client_secret" in _SENSITIVE_FIELDS["keycloak"]
    assert "admin_client_secret" in _SENSITIVE_FIELDS["keycloak"]


# ---------------------------------------------------------------------------
# Startup migration: encrypt legacy plaintext rows in place
# ---------------------------------------------------------------------------


async def _test_migration_encrypts_legacy_connection_plaintext():
    from app.models.connection import Connection
    from app.services.migration_flags import (
        SECRET_AT_REST_ENCRYPTION_KEY,
        is_migration_completed,
    )
    from app.db_migrate import apply_secret_at_rest_encryption

    db = await _make_db()
    try:
        db.add(
            Connection(
                name="legacy",
                provider_type="openrouter",
                api_key_encrypted="sk-or-v1-plaintext-legacy-key",
                base_url=None,
            )
        )
        await db.commit()

        await apply_secret_at_rest_encryption(db)

        conn = (await db.execute(select(Connection))).scalars().first()
        assert is_encrypted(conn.api_key_encrypted), "row should now hold ciphertext"
        assert decrypt_secret(conn.api_key_encrypted) == "sk-or-v1-plaintext-legacy-key"
        assert await is_migration_completed(db, SECRET_AT_REST_ENCRYPTION_KEY)
    finally:
        await _dispose_db(db)


def test_migration_encrypts_legacy_connection_plaintext():
    asyncio.run(_test_migration_encrypts_legacy_connection_plaintext())


async def _test_migration_is_idempotent_and_skips_already_encrypted():
    from app.models.connection import Connection
    from app.db_migrate import apply_secret_at_rest_encryption

    db = await _make_db()
    try:
        cipher = encrypt_secret("sk-or-v1-already-encrypted")
        db.add(
            Connection(
                name="already",
                provider_type="openrouter",
                api_key_encrypted=cipher,
                base_url=None,
            )
        )
        await db.commit()

        await apply_secret_at_rest_encryption(db)
        conn = (await db.execute(select(Connection))).scalars().first()
        assert conn.api_key_encrypted == cipher
        assert decrypt_secret(conn.api_key_encrypted) == "sk-or-v1-already-encrypted"

        await apply_secret_at_rest_encryption(db)
        conn = (await db.execute(select(Connection))).scalars().first()
        assert conn.api_key_encrypted == cipher
    finally:
        await _dispose_db(db)


def test_migration_is_idempotent_and_skips_already_encrypted():
    asyncio.run(_test_migration_is_idempotent_and_skips_already_encrypted())


async def _test_migration_encrypts_ldap_config_json_sensitive_field():
    from app.models.auth_provider import AuthProviderConfig
    from app.db_migrate import apply_secret_at_rest_encryption

    db = await _make_db()
    try:
        db.add(
            AuthProviderConfig(
                provider="ldap",
                enabled=True,
                config_json=json.dumps(
                    {
                        "dc_host": "dc.example.com",
                        "bind_username": "svc_ldap",
                        "bind_password": "plaintext-ldap-bind-pw",
                        "port": 636,
                    }
                ),
            )
        )
        await db.commit()

        await apply_secret_at_rest_encryption(db)

        row = await db.get(AuthProviderConfig, "ldap")
        stored = json.loads(row.config_json)
        assert stored["bind_password"] != "plaintext-ldap-bind-pw"
        assert is_encrypted(stored["bind_password"])
        assert stored["dc_host"] == "dc.example.com"
        assert stored["bind_username"] == "svc_ldap"
        assert decrypt_secret(stored["bind_password"]) == "plaintext-ldap-bind-pw"
    finally:
        await _dispose_db(db)


def test_migration_encrypts_ldap_config_json_sensitive_field():
    asyncio.run(_test_migration_encrypts_ldap_config_json_sensitive_field())
