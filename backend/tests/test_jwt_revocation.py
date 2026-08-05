"""Tests for JWT revocation via the per-user token_version counter.

Covers:
- ``create_access_token`` embeds ``ver``.
- ``get_current_user`` accepts a token whose ``ver`` matches the user's
  current ``token_version`` and rejects one issued before a bump (logout /
  password reset / admin disable).
- Legacy tokens without ``ver`` are treated as 0 and keep working for
  existing users (backward compatible).
"""

import asyncio
import os

from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.config import get_settings
from app.core.security import create_access_token, decode_access_token
from app.database import Base
from app.models.user import User


def _enable_legacy_bearer_for_test() -> None:
    """Bearer-path revocation tests opt into the compatibility flag explicitly."""
    os.environ["ALLOW_LEGACY_BEARER_AUTH"] = "true"
    get_settings.cache_clear()


def _request(
    cookie: str | None = None,
    *,
    cookie_name: str = "alpha_router_session",
) -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", f"{cookie_name}={cookie}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


async def _setup() -> tuple[async_sessionmaker[AsyncSession], User]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        user = User(
            username="alice",
            email="alice@alpha-router.local",
            display_name="Alice",
            hashed_password="x",
            role="user",
            auth_provider="local",
            token_version=0,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return Session, user


async def _run_revocation_scenarios() -> None:
    Session, user = await _setup()

    # 1) Fresh token with ver=0 accepted when user.token_version=0.
    async with Session() as session:
        token = create_access_token("alice", "user", token_version=0)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        u = await get_current_user(request=_request(), creds=creds, db=session)
        assert u.username == "alice"

    # 2) Bump token_version (e.g. after logout) -> old token rejected.
    async with Session() as session:
        db_user = await session.get(User, user.id)
        db_user.token_version = 1
        await session.commit()
    async with Session() as session:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        try:
            await get_current_user(request=_request(), creds=creds, db=session)
            raise AssertionError("expected revoked token to be rejected")
        except Exception as exc:
            # FastAPI HTTPException status code 401
            assert getattr(exc, "status_code", None) == 401, exc

    # 3) Newly issued token with ver=1 accepted.
    async with Session() as session:
        new_token = create_access_token("alice", "user", token_version=1)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=new_token)
        u = await get_current_user(request=_request(new_token), creds=None, db=session)
        assert u.username == "alice"


async def _run_legacy_token_compat() -> None:
    Session, user = await _setup()

    # A token issued WITHOUT ver (legacy, before this feature) decodes to no
    # "ver" claim. It must be treated as 0 and accepted for an existing user
    # whose token_version is still 0.
    legacy_token = create_access_token("alice", "user")  # token_version defaults to 0
    payload = decode_access_token(legacy_token)
    assert payload is not None
    # create_access_token now always sets ver=0 by default; simulate a truly
    # legacy token by deleting the claim and re-encoding via jose directly.
    from jose import jwt as _jwt
    from app.config import get_settings

    del payload["ver"]
    legacy_token = _jwt.encode(payload, get_settings().secret_key, algorithm="HS256")
    assert "ver" not in decode_access_token(legacy_token)

    async with Session() as session:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=legacy_token)
        u = await get_current_user(request=_request(), creds=creds, db=session)
        assert u.username == "alice"

    # After a bump, even a legacy (no-ver => 0) token is rejected.
    async with Session() as session:
        db_user = await session.get(User, user.id)
        db_user.token_version = 1
        await session.commit()
    async with Session() as session:
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=legacy_token)
        try:
            await get_current_user(request=_request(), creds=creds, db=session)
            raise AssertionError("expected legacy token to be rejected after bump")
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 401, exc


async def _run_create_token_embeds_ver() -> None:
    token = create_access_token("bob", "user", token_version=7)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["ver"] == 7


def test_create_access_token_embeds_ver():
    asyncio.run(_run_create_token_embeds_ver())


def test_revocation_scenarios():
    _enable_legacy_bearer_for_test()
    asyncio.run(_run_revocation_scenarios())


def test_legacy_token_backward_compatible():
    _enable_legacy_bearer_for_test()
    asyncio.run(_run_legacy_token_compat())
