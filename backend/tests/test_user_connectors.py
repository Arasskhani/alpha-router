"""Security tests for per-user Connectors.

These run against an in-memory SQLite DB to validate the data model and
registry guards. API-level IDOR/CSRF tests are added in Step 2 once the
router exists; here we assert the foundations: encrypted storage, unique
constraint, and SSRF allowlist.
"""

import asyncio
import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.models.user_connector import UserConnector
from app.services import connector_registry
from app.services.secret_crypto import decrypt_secret, encrypt_secret, is_encrypted


def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def test_registry_google_providers_present():
    assert connector_registry.get_connector("gmail") is not None
    assert connector_registry.get_connector("google_drive") is not None
    assert connector_registry.get_connector("google_calendar") is not None


def test_registry_unknown_provider_rejected():
    assert connector_registry.get_connector("evil") is None
    assert connector_registry.is_known_provider("evil") is False


def test_registry_ssrf_allowlist_blocks_arbitrary_urls():
    # Only registered MCP URLs are allowed.
    assert connector_registry.is_allowed_mcp_url("https://gmailmcp.googleapis.com/mcp/v1") is True
    assert connector_registry.is_allowed_mcp_url("http://169.254.169.254/latest/meta-data/") is False
    assert connector_registry.is_allowed_mcp_url("https://attacker.example.com/mcp") is False


def test_registry_scopes_pinned_least_privilege():
    gmail = connector_registry.get_connector("gmail")
    assert "https://www.googleapis.com/auth/gmail.readonly" in gmail.scopes
    # No destructive scope like gmail.modify or gmail.send granted by default.
    assert all("send" not in s and "modify" not in s for s in gmail.scopes)


def test_secrets_are_encrypted_at_rest():
    enc = encrypt_secret("my-client-secret")
    assert enc != "my-client-secret"
    assert is_encrypted(enc) is True
    assert decrypt_secret(enc) == "my-client-secret"


async def _test_unique_constraint_and_user_scoping() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(User(username="alice", auth_provider="local", hashed_password="x"))
        db.add(User(username="bob", auth_provider="local", hashed_password="x"))
        await db.commit()
        from sqlalchemy import select

        alice = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
        bob = (await db.execute(select(User).where(User.username == "bob"))).scalar_one()
        alice_id = alice.id
        bob_id = bob.id

        db.add(UserConnector(user_id=alice_id, provider_id="gmail", client_id_encrypted=encrypt_secret("cid")))
        await db.commit()

        # Same provider for same user must fail (unique constraint).
        db.add(UserConnector(user_id=alice_id, provider_id="gmail", client_id_encrypted=encrypt_secret("cid2")))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        # Different user can have the same provider (no cross-user clash).
        db.add(UserConnector(user_id=bob_id, provider_id="gmail", client_id_encrypted=encrypt_secret("cid3")))
        await db.commit()

        # Alice cannot read Bob's row by simple filter — emulate IDOR guard at query layer.
        alice_rows = (
            await db.execute(select(UserConnector).where(UserConnector.user_id == alice_id))
        ).scalars().all()
        bob_rows = (
            await db.execute(select(UserConnector).where(UserConnector.user_id == bob_id))
        ).scalars().all()
        assert len(alice_rows) == 1
        assert len(bob_rows) == 1
        assert alice_rows[0].user_id == alice_id
        assert bob_rows[0].user_id == bob_id
    await engine.dispose()


def test_unique_constraint_and_user_scoping():
    asyncio.run(_test_unique_constraint_and_user_scoping())


async def _test_encrypted_fields_round_trip() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(User(username="alice", auth_provider="local", hashed_password="x"))
        await db.commit()
        from sqlalchemy import select

        alice = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
        alice_id = alice.id
        db.add(
            UserConnector(
                user_id=alice_id,
                provider_id="gmail",
                client_id_encrypted=encrypt_secret("client-id"),
                client_secret_encrypted=encrypt_secret("client-secret"),
                access_token_encrypted=encrypt_secret("access-tok"),
                refresh_token_encrypted=encrypt_secret("refresh-tok"),
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=1),
                scope=" ".join(connector_registry.get_connector("gmail").scopes),
            )
        )
        await db.commit()
        row = (
            await db.execute(select(UserConnector).where(UserConnector.user_id == alice_id))
        ).scalar_one()
        # Ciphertext is not plaintext.
        assert row.client_secret_encrypted != "client-secret"
        assert is_encrypted(row.client_secret_encrypted) is True
        assert decrypt_secret(row.client_secret_encrypted) == "client-secret"
        assert decrypt_secret(row.access_token_encrypted) == "access-tok"
    await engine.dispose()


def test_encrypted_fields_round_trip():
    asyncio.run(_test_encrypted_fields_round_trip())
