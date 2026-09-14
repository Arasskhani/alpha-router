"""Connection allowlist for gateway API keys."""

import asyncio

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_api_key
from app.database import Base
from app.models.api_key import AlphaRouterApiKey
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.api_key_connection_policy import (
    allowed_connection_ids_for_key,
    connection_policy_label,
    filter_models_for_connections,
    replace_key_allowed_connections,
)
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


async def _conn(db: AsyncSession, name: str, *, active: bool = True) -> Connection:
    c = Connection(
        name=name,
        provider_type="openai",
        api_key_encrypted=encrypt_secret("sk-test"),
        is_active=active,
    )
    db.add(c)
    await db.flush()
    return c


async def _model(db: AsyncSession, conn: Connection, ext: str) -> AIModel:
    m = AIModel(
        connection_id=conn.id,
        external_id=ext,
        display_name=ext,
        provider_type="openai",
        is_enabled=True,
    )
    db.add(m)
    await db.flush()
    return m


async def _key(db: AsyncSession, *, restrict: bool = False) -> AlphaRouterApiKey:
    key = AlphaRouterApiKey(
        name="svc",
        key_prefix="alpha_router_ab",
        key_hash=hash_api_key("alpha_router_test_connection_policy"),
        is_active=True,
        restrict_connections=restrict,
    )
    db.add(key)
    await db.flush()
    return key


async def _test_unrestricted_key_returns_none_allowlist() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            key = await _key(db, restrict=False)
            assert await allowed_connection_ids_for_key(db, key.id) is None
            assert await allowed_connection_ids_for_key(db, None) is None
    finally:
        await engine.dispose()


async def _test_restricted_empty_allowlist_is_deny_all() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            key = await _key(db, restrict=True)
            allowed = await allowed_connection_ids_for_key(db, key.id)
            assert allowed == set()
            openai = await _conn(db, "OpenAI")
            other = await _conn(db, "Anthropic")
            m1 = await _model(db, openai, "gpt-4o")
            m2 = await _model(db, other, "claude-3")
            filtered = filter_models_for_connections([m1, m2], allowed)
            assert filtered == []
    finally:
        await engine.dispose()


async def _test_restricted_allowlist_filters_models() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            openai = await _conn(db, "OpenAI")
            other = await _conn(db, "Anthropic")
            key = await _key(db)
            names = await replace_key_allowed_connections(
                db, key, restrict=True, connection_ids=[openai.id]
            )
            assert names == ["OpenAI"]
            allowed = await allowed_connection_ids_for_key(db, key.id)
            assert allowed == {openai.id}
            m1 = await _model(db, openai, "gpt-4o")
            m2 = await _model(db, other, "claude-3")
            filtered = filter_models_for_connections([m1, m2], allowed)
            assert [m.external_id for m in filtered] == ["gpt-4o"]
    finally:
        await engine.dispose()


async def _test_clearing_restriction_does_not_keep_join_rows() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            openai = await _conn(db, "OpenAI")
            key = await _key(db)
            await replace_key_allowed_connections(
                db, key, restrict=True, connection_ids=[openai.id]
            )
            await replace_key_allowed_connections(
                db, key, restrict=False, connection_ids=[openai.id]
            )
            assert key.restrict_connections is False
            assert await allowed_connection_ids_for_key(db, key.id) is None
    finally:
        await engine.dispose()


async def _test_deleted_connection_keeps_key_restricted() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            openai = await _conn(db, "OpenAI")
            key = await _key(db)
            await replace_key_allowed_connections(
                db, key, restrict=True, connection_ids=[openai.id]
            )
            await db.delete(openai)
            await db.flush()
            allowed = await allowed_connection_ids_for_key(db, key.id)
            assert key.restrict_connections is True
            assert allowed == set()
            assert connection_policy_label(True, []) == "None"
    finally:
        await engine.dispose()


async def _test_unknown_connection_id_raises() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            key = await _key(db)
            try:
                await replace_key_allowed_connections(
                    db, key, restrict=True, connection_ids=[999]
                )
            except ValueError as exc:
                assert "999" in str(exc)
            else:
                raise AssertionError("expected ValueError")
    finally:
        await engine.dispose()


async def _test_resolve_uses_allowed_connection_for_duplicate_ids() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            first = await _conn(db, "First")
            second = await _conn(db, "Second")
            await _model(db, first, "gpt-4o")
            wanted = await _model(db, second, "gpt-4o")
            row, _, _, _ = await resolve_model_and_key(
                db, "gpt-4o", allowed_connection_ids={second.id}
            )
            assert row is not None
            assert row.id == wanted.id
            missing, _, _, _ = await resolve_model_and_key(
                db, "gpt-4o", allowed_connection_ids={999}
            )
            assert missing is None
            none, _, _, _ = await resolve_model_and_key(
                db, "gpt-4o", allowed_connection_ids=set()
            )
            assert none is None
    finally:
        await engine.dispose()


async def _test_gateway_models_list_respects_allowlist() -> None:
    from app.api import gateway

    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            openai = await _conn(db, "OpenAI")
            other = await _conn(db, "Anthropic")
            await _model(db, openai, "gpt-4o")
            await _model(db, other, "claude-3")
            raw = "alpha_router_gateway_conn_test"
            key = AlphaRouterApiKey(
                name="svc",
                key_prefix=raw[:16],
                key_hash=hash_api_key(raw),
                is_active=True,
                unlimited_budget=True,  # no cap must now be explicit
            )
            db.add(key)
            await db.flush()
            await replace_key_allowed_connections(
                db, key, restrict=True, connection_ids=[openai.id]
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


def test_restricted_allowlist_filters_models():
    asyncio.run(_test_restricted_allowlist_filters_models())


def test_clearing_restriction_does_not_keep_join_rows():
    asyncio.run(_test_clearing_restriction_does_not_keep_join_rows())


def test_deleted_connection_keeps_key_restricted():
    asyncio.run(_test_deleted_connection_keeps_key_restricted())


def test_unknown_connection_id_raises():
    asyncio.run(_test_unknown_connection_id_raises())


def test_resolve_uses_allowed_connection_for_duplicate_ids():
    asyncio.run(_test_resolve_uses_allowed_connection_for_duplicate_ids())


def test_gateway_models_list_respects_allowlist():
    asyncio.run(_test_gateway_models_list_respects_allowlist())
