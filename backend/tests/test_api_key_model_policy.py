"""Model allowlist for gateway API keys."""

import asyncio

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_api_key
from app.database import Base
from app.models.api_key import AlphaRouterApiKey
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.api_key_connection_policy import replace_key_allowed_connections
from app.services.api_key_model_policy import (
    allowed_model_ids_for_key,
    filter_models_for_allowlist,
    model_policy_label,
    replace_key_allowed_models,
)
from app.services.model_access_service import ACCESS_PRIVATE, set_model_access
from app.services.proxy_service import resolve_model_and_key
from app.services.secret_crypto import encrypt_secret


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _connection_record):  # noqa: ARG001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db: AsyncSession, username: str) -> User:
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _conn(db: AsyncSession, name: str) -> Connection:
    c = Connection(
        name=name,
        provider_type="openai",
        api_key_encrypted=encrypt_secret("sk-test"),
        is_active=True,
    )
    db.add(c)
    await db.flush()
    return c


async def _model(db: AsyncSession, conn: Connection, ext: str, *, access: str = "public") -> AIModel:
    m = AIModel(
        connection_id=conn.id,
        external_id=ext,
        display_name=ext,
        provider_type="openai",
        is_enabled=True,
        access_type=access,
    )
    db.add(m)
    await db.flush()
    return m


async def _key(db: AsyncSession, *, owner_id: int | None = None) -> AlphaRouterApiKey:
    key = AlphaRouterApiKey(
        name="svc",
        key_prefix="alpha_router_ab",
        key_hash=hash_api_key("alpha_router_test_model_policy"),
        is_active=True,
        owner_user_id=owner_id,
    )
    db.add(key)
    await db.flush()
    return key


async def _test_unrestricted_key_returns_none_allowlist() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "alice")
            key = await _key(db, owner_id=owner.id)
            assert await allowed_model_ids_for_key(db, key.id) is None
    finally:
        await engine.dispose()


async def _test_restricted_empty_allowlist_is_deny_all() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "alice")
            conn = await _conn(db, "OpenAI")
            key = await _key(db, owner_id=owner.id)
            key.restrict_models = True
            await db.flush()
            m1 = await _model(db, conn, "gpt-4o")
            allowed = await allowed_model_ids_for_key(db, key.id)
            assert allowed == set()
            assert filter_models_for_allowlist([m1], allowed) == []
    finally:
        await engine.dispose()


async def _test_owner_private_model_denied_for_other_owner() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "owner")
            other = await _user(db, "other")
            conn = await _conn(db, "OpenAI")
            private = await _model(db, conn, "secret-model", access=ACCESS_PRIVATE)
            await set_model_access(db, private, access_type=ACCESS_PRIVATE, user_ids=[owner.id])
            key = await _key(db, owner_id=other.id)
            try:
                await replace_key_allowed_models(
                    db, key, restrict=True, model_ids=[private.id]
                )
            except ValueError as exc:
                assert "Owner cannot access model" in str(exc)
            else:
                raise AssertionError("expected ValueError")
    finally:
        await engine.dispose()


async def _test_model_must_be_on_allowed_connection() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "alice")
            openai = await _conn(db, "OpenAI")
            anthropic = await _conn(db, "Anthropic")
            model = await _model(db, anthropic, "claude-3")
            key = await _key(db, owner_id=owner.id)
            await replace_key_allowed_connections(
                db, key, restrict=True, connection_ids=[openai.id]
            )
            try:
                await replace_key_allowed_models(
                    db, key, restrict=True, model_ids=[model.id]
                )
            except ValueError as exc:
                assert "allowed connection" in str(exc)
            else:
                raise AssertionError("expected ValueError")
    finally:
        await engine.dispose()


async def _test_resolve_respects_model_allowlist() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "alice")
            conn = await _conn(db, "OpenAI")
            allowed = await _model(db, conn, "gpt-4o")
            await _model(db, conn, "gpt-4o-mini")
            key = await _key(db, owner_id=owner.id)
            await replace_key_allowed_models(
                db, key, restrict=True, model_ids=[allowed.id]
            )
            allowlist = await allowed_model_ids_for_key(db, key.id)
            row, _, _, _ = await resolve_model_and_key(
                db, "gpt-4o", allowed_model_ids=allowlist
            )
            assert row is not None
            assert row.id == allowed.id
            missing, _, _, _ = await resolve_model_and_key(
                db, "gpt-4o-mini", allowed_model_ids=allowlist
            )
            assert missing is None
    finally:
        await engine.dispose()


async def _test_gateway_models_list_respects_model_allowlist() -> None:
    from app.api import gateway

    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            owner = await _user(db, "alice")
            conn = await _conn(db, "OpenAI")
            m1 = await _model(db, conn, "gpt-4o")
            await _model(db, conn, "gpt-4o-mini")
            raw = "alpha_router_gateway_model_test"
            key = AlphaRouterApiKey(
                name="svc",
                key_prefix=raw[:16],
                key_hash=hash_api_key(raw),
                is_active=True,
                owner_user_id=owner.id,
            )
            db.add(key)
            await db.flush()
            await replace_key_allowed_models(
                db, key, restrict=True, model_ids=[m1.id]
            )
            await db.commit()

            class _Headers:
                def __init__(self, items):
                    self._items = {k.lower(): v for k, v in items.items()}

                def get(self, key, default=None):
                    return self._items.get(key.lower(), default)

            class _Req:
                def __init__(self):
                    self.headers = _Headers({"authorization": f"Bearer {raw}"})
                    self.client = type("C", (), {"host": "127.0.0.1"})()

            payload = await gateway.list_models(request=_Req(), db=db)
            ids = [item["id"] for item in payload["data"]]
            assert ids == ["gpt-4o"]
    finally:
        await engine.dispose()


def test_unrestricted_key_returns_none_allowlist():
    asyncio.run(_test_unrestricted_key_returns_none_allowlist())


def test_restricted_empty_allowlist_is_deny_all():
    asyncio.run(_test_restricted_empty_allowlist_is_deny_all())


def test_owner_private_model_denied_for_other_owner():
    asyncio.run(_test_owner_private_model_denied_for_other_owner())


def test_model_must_be_on_allowed_connection():
    asyncio.run(_test_model_must_be_on_allowed_connection())


def test_resolve_respects_model_allowlist():
    asyncio.run(_test_resolve_respects_model_allowlist())


def test_gateway_models_list_respects_model_allowlist():
    asyncio.run(_test_gateway_models_list_respects_model_allowlist())


def test_model_policy_label():
    assert model_policy_label(False, []) == "All models"
    assert model_policy_label(True, []) == "None"
    assert model_policy_label(True, ["gpt-4o"]) == "gpt-4o"
