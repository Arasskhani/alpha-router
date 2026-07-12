"""Phase 6: account-takeover prevention in _upsert_directory_user + one-time exchange.

The Keycloak upsert must bind by (auth_provider, external_id) and REFUSE to
silently take over a local/ldap account that merely shares a username — that
would be account takeover / privilege escalation (e.g. a Keycloak user named
"admin" hijacking the local Super Admin).
"""

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.api.auth import _upsert_directory_user


def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _test_keycloak_binds_by_external_id_not_username() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        # First Keycloak login for "alice" with sub=sub-1.
        u1 = await _upsert_directory_user(
            db,
            {"username": "alice", "email": "a@x", "external_id": "sub-1"},
            "keycloak",
        )
        assert u1.auth_provider == "keycloak"
        assert u1.external_id == "sub-1"
    async with factory() as db:
        # Same sub, but IdP now returns a different username (rename). Must
        # bind to the SAME account by external_id, not create a new one.
        u2 = await _upsert_directory_user(
            db,
            {"username": "alice2", "email": "a@x", "external_id": "sub-1"},
            "keycloak",
        )
        assert u2.id == u1.id
    await engine.dispose()


async def _test_keycloak_refuses_cross_provider_username_collision() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        # A local admin account "admin" exists.
        db.add(User(username="admin", hashed_password="x", role="user", auth_provider="local"))
        await db.commit()
    async with factory() as db:
        # A Keycloak user also named "admin" tries to log in. This MUST be
        # rejected (409), not silently take over the local admin account.
        with pytest.raises(HTTPException) as exc:
            await _upsert_directory_user(
                db,
                {"username": "admin", "email": "kadmin@kc", "external_id": "kc-sub-admin"},
                "keycloak",
            )
        assert exc.value.status_code == 409
    async with factory() as db:
        # Confirm the local admin account was NOT taken over.
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        assert admin.auth_provider == "local"
        assert admin.external_id is None
    await engine.dispose()


async def _test_keycloak_same_provider_username_backfills_external_id() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        # Legacy keycloak user without external_id (created before Phase 6).
        db.add(User(username="bob", role="user", auth_provider="keycloak", external_id=None))
        await db.commit()
    async with factory() as db:
        # Same provider + same username, now with external_id -> claim it.
        u = await _upsert_directory_user(
            db,
            {"username": "bob", "external_id": "bob-sub"},
            "keycloak",
        )
        assert u.id is not None
        assert u.auth_provider == "keycloak"
        assert u.external_id == "bob-sub"
    await engine.dispose()


async def _test_ldap_keeps_username_binding() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        u = await _upsert_directory_user(
            db,
            {"username": "ldapuser", "email": "l@x", "external_id": None},
            "ldap",
        )
        assert u.auth_provider == "ldap"
    await engine.dispose()


def test_keycloak_binds_by_external_id_not_username():
    asyncio.run(_test_keycloak_binds_by_external_id_not_username())


def test_keycloak_refuses_cross_provider_username_collision():
    asyncio.run(_test_keycloak_refuses_cross_provider_username_collision())


def test_keycloak_same_provider_username_backfills_external_id():
    asyncio.run(_test_keycloak_same_provider_username_backfills_external_id())


def test_ldap_keeps_username_binding():
    asyncio.run(_test_ldap_keeps_username_binding())
