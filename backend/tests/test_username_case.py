"""Case-insensitive username identity."""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.auth import _upsert_directory_user
from app.database import Base
from app.models.user import User
from app.services.username_norm import (
    find_user_by_username_ci,
    normalize_username,
    username_taken_ci,
)


def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def test_normalize_username_strips_and_lowers():
    assert normalize_username("  Ali ") == "ali"
    assert normalize_username(None) == ""


async def _test_find_and_taken_ci() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(User(username="Ali", auth_provider="local", hashed_password="x"))
        await db.commit()
    async with factory() as db:
        found = await find_user_by_username_ci(db, "ALI")
        assert found is not None
        assert found.username == "Ali"
        assert await username_taken_ci(db, "ali") is True
        assert await username_taken_ci(db, "ali", exclude_user_id=found.id) is False
        assert await username_taken_ci(db, "bob") is False
    await engine.dispose()


async def _test_upsert_matches_existing_mixed_case_without_rename() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(User(username="Ali", auth_provider="ldap"))
        await db.commit()
    async with factory() as db:
        user = await _upsert_directory_user(
            db,
            {"username": "ALI", "email": "a@x"},
            "ldap",
        )
        assert user.username == "Ali"
    await engine.dispose()


async def _test_upsert_stores_new_username_lowercase() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        user = await _upsert_directory_user(
            db,
            {"username": "Bob", "email": "b@x"},
            "ldap",
        )
        assert user.username == "bob"
    await engine.dispose()


async def _test_upsert_refuses_cross_provider_case_collision() -> None:
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(User(username="admin", hashed_password="x", auth_provider="local"))
        await db.commit()
    async with factory() as db:
        with pytest.raises(HTTPException) as exc:
            await _upsert_directory_user(
                db,
                {"username": "ADMIN", "email": "s@idp", "external_id": "saml-admin"},
                "saml",
            )
        assert exc.value.status_code == 409
    await engine.dispose()


async def test_find_and_taken_ci():
    await _test_find_and_taken_ci()


async def test_upsert_matches_existing_mixed_case_without_rename():
    await _test_upsert_matches_existing_mixed_case_without_rename()


async def test_upsert_stores_new_username_lowercase():
    await _test_upsert_stores_new_username_lowercase()


async def test_upsert_refuses_cross_provider_case_collision():
    await _test_upsert_refuses_cross_provider_case_collision()
