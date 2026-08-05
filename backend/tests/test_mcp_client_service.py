"""Security tests for mcp_client_service (Step 5).

Covers: per-user token isolation, SSRF allowlist enforcement, 401 → refresh →
retry, and that tokens never appear in logs/return values.
"""

from __future__ import annotations

import asyncio
import datetime
import io
import logging
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.models.user_connector import UserConnector
from app.services import mcp_client_service as mcs
from app.services.connector_registry import get_connector
from app.services.secret_crypto import decrypt_secret, encrypt_secret


def _engine_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _patch_client(transport: httpx.MockTransport):
    real = httpx.AsyncClient

    def patched(*a, **kw):
        kw.setdefault("transport", transport)
        return real(*a, **kw)

    return patch("httpx.AsyncClient", new=patched)


def _make_transport(handler):
    return httpx.MockTransport(handler)


async def _seed(factory, alice_id=None, bob_id=None):
    async with factory() as db:
        if alice_id is None:
            db.add(User(username="alice", role="user", auth_provider="local", hashed_password="x"))
            await db.commit()
            alice = (await db.execute(select(User).where(User.username == "alice"))).scalar_one()
            alice_id = alice.id
        if bob_id is None:
            db.add(User(username="bob", role="user", auth_provider="local", hashed_password="x"))
            await db.commit()
            bob = (await db.execute(select(User).where(User.username == "bob"))).scalar_one()
            bob_id = bob.id
    return alice_id, bob_id


async def _add_connector(factory, user_id, provider_id="gmail", access="alice-atok", refresh="alice-rtok"):
    async with factory() as db:
        db.add(
            UserConnector(
                user_id=user_id,
                provider_id=provider_id,
                client_id_encrypted=encrypt_secret("cid"),
                client_secret_encrypted=encrypt_secret("csec"),
                access_token_encrypted=encrypt_secret(access),
                refresh_token_encrypted=encrypt_secret(refresh),
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=1),
                scope=" ".join(get_connector(provider_id).scopes),
            )
        )
        await db.commit()


def test_list_tools_only_uses_calling_users_tokens():
    engine, factory = _engine_factory()
    asyncio.run(_run_list_tools_isolation(engine, factory))


async def _run_list_tools_isolation(engine, factory):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    alice_id, bob_id = await _seed(factory)

    # Alice has gmail; bob has google_calendar. Each MCP server echoes the
    # bearer token it received so we can prove isolation.
    seen_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_tokens.append(request.headers.get("authorization", ""))
        # Return a minimal tools/list result.
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"tools": [{"name": "search", "description": "d", "inputSchema": {"type": "object"}}]},
            },
        )

    await _add_connector(factory, alice_id, "gmail", access="ALICE-TOK")
    await _add_connector(factory, bob_id, "google_calendar", access="BOB-TOK")

    transport = _make_transport(handler)
    with _patch_client(transport):
        async with factory() as db:
            tools = await mcs.list_tools_for_user(db, alice_id)
    # Only Alice's connector (gmail) should have been queried.
    assert len(tools) == 1
    assert tools[0]["_alpha_router_provider"] == "gmail"
    assert tools[0]["_alpha_router_tool"] == "search"
    assert tools[0]["function"]["name"].startswith("gmail.")
    # The bearer used must be Alice's, never Bob's.
    assert any("ALICE-TOK" in t for t in seen_tokens)
    assert not any("BOB-TOK" in t for t in seen_tokens)
    await engine.dispose()


def test_call_tool_ssrf_allowlist_blocks_unknown_provider():
    engine, factory = _engine_factory()
    asyncio.run(_run_ssrf(engine, factory))


async def _run_ssrf(engine, factory):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    alice_id, _ = await _seed(factory)
    await _add_connector(factory, alice_id)
    async with factory() as db:
        with pytest.raises(mcs.McpError, match="Unknown or disallowed"):
            await mcs.call_tool(db, alice_id, "evil_provider", "search", {"q": "x"})
    await engine.dispose()


def test_call_tool_401_triggers_refresh_and_retry():
    engine, factory = _engine_factory()
    asyncio.run(_run_refresh_retry(engine, factory))


async def _run_refresh_retry(engine, factory):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    alice_id, _ = await _seed(factory)
    await _add_connector(factory, alice_id, access="STALE-TOK", refresh="RTOK")

    call_count = {"n": 0}
    refresh_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2.googleapis.com/token" in url:
            refresh_count["n"] += 1
            return httpx.Response(200, json={"access_token": "FRESH-TOK", "expires_in": 3600})
        # MCP endpoint: first call 401 with stale token, second (retry) 200 with fresh.
        call_count["n"] += 1
        auth = request.headers.get("authorization", "")
        if "STALE-TOK" in auth:
            return httpx.Response(401, json={"error": "unauthorized"})
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}},
        )

    transport = _make_transport(handler)
    with _patch_client(transport):
        async with factory() as db:
            result = await mcs.call_tool(db, alice_id, "gmail", "search", {"q": "x"})
    assert call_count["n"] == 2  # initial 401 + retry
    assert refresh_count["n"] == 1
    assert result.get("content")[0]["text"] == "ok"

    # The refreshed token must have been persisted (encrypted).
    async with factory() as db:
        row = (
            await db.execute(select(UserConnector).where(UserConnector.user_id == alice_id))
        ).scalar_one()
        assert decrypt_secret(row.access_token_encrypted) == "FRESH-TOK"
    await engine.dispose()


def test_tokens_never_logged():
    engine, factory = _engine_factory()
    asyncio.run(_run_no_log_leak(engine, factory))


async def _run_no_log_leak(engine, factory):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    alice_id, _ = await _seed(factory)
    await _add_connector(factory, alice_id, access="SECRET-TOK-XYZ", refresh="SECRET-RTOK")

    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    logger = logging.getLogger("alpha_router.mcp")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    def srv(request: httpx.Request) -> httpx.Response:
        # Force a refresh error path so the service logs a warning.
        if "oauth2.googleapis.com/token" in str(request.url):
            return httpx.Response(500, json={"error": "boom"})
        # Make the token expired so refresh is attempted.
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})

    # Expire the token to force a refresh attempt that fails.
    async with factory() as db:
        row = (
            await db.execute(select(UserConnector).where(UserConnector.user_id == alice_id))
        ).scalar_one()
        row.expires_at = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        await db.commit()

    transport = _make_transport(srv)
    with _patch_client(transport):
        async with factory() as db:
            await mcs.list_tools_for_user(db, alice_id)

    logger.removeHandler(handler)
    log_text = log_buf.getvalue()
    assert "SECRET-TOK-XYZ" not in log_text
    assert "SECRET-RTOK" not in log_text
    await engine.dispose()
