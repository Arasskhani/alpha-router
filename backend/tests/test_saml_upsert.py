"""Account-takeover prevention in _upsert_directory_user for SAML NameID binding."""

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.auth import _upsert_directory_user
from app.database import Base
from app.models.user import User


def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _test_saml_binds_by_external_id_not_username() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        u1 = await _upsert_directory_user(
            db,
            {"username": "alice", "email": "a@x", "external_id": "nameid-1"},
            "saml",
        )
        assert u1.auth_provider == "saml"
        assert u1.external_id == "nameid-1"
    async with factory() as db:
        u2 = await _upsert_directory_user(
            db,
            {"username": "alice2", "email": "a@x", "external_id": "nameid-1"},
            "saml",
        )
        assert u2.id == u1.id
    await engine.dispose()


async def _test_saml_refuses_cross_provider_username_collision() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(User(username="admin", hashed_password="x", role="user", auth_provider="local"))
        await db.commit()
    async with factory() as db:
        with pytest.raises(HTTPException) as exc:
            await _upsert_directory_user(
                db,
                {"username": "admin", "email": "sadmin@idp", "external_id": "saml-admin"},
                "saml",
            )
        assert exc.value.status_code == 409
    async with factory() as db:
        admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
        assert admin.auth_provider == "local"
        assert admin.external_id is None
    await engine.dispose()


async def _test_saml_same_provider_username_backfills_external_id() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(User(username="bob", role="user", auth_provider="saml", external_id=None))
        await db.commit()
    async with factory() as db:
        u = await _upsert_directory_user(
            db,
            {"username": "bob", "external_id": "bob-nameid"},
            "saml",
        )
        assert u.id is not None
        assert u.auth_provider == "saml"
        assert u.external_id == "bob-nameid"
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


def test_saml_binds_by_external_id_not_username():
    asyncio.run(_test_saml_binds_by_external_id_not_username())


def test_saml_refuses_cross_provider_username_collision():
    asyncio.run(_test_saml_refuses_cross_provider_username_collision())


def test_saml_same_provider_username_backfills_external_id():
    asyncio.run(_test_saml_same_provider_username_backfills_external_id())


def test_ldap_keeps_username_binding():
    asyncio.run(_test_ldap_keeps_username_binding())


async def _test_oidc_binds_by_sub_not_username() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        u1 = await _upsert_directory_user(
            db,
            {"username": "alice", "email": "a@x", "external_id": "oidc-sub-1"},
            "oidc",
        )
        assert u1.auth_provider == "oidc"
        assert u1.external_id == "oidc-sub-1"
    async with factory() as db:
        u2 = await _upsert_directory_user(
            db,
            {"username": "alice2", "email": "a@x", "external_id": "oidc-sub-1"},
            "oidc",
        )
        assert u2.id == u1.id
    await engine.dispose()


async def _test_oidc_refuses_local_username_takeover() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(User(username="admin", hashed_password="x", role="user", auth_provider="local"))
        await db.commit()
    async with factory() as db:
        with pytest.raises(HTTPException) as exc:
            await _upsert_directory_user(
                db,
                {"username": "admin", "email": "o@idp", "external_id": "oidc-admin"},
                "oidc",
            )
        assert exc.value.status_code == 409
    await engine.dispose()


def test_oidc_binds_by_sub_not_username():
    asyncio.run(_test_oidc_binds_by_sub_not_username())


def test_oidc_refuses_local_username_takeover():
    asyncio.run(_test_oidc_refuses_local_username_takeover())
