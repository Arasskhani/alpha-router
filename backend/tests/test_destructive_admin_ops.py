"""Irreversible admin operations: typed confirmation verified server-side, audited first.

The endpoint functions are called directly against an in-memory SQLite
schema; FastAPI dependencies are plain parameters here.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.api_key import AlphaRouterApiKey, UserApiKey
from app.models.connection import Connection
from app.models.logging import RequestLog
from app.models.media import MediaAsset
from app.models.security import SecurityAuditEvent
from app.models.user import User


def _request():
    return SimpleNamespace(client=SimpleNamespace(host="10.1.2.3"), headers={})


async def _db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _admin(db):
    u = User(username="root", email="root@t", hashed_password="x", auth_provider="local", is_active=True)
    db.add(u)
    await db.flush()
    return u


async def _events(db, action):
    rows = (await db.execute(select(SecurityAuditEvent).where(SecurityAuditEvent.action == action))).scalars().all()
    return [(r.resource_id, json.loads(r.detail_json)) for r in rows]


def test_clear_all_logs_needs_phrase_and_records_row_count():
    from app.api.logs import CLEAR_ALL_LOGS_PHRASE, ClearLogsIn, clear_admin_logs

    async def run():
        factory, engine = await _db()
        try:
            async with factory() as db:
                admin = await _admin(db)
                for i in range(3):
                    db.add(RequestLog(model_id=f"m{i}", user_id=admin.id))
                await db.commit()

                with pytest.raises(HTTPException) as exc:
                    await clear_admin_logs(ClearLogsIn(confirm=""), _request(), db, admin, admin)
                assert exc.value.status_code == 400
                with pytest.raises(HTTPException):
                    await clear_admin_logs(ClearLogsIn(confirm="delete all logs"), _request(), db, admin, admin)
                assert len((await db.execute(select(RequestLog))).scalars().all()) == 3
                assert await _events(db, "request_logs_cleared_all") == []

                out = await clear_admin_logs(ClearLogsIn(confirm=CLEAR_ALL_LOGS_PHRASE), _request(), db, admin, admin)
                assert out["deleted"] == 3
                assert (await db.execute(select(RequestLog))).scalars().all() == []
                events = await _events(db, "request_logs_cleared_all")
                assert events == [(None, {"row_count": 3})]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_clear_all_media_needs_phrase_and_records_count_and_bytes():
    from app.api import admin as admin_api

    async def run():
        factory, engine = await _db()
        try:
            async with factory() as db:
                admin = await _admin(db)
                for i in range(2):
                    db.add(MediaAsset(user_id=admin.id, file_name=f"f{i}", storage_path=f"cdn/u/{i}", size_bytes=1000 + i))
                await db.commit()

                with pytest.raises(HTTPException) as exc:
                    await admin_api.admin_clear_storage_cache(
                        admin_api.DestructiveConfirmIn(confirm="nope"), _request(), db, admin, admin
                    )
                assert exc.value.status_code == 400
                assert len((await db.execute(select(MediaAsset))).scalars().all()) == 2

                with patch("app.services.storage_service.oss.delete_object"):
                    out = await admin_api.admin_clear_storage_cache(
                        admin_api.DestructiveConfirmIn(confirm=admin_api.CLEAR_ALL_MEDIA_PHRASE),
                        _request(), db, admin, admin,
                    )
                assert out["removed_files"] == 2
                events = await _events(db, "media_cleared_all")
                assert events == [(None, {"asset_count": 2, "total_bytes": 2001})]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_connection_and_key_deletions_leave_an_audit_row_that_survives():
    from app.api import admin as admin_api

    async def run():
        factory, engine = await _db()
        try:
            async with factory() as db:
                admin = await _admin(db)
                conn = Connection(name="OpenRouter prod", provider_type="openrouter", api_key_encrypted="enc", is_active=True)
                db.add(conn)
                await db.flush()
                key = AlphaRouterApiKey(
                    name="ci-bot", key_prefix="ar_abc123", key_hash="h" * 20, owner_user_id=admin.id,
                    credit_limit_usd=25.0, is_active=True,
                )
                db.add(key)
                await db.flush()
                ukey = UserApiKey(user_id=admin.id, name="personal", key_prefix="uk_1", key_hash="k" * 20)
                db.add(ukey)
                await db.commit()
                conn_id, key_id, ukey_id = conn.id, key.id, ukey.id

                await admin_api.delete_connection(conn_id, _request(), db, admin)
                await admin_api.delete_alpha_router_key(key_id, _request(), db, admin)
                await admin_api.delete_user_api_key(ukey_id, _request(), db, admin)

                assert await db.get(Connection, conn_id) is None
                assert await db.get(AlphaRouterApiKey, key_id) is None
                assert await db.get(UserApiKey, ukey_id) is None

                (rid, detail), = await _events(db, "connection_deleted")
                assert rid == str(conn_id)
                assert detail["name"] == "OpenRouter prod" and detail["provider_type"] == "openrouter"
                assert "api_key" not in json.dumps(detail).lower().replace("api_key_encrypted", "")

                (rid, detail), = await _events(db, "api_key_deleted")
                assert rid == str(key_id)
                assert detail["name"] == "ci-bot" and detail["key_prefix"] == "ar_abc123"
                assert "key_hash" not in detail

                (rid, detail), = await _events(db, "user_api_key_deleted")
                assert rid == str(ukey_id) and detail["user_id"] == admin.id
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_self_service_key_deletion_is_audited():
    from app.api.user_routes import delete_user_key

    async def run():
        factory, engine = await _db()
        try:
            async with factory() as db:
                me = await _admin(db)
                other = User(username="other", email="o@t", hashed_password="x", auth_provider="local", is_active=True)
                db.add(other)
                await db.flush()
                mine = UserApiKey(user_id=me.id, name="mine", key_prefix="uk_2", key_hash="a" * 20)
                theirs = UserApiKey(user_id=other.id, name="theirs", key_prefix="uk_3", key_hash="b" * 20)
                db.add_all([mine, theirs])
                await db.commit()

                with pytest.raises(HTTPException) as exc:
                    await delete_user_key(theirs.id, _request(), me, db)
                assert exc.value.status_code == 404

                await delete_user_key(mine.id, _request(), me, db)
                (rid, detail), = await _events(db, "user_api_key_deleted")
                assert rid == str(mine.id) and detail["self_service"] is True
        finally:
            await engine.dispose()

    asyncio.run(run())
