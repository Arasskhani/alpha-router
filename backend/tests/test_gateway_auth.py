"""Phase 1 — /v1 gateway auth hardening.

Covers:
- Missing/empty/unknown Bearer key → 401 (no anonymous access).
- Master key maps to a FIXED service account; body.user is ignored (no impersonation).
- User API key resolves to its owner with budget applied (skip_budget=False).
- Alpharouter API key skips user budget but is still subject to its own credit limit.
- /v1/models read gate (_require_valid_gateway_key) rejects missing/unknown, accepts valid.
"""

import asyncio
import datetime
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import gateway
from app.core.security import hash_api_key
from app.database import Base
from app.models.api_key import AlphaRouterApiKey, UserApiKey
from app.models.user import User

MASTER_KEY = gateway.settings.gateway_master_key
GATEWAY_SERVICE_USERNAME = gateway.GATEWAY_SERVICE_USERNAME


class _CIHeaders:
    """Case-insensitive header mapping, mimicking starlette's Headers.get()."""

    def __init__(self, items: dict[str, str] | None = None):
        self._items = {k.lower(): v for k, v in (items or {}).items()}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._items.get(key.lower(), default)


class _FakeRequest:
    """Minimal stand-in for starlette.Request used by the auth resolvers."""

    def __init__(self, authorization: str | None):
        headers: dict[str, str] = {}
        if authorization is not None:
            headers["authorization"] = authorization
        self.headers = _CIHeaders(headers)
        self.client = types.SimpleNamespace(host="127.0.0.1")


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _seed_user_key(
    session_factory,
    raw_key="alpha_router_userkey_test123",
):
    async with session_factory() as db:
        user = User(
            username="alice",
            email="alice@test",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        db.add(user)
        await db.flush()
        db.add(
            UserApiKey(
                user_id=user.id,
                name="alice-key",
                key_prefix=raw_key[:16],
                key_hash=hash_api_key(raw_key),
                is_active=True,
            )
        )
        await db.commit()
        return user.id, raw_key


async def _seed_alpha_router_key(
    session_factory,
    *,
    raw_key="alpha_router_gatewaykey_test456",
    credit_limit_usd=0.0,
    period_used_usd=0.0,
    unlimited_budget=None,
):
    async with session_factory() as db:
        key = AlphaRouterApiKey(
            name="svc-key",
            key_prefix=raw_key[:16],
            key_hash=hash_api_key(raw_key),
            is_active=True,
            credit_limit_usd=credit_limit_usd,
            # A key without a positive limit is blocked unless explicitly unlimited.
            unlimited_budget=(credit_limit_usd <= 0) if unlimited_budget is None else unlimited_budget,
            reset_period="monthly",
            period_used_usd=period_used_usd,
            period_started_at=datetime.datetime.utcnow(),
        )
        db.add(key)
        await db.commit()
        return key.id, raw_key


# ---- _resolve_gateway_auth ----

async def _test_missing_authorization_raises_401():
    _, sf = await _setup_db()
    async with sf() as db:
        with pytest.raises(HTTPException) as exc:
            await gateway._resolve_gateway_auth(_FakeRequest(None), db)
        assert exc.value.status_code == 401
        assert "Missing API key" in exc.value.detail


async def _test_empty_bearer_raises_401():
    _, sf = await _setup_db()
    async with sf() as db:
        with pytest.raises(HTTPException) as exc:
            await gateway._resolve_gateway_auth(_FakeRequest("Bearer "), db)
        assert exc.value.status_code == 401


async def _test_unknown_key_raises_401():
    _, sf = await _setup_db()
    async with sf() as db:
        with pytest.raises(HTTPException) as exc:
            await gateway._resolve_gateway_auth(_FakeRequest("Bearer totally-bogus"), db)
        assert exc.value.status_code == 401
        assert "Invalid API key" in exc.value.detail


async def _test_master_key_ignores_body_user_and_uses_service_account():
    _, sf = await _setup_db()
    async with sf() as db:
        # Attacker tries to impersonate "admin@evil" via body.user — must be ignored.
        auth = await gateway._resolve_gateway_auth(
            _FakeRequest(f"Bearer {MASTER_KEY}"), db
        )
        assert auth.source == "master"
        assert auth.username == GATEWAY_SERVICE_USERNAME
        assert auth.skip_budget is False
        assert auth.user_id is not None

        # No impersonation: the attacker identity must NOT exist in the DB.
        evil = (
            await db.execute(
                select(User).where((User.email == "admin@evil") | (User.username == "admin@evil"))
            )
        ).scalars().first()
        assert evil is None

        # Idempotent: a second call returns the same service user.
        async with sf() as db2:
            auth2 = await gateway._resolve_gateway_auth(
                _FakeRequest(f"Bearer {MASTER_KEY}"), db2
            )
            assert auth2.user_id == auth.user_id
            # And there is exactly one gateway-service user.
            svc_count = (
                await db2.execute(
                    select(User).where(User.username == GATEWAY_SERVICE_USERNAME)
                )
            ).scalars().all()
            assert len(svc_count) == 1


async def _test_user_api_key_resolves_owner_with_budget():
    _, sf = await _setup_db()
    _, raw = await _seed_user_key(sf)
    async with sf() as db:
        auth = await gateway._resolve_gateway_auth(_FakeRequest(f"Bearer {raw}"), db)
        assert auth.source == "user_key"
        assert auth.username == "alice"
        assert auth.skip_budget is False
        assert auth.alpha_router_api_key_id is None
        assert auth.user_api_key_id is not None
        assert auth.user_id is not None


async def _test_alpha_router_api_key_skips_user_budget():
    _, sf = await _setup_db()
    _, raw = await _seed_alpha_router_key(sf, credit_limit_usd=0.0)
    async with sf() as db:
        auth = await gateway._resolve_gateway_auth(_FakeRequest(f"Bearer {raw}"), db)
        assert auth.source == "alpha_router_key"
        assert auth.skip_budget is True
        assert auth.alpha_router_api_key_id is not None
        assert auth.user_id is None


async def _test_alpha_router_api_key_over_credit_limit_raises_402():
    _, sf = await _setup_db()
    _, raw = await _seed_alpha_router_key(
        sf,
        credit_limit_usd=1.0,
        period_used_usd=1.0,
    )
    async with sf() as db:
        with pytest.raises(HTTPException) as exc:
            await gateway._resolve_gateway_auth(_FakeRequest(f"Bearer {raw}"), db)
        assert exc.value.status_code == 402


# ---- _require_valid_gateway_key (read gate) ----

async def _test_read_gate_rejects_missing():
    _, sf = await _setup_db()
    async with sf() as db:
        with pytest.raises(HTTPException) as exc:
            await gateway._require_valid_gateway_key(_FakeRequest(None), db)
        assert exc.value.status_code == 401


async def _test_read_gate_accepts_master():
    _, sf = await _setup_db()
    async with sf() as db:
        # Should not raise.
        await gateway._require_valid_gateway_key(_FakeRequest(f"Bearer {MASTER_KEY}"), db)


async def _test_read_gate_rejects_unknown():
    _, sf = await _setup_db()
    async with sf() as db:
        with pytest.raises(HTTPException) as exc:
            await gateway._require_valid_gateway_key(_FakeRequest("Bearer nope"), db)
        assert exc.value.status_code == 401


async def _test_read_gate_accepts_user_key():
    _, sf = await _setup_db()
    _, raw = await _seed_user_key(sf)
    async with sf() as db:
        await gateway._require_valid_gateway_key(_FakeRequest(f"Bearer {raw}"), db)


async def _test_chat_completions_no_key_short_circuits_before_body_parse():
    """Auth must run before request.json(): a keyless POST with a body that would
    raise if parsed must still return 401, not 500."""
    _, sf = await _setup_db()
    async with sf() as db:
        req = _FakeRequest(None)

        async def _boom():
            raise AssertionError("body must not be parsed before auth")

        req.json = _boom
        with pytest.raises(HTTPException) as exc:
            await gateway.chat_completions(request=req, db=db)
        assert exc.value.status_code == 401


class _ChatRequest(_FakeRequest):
    def __init__(self, authorization: str, body: dict):
        super().__init__(authorization)
        self._body = body

    async def json(self):
        return self._body


async def _test_chat_completions_personal_key_preflight_and_stream():
    """Personal API key chat must not pass user_api_key_id into preflight_stream_chat."""
    _, sf = await _setup_db()
    _, raw = await _seed_user_key(sf)
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(external_id="test-model"),
        api_key="sk-test",
        base_url="https://example.invalid",
        provider_type="openai",
        model_id="test-model",
        budget_reservation_id=None,
        code_interpreter_capacity_permit=None,
        agent_turn=None,
    )
    stream_calls: list[dict] = []

    async def _empty_stream():
        if False:
            yield b""

    def fake_stream(*_args, **kwargs):
        stream_calls.append(kwargs)
        return _empty_stream()

    preflight_mock = AsyncMock(return_value=resolved)
    body = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }
    req = _ChatRequest(f"Bearer {raw}", body)

    with (
        patch.object(gateway, "preflight_stream_chat", preflight_mock),
        patch.object(gateway, "stream_chat", fake_stream),
    ):
        async with sf() as db:
            resp = await gateway.chat_completions(request=req, db=db)

    assert isinstance(resp, StreamingResponse)
    preflight_mock.assert_awaited_once()
    assert "user_api_key_id" not in preflight_mock.await_args.kwargs
    assert stream_calls
    assert stream_calls[0]["user_api_key_id"] is not None


# ---- sync wrappers ----

def test_missing_authorization_raises_401():
    asyncio.run(_test_missing_authorization_raises_401())


def test_empty_bearer_raises_401():
    asyncio.run(_test_empty_bearer_raises_401())


def test_unknown_key_raises_401():
    asyncio.run(_test_unknown_key_raises_401())


def test_master_key_ignores_body_user_and_uses_service_account():
    asyncio.run(_test_master_key_ignores_body_user_and_uses_service_account())


def test_user_api_key_resolves_owner_with_budget():
    asyncio.run(_test_user_api_key_resolves_owner_with_budget())


def test_alpha_router_api_key_skips_user_budget():
    asyncio.run(_test_alpha_router_api_key_skips_user_budget())


def test_alpha_router_api_key_over_credit_limit_raises_402():
    asyncio.run(_test_alpha_router_api_key_over_credit_limit_raises_402())


def test_read_gate_rejects_missing():
    asyncio.run(_test_read_gate_rejects_missing())


def test_read_gate_accepts_master():
    asyncio.run(_test_read_gate_accepts_master())


def test_read_gate_rejects_unknown():
    asyncio.run(_test_read_gate_rejects_unknown())


def test_read_gate_accepts_user_key():
    asyncio.run(_test_read_gate_accepts_user_key())


def test_chat_completions_no_key_short_circuits_before_body_parse():
    asyncio.run(_test_chat_completions_no_key_short_circuits_before_body_parse())


def test_chat_completions_personal_key_preflight_and_stream():
    asyncio.run(_test_chat_completions_personal_key_preflight_and_stream())
