"""Phase 9 — data-key rotation migration (idempotent, multi-key, no plaintext)."""

import asyncio
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base
from app.services.migration_flags import DATA_KEY_ROTATION_V1_KEY, is_migration_completed
from app.services.secret_crypto import decrypt_secret, encrypt_secret, is_encrypted, reset_fernet_cache


@pytest.fixture(autouse=True)
def _reset_caches():
    reset_fernet_cache()
    yield
    reset_fernet_cache()


def _set_keys(monkeypatch, *, secret_key: str, data_key: str = ""):
    settings = get_settings()
    monkeypatch.setattr(settings, "secret_key", secret_key)
    monkeypatch.setattr(settings, "data_encryption_key", data_key)
    reset_fernet_cache()


async def _make_db() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    setattr(session, "_test_engine", engine)
    return session


async def _dispose_db(session: AsyncSession) -> None:
    engine = getattr(session, "_test_engine")
    await session.close()
    await engine.dispose()


async def _test_rotation_re_encrypts_legacy_ciphertext(monkeypatch):
    from app.models.connection import Connection
    from app.db_migrate import apply_data_key_rotation

    # 1) Encrypt a secret under the legacy key (no DATA_ENCRYPTION_KEY).
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="")
    legacy_cipher = encrypt_secret("sk-or-v1-rotate-me")

    db = await _make_db()
    try:
        db.add(
            Connection(
                name="rot",
                provider_type="openrouter",
                api_key_encrypted=legacy_cipher,
                base_url=None,
            )
        )
        await db.commit()

        # 2) Rotate to a dedicated data key and run the migration.
        _set_keys(monkeypatch, secret_key="legacy-secret", data_key="new-data-key")
        result = await apply_data_key_rotation(db)

        assert result["completed"] is True
        assert result["connections"] == 1
        assert result["skipped"] is False

        conn = (await db.execute(select(Connection))).scalars().first()
        assert is_encrypted(conn.api_key_encrypted)
        # Still decrypts (now under the primary/data key).
        assert decrypt_secret(conn.api_key_encrypted) == "sk-or-v1-rotate-me"

        # 3) Prove it is primary-key ciphertext: drop the data key so only the
        #    legacy key remains; the rotated ciphertext must NOT decrypt.
        _set_keys(monkeypatch, secret_key="legacy-secret", data_key="")
        assert decrypt_secret(conn.api_key_encrypted) == conn.api_key_encrypted
    finally:
        await _dispose_db(db)


def test_rotation_re_encrypts_legacy_ciphertext(monkeypatch):
    asyncio.run(_test_rotation_re_encrypts_legacy_ciphertext(monkeypatch))


async def _test_rotation_is_idempotent(monkeypatch):
    from app.models.connection import Connection
    from app.db_migrate import apply_data_key_rotation

    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="new-data-key")
    db = await _make_db()
    try:
        db.add(
            Connection(
                name="rot",
                provider_type="openrouter",
                api_key_encrypted=encrypt_secret("sk-or-v1-once"),
                base_url=None,
            )
        )
        await db.commit()

        first = await apply_data_key_rotation(db)
        assert first["connections"] == 1
        cipher_after_first = (await db.execute(select(Connection))).scalars().first().api_key_encrypted

        second = await apply_data_key_rotation(db)
        assert second["skipped"] is True
        assert second["connections"] == 0
        cipher_after_second = (await db.execute(select(Connection))).scalars().first().api_key_encrypted
        assert cipher_after_first == cipher_after_second  # untouched on re-run

        assert await is_migration_completed(db, DATA_KEY_ROTATION_V1_KEY)
    finally:
        await _dispose_db(db)


def test_rotation_is_idempotent(monkeypatch):
    asyncio.run(_test_rotation_is_idempotent(monkeypatch))


async def _test_rotation_encrypts_plaintext_rows(monkeypatch):
    from app.models.connection import Connection
    from app.db_migrate import apply_data_key_rotation

    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="new-data-key")
    db = await _make_db()
    try:
        db.add(
            Connection(
                name="plain",
                provider_type="openrouter",
                api_key_encrypted="sk-or-v1-plaintext-legacy",
                base_url=None,
            )
        )
        await db.commit()

        result = await apply_data_key_rotation(db)
        assert result["connections"] == 1
        conn = (await db.execute(select(Connection))).scalars().first()
        assert is_encrypted(conn.api_key_encrypted)
        assert decrypt_secret(conn.api_key_encrypted) == "sk-or-v1-plaintext-legacy"
    finally:
        await _dispose_db(db)


def test_rotation_encrypts_plaintext_rows(monkeypatch):
    asyncio.run(_test_rotation_encrypts_plaintext_rows(monkeypatch))


async def _test_rotation_re_encrypts_auth_provider_sensitive_fields(monkeypatch):
    from app.models.auth_provider import AuthProviderConfig
    from app.db_migrate import apply_data_key_rotation

    # Legacy ciphertext for the bind_password.
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="")
    legacy_cipher = encrypt_secret("plaintext-ldap-bind-pw")

    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="new-data-key")
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
                        "bind_password": legacy_cipher,
                        "port": 636,
                    }
                ),
            )
        )
        await db.commit()

        result = await apply_data_key_rotation(db)
        assert result["auth_providers"] == 1

        row = await db.get(AuthProviderConfig, "ldap")
        stored = json.loads(row.config_json)
        assert stored["dc_host"] == "dc.example.com"
        assert stored["bind_username"] == "svc_ldap"
        assert is_encrypted(stored["bind_password"])
        assert decrypt_secret(stored["bind_password"]) == "plaintext-ldap-bind-pw"

        # No plaintext leaked into the stored JSON.
        assert "plaintext-ldap-bind-pw" not in row.config_json
    finally:
        await _dispose_db(db)


def test_rotation_re_encrypts_auth_provider_sensitive_fields(monkeypatch):
    asyncio.run(_test_rotation_re_encrypts_auth_provider_sensitive_fields(monkeypatch))


async def _test_rotation_returns_counts_without_plaintext(monkeypatch):
    from app.models.connection import Connection
    from app.db_migrate import apply_data_key_rotation

    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="new-data-key")
    db = await _make_db()
    try:
        db.add(
            Connection(
                name="a",
                provider_type="openrouter",
                api_key_encrypted=encrypt_secret("super-secret-api-key-value"),
                base_url=None,
            )
        )
        await db.commit()
        result = await apply_data_key_rotation(db)
        # Result contains only counts/flags — never the plaintext.
        assert "super-secret-api-key-value" not in json.dumps(result)
        assert set(result.keys()) >= {"completed", "connections", "smtp", "auth_providers", "skipped"}
    finally:
        await _dispose_db(db)


def test_rotation_returns_counts_without_plaintext(monkeypatch):
    asyncio.run(_test_rotation_returns_counts_without_plaintext(monkeypatch))
