"""Directory sync must not take over password-bearing local accounts.

A directory object whose sAMAccountName or mail matches a local row used to
flip that row to ``auth_provider="ldap"`` unconditionally. Because the login
path enforced TOTP only for ``local`` rows, one sync run silently disabled an
administrator's 2FA and let the directory identity inherit the row's roles.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register every table on Base.metadata
from app.database import Base
from app.models.user import User, UserRoleAssignment
from app.services import ldap_sync
from app.services.rbac import FULL_ADMIN_SLUG

CFG = {"enabled": True, "server": "ldaps://dc.example.com", "base_dn": "DC=example,DC=com"}


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


def _entry(username: str, *, guid: str, email: str | None = None) -> dict:
    return {
        "username": username,
        "external_id": guid,
        "dn": f"CN={username},OU=Users,DC=example,DC=com",
        "email": email or f"{username}@example.com",
        "display_name": username.title(),
    }


async def _run_sync(db: AsyncSession, users: list[dict], *, prune: bool = False, **settings_overrides) -> dict:
    cfg = dict(CFG, sync_ous_prune=prune)
    fake_settings = type("S", (), {"ldap_link_local_password_accounts": False, **settings_overrides})()
    with (
        patch.object(ldap_sync, "fetch_ldap_users", return_value=users),
        patch.object(ldap_sync, "fetch_ldap_groups", return_value=[]),
        patch.object(ldap_sync, "get_settings", return_value=fake_settings),
    ):
        result = await ldap_sync.sync_ldap_directory(db, cfg)
    await db.commit()
    return result


async def _reload(db: AsyncSession, username: str) -> User:
    return (await db.execute(select(User).where(User.username == username))).scalars().one()


def test_local_password_account_is_not_linked_by_username_or_email():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                db.add(
                    User(
                        username="admin",
                        email="admin@example.com",
                        hashed_password="$2b$hash",
                        auth_provider="local",
                        totp_enabled=True,
                        is_active=True,
                    )
                )
                await db.commit()

                # Same sAMAccountName as the local admin, plus an unrelated user.
                result = await _run_sync(
                    db,
                    [_entry("admin", guid="guid-admin"), _entry("jdoe", guid="guid-jdoe")],
                    prune=True,
                )

                admin = await _reload(db, "admin")
                assert admin.auth_provider == "local"
                assert admin.hashed_password == "$2b$hash"
                assert admin.external_id is None, "refused rows must be left byte-for-byte alone"
                assert admin.totp_enabled is True

                jdoe = await _reload(db, "jdoe")
                assert jdoe.auth_provider == "ldap"

                assert result["local_password_skipped"] == 1
                assert result["users_skipped"] == 0, "a policy skip is not a failure"
                assert result["prune_skipped"] is False, "policy skips must not suppress pruning"
                reasons = {c["reason"] for c in result["conflicts"]}
                assert "local_password_account" in reasons
                assert result["local_accounts_linked"] == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_local_password_account_links_when_operator_opts_in():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                db.add(
                    User(
                        username="alice",
                        email="alice@example.com",
                        hashed_password="$2b$hash",
                        auth_provider="local",
                        is_active=True,
                    )
                )
                await db.commit()

                result = await _run_sync(
                    db,
                    [_entry("alice", guid="guid-alice")],
                    ldap_link_local_password_accounts=True,
                )

                alice = await _reload(db, "alice")
                assert alice.auth_provider == "ldap"
                assert alice.external_id == "guid-alice"
                assert alice.hashed_password == "$2b$hash", "password stays as the break-glass path"
                assert result["local_accounts_linked"] == 1
                assert result["local_password_skipped"] == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_full_administrator_is_never_linked_even_with_opt_in():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                root = User(
                    username="root",
                    email="root@example.com",
                    hashed_password="$2b$hash",
                    auth_provider="local",
                    is_active=True,
                )
                db.add(root)
                await db.flush()
                db.add(UserRoleAssignment(user_id=root.id, role_slug=FULL_ADMIN_SLUG))
                await db.commit()

                result = await _run_sync(
                    db,
                    [_entry("root", guid="guid-root")],
                    ldap_link_local_password_accounts=True,
                )

                root = await _reload(db, "root")
                assert root.auth_provider == "local"
                assert root.external_id is None
                assert result["local_password_skipped"] == 1
                assert any("Full Administrator" in c["detail"] for c in result["conflicts"])
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_passwordless_local_row_and_existing_ldap_row_still_link():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                db.add(
                    User(
                        username="pre",
                        email="pre@example.com",
                        hashed_password=None,
                        auth_provider="local",
                        is_active=True,
                    )
                )
                db.add(
                    User(
                        username="old-name",
                        email="moved@example.com",
                        hashed_password="$2b$hash",  # break-glass password on an LDAP row
                        auth_provider="ldap",
                        external_id="CN=old-name,OU=Users,DC=example,DC=com",
                        is_active=True,
                    )
                )
                await db.commit()

                moved = _entry("new-name", guid="guid-moved", email="moved@example.com")
                moved["dn"] = "CN=old-name,OU=Users,DC=example,DC=com"
                result = await _run_sync(db, [_entry("pre", guid="guid-pre"), moved])

                pre = await _reload(db, "pre")
                assert pre.auth_provider == "ldap"
                assert pre.external_id == "guid-pre"

                # ldap row matched by its historical DN: GUID backfilled, password kept.
                row = (await db.execute(select(User).where(User.external_id == "guid-moved"))).scalars().one()
                assert row.auth_provider == "ldap"
                assert row.hashed_password == "$2b$hash"

                assert result["local_password_skipped"] == 0
                assert result["local_accounts_linked"] == 1
        finally:
            await engine.dispose()

    asyncio.run(run())
