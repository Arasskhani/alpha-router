"""Saving the storage and transfer ceilings is recorded, like every other
administrative change.

These fields decide how much of the shared platform a caller may consume: the
per-user and per-project media quotas, the upload and attachment ceilings, and
the Code Interpreter workspace limits that bound what may be sent into a
sandbox. Lowering any of them changes what every user can do. Until now the
save went straight to ``SystemSetting`` and the trail said nothing, so "who
shrank the workspace limit" had no answer.

The before/after pair is read from the stored view rather than the request
body: the services clamp what they are given, and the trail has to say what
actually took effect, not what was asked for.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.api.admin import StorageSettingsPatch, patch_storage_settings
from app.models.security import SecurityAuditEvent


class _Request:
    def __init__(self, host: str = "198.51.100.7") -> None:
        self.client = type("C", (), {"host": host})()
        self.headers: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _no_edge_sync(monkeypatch):
    """The transfer-limit path pokes the TLS edge; there is none in a test."""
    from app.services import tls_edge_service

    async def noop(_db):
        return {"attempted": False, "queued": False, "applied": False, "reason": "test"}

    monkeypatch.setattr(tls_edge_service, "sync_edge_body_limit", noop)

    from app.api import admin as admin_api

    async def noop_schedule():
        return None

    monkeypatch.setattr(admin_api, "refresh_storage_cleanup_schedule", noop_schedule)


async def _save(db, admin, **fields):
    return await patch_storage_settings(
        body=StorageSettingsPatch(**fields),
        request=_Request(),
        db=db,
        admin=admin,
    )


async def _events(db) -> list[SecurityAuditEvent]:
    return (await db.execute(select(SecurityAuditEvent).order_by(SecurityAuditEvent.id))).scalars().all()


async def test_changing_the_workspace_limits_is_recorded_with_both_values(db_session, admin):
    await _save(db_session, admin, max_code_interpreter_workspace_files=10)
    await _save(db_session, admin, max_code_interpreter_workspace_files=3)

    events = await _events(db_session)
    assert [e.action for e in events] == ["storage_settings_changed"] * 2
    assert events[-1].resource_type == "storage_settings"
    assert events[-1].actor_username == admin.username
    assert events[-1].actor_ip == "198.51.100.7"
    detail = json.loads(events[-1].detail_json)
    assert detail["before"]["max_code_interpreter_workspace_files"] == 10
    assert detail["after"]["max_code_interpreter_workspace_files"] == 3


async def test_the_quotas_and_retention_are_covered_by_the_same_event(db_session, admin):
    """One save, one event: four rows describing one operator action read worse
    than one row describing all of it."""
    await _save(db_session, admin, retention_days=45, user_media_quota_gb=9, project_media_quota_gb=4)

    detail = json.loads((await _events(db_session))[-1].detail_json)
    assert detail["after"]["retention_days"] == 45
    assert detail["after"]["user_media_quota_gb"] == 9
    assert detail["after"]["project_media_quota_gb"] == 4


async def test_the_trail_reports_the_stored_value_not_the_requested_one(db_session, admin):
    """``retention_days`` is clamped to at least 1; the event says 1, not 0."""
    await _save(db_session, admin, retention_days=0)
    detail = json.loads((await _events(db_session))[-1].detail_json)
    assert detail["requested"]["retention_days"] == 0
    assert detail["after"]["retention_days"] == 1


async def test_a_save_that_changes_nothing_writes_no_event(db_session, admin):
    """An empty PATCH is not an administrative act and must not pad the trail."""
    await _save(db_session, admin)
    assert await _events(db_session) == []
