"""Greenfield at-rest secret-encryption contracts."""

import asyncio
import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base
from app.services.auth_config import (
    _SENSITIVE_FIELDS,
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
def _stable_data_key(monkeypatch):
    monkeypatch.setattr(
        get_settings(),
        "data_encryption_key",
        "test-only-dedicated-data-encryption-key",
    )
    reset_fernet_cache()
    yield
    reset_fernet_cache()


def test_round_trip_returns_original_plaintext():
    plaintext = "provider-api-key-value"
    ciphertext = encrypt_secret(plaintext)
    assert ciphertext != plaintext
    assert is_encrypted(ciphertext)
    assert decrypt_secret(ciphertext) == plaintext


def test_encrypt_validates_and_preserves_current_ciphertext():
    ciphertext = encrypt_secret("stored-secret")
    assert encrypt_secret(ciphertext) == ciphertext
    assert decrypt_secret(ciphertext) == "stored-secret"


def test_decrypt_rejects_plaintext_and_invalid_ciphertext():
    with pytest.raises(ValueError, match="not encrypted"):
        decrypt_secret("plaintext-is-not-a-stored-secret")
    bogus = "gAAAAABm" + "A" * 90
    with pytest.raises(ValueError, match="DATA_ENCRYPTION_KEY"):
        decrypt_secret(bogus)
    with pytest.raises(ValueError, match="DATA_ENCRYPTION_KEY"):
        encrypt_secret(bogus)


def test_empty_values_remain_optional():
    assert decrypt_secret("") == ""
    assert decrypt_secret(None) is None
    assert encrypt_secret("") == ""
    assert encrypt_secret(None) == ""


def test_mask_secret_decrypts_then_masks():
    plaintext = "provider-api-key-1234567890"
    masked = mask_secret(encrypt_secret(plaintext))
    assert masked.endswith(plaintext[-4:])
    assert plaintext not in masked
    assert mask_secret(None) == ""


def test_ciphertext_is_bound_to_configured_data_key(monkeypatch):
    ciphertext = encrypt_secret("bound-secret")
    monkeypatch.setattr(get_settings(), "data_encryption_key", "different-data-key")
    reset_fernet_cache()
    with pytest.raises(ValueError, match="DATA_ENCRYPTION_KEY"):
        decrypt_secret(ciphertext)


async def _make_db() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    session = factory()
    setattr(session, "_test_engine", engine)
    return session


async def _dispose_db(session: AsyncSession) -> None:
    await session.close()
    await getattr(session, "_test_engine").dispose()


async def _test_provider_config_persists_only_ciphertext():
    from app.models.auth_provider import AuthProviderConfig

    db = await _make_db()
    try:
        await save_provider_config(
            db,
            "ldap",
            enabled=True,
            config={
                "dc_host": "directory.example.test",
                "bind_username": "service-account",
                "bind_password": "directory-password",
                "port": 636,
                "use_ssl": True,
            },
        )
        row = await db.get(AuthProviderConfig, "ldap")
        stored = json.loads(row.config_json)
        assert "directory-password" not in row.config_json
        assert is_encrypted(stored["bind_password"])
        loaded = await get_provider_config(db, "ldap")
        assert loaded["bind_password"] == "directory-password"
        assert loaded["dc_host"] == "directory.example.test"
    finally:
        await _dispose_db(db)


def test_provider_config_persists_only_ciphertext():
    asyncio.run(_test_provider_config_persists_only_ciphertext())


def test_sensitive_fields_catalog():
    assert "bind_password" in _SENSITIVE_FIELDS["ldap"]
    assert "keycloak" not in _SENSITIVE_FIELDS
