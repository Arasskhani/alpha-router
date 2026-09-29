"""Every change made on Admin -> Memory is in Admin Logs.

Saving the memory settings, rebuilding the index and purging a person's
memories were not recorded anywhere: who switched learning off for everyone,
or raised the monthly cap, could not be answered.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.security import SecurityAuditEvent


@pytest.fixture(autouse=True)
def _on_the_test_engine(session_factory, monkeypatch):
    from app.database import get_read_db
    from app.main import app as fastapi_app
    from app.services import admin_ip_allowlist_service

    async def _read_db():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setitem(fastapi_app.dependency_overrides, get_read_db, _read_db)
    admin_ip_allowlist_service.invalidate_restriction_cache()
    yield
    admin_ip_allowlist_service.invalidate_restriction_cache()


@pytest.fixture
def signed_in(client, admin) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(admin.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, "csrf-token")
    return {settings.csrf_header_name: "csrf-token"}


async def _rows(db, action: str) -> list[SecurityAuditEvent]:
    stmt = select(SecurityAuditEvent).where(SecurityAuditEvent.action == action)
    return list((await db.execute(stmt)).scalars())


async def test_a_settings_save_is_recorded_with_what_changed(client, db_session, admin, signed_in):
    saved = await client.patch(
        "/api/admin/memory/settings",
        json={"extract_max_tokens": 3000, "history_completion_enabled": False, "max_per_user": 200},
        headers=signed_in,
    )
    assert saved.status_code == 200, saved.text
    rows = await _rows(db_session, "memory_settings_changed")
    assert len(rows) == 1
    assert rows[0].actor_user_id == admin.id
    assert json.loads(rows[0].detail_json)["changes"] == {
        "extract_max_tokens": {"from": 2000, "to": 3000},
        "history_completion_enabled": {"from": True, "to": False},
    }


async def test_a_save_that_changes_nothing_is_not(client, db_session, signed_in):
    assert (await client.patch("/api/admin/memory/settings", json={"max_per_user": 200}, headers=signed_in)).is_success
    assert await _rows(db_session, "memory_settings_changed") == []


async def test_a_refused_save_is_not(client, db_session, signed_in):
    refused = await client.patch("/api/admin/memory/settings", json={"extraction_model_id": 999}, headers=signed_in)
    assert refused.status_code == 400
    assert await _rows(db_session, "memory_settings_changed") == []


async def test_purging_a_person_and_rebuilding_the_index_are_recorded(client, db_session, user, signed_in, monkeypatch):
    async def _reindex(_db):
        return {"indexed": 3, "version": 2}

    monkeypatch.setattr("app.api.admin_memory.reindex_all_memories", _reindex)
    assert (await client.post(f"/api/admin/memory/purge-user/{user.id}", headers=signed_in)).is_success
    assert (await client.post("/api/admin/memory/reindex", headers=signed_in)).is_success
    purged = await _rows(db_session, "memory_user_purged")
    assert [row.resource_id for row in purged] == [str(user.id)]
    assert json.loads(purged[0].detail_json) == {"user_id": user.id, "deleted": 0}
    rebuilt = await _rows(db_session, "memory_index_rebuilt")
    assert json.loads(rebuilt[0].detail_json) == {"indexed": 3, "version": 2}
