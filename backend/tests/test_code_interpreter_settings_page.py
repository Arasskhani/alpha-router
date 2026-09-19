"""One answer for everything that governs Code Interpreter.

The settings were spread over three pages and two permissions: the concurrency
policy on Operations, the workspace limits on Storage Management, and the
deployment ceilings on neither. An operator tuning the feature had to know
which page held which half, and nothing showed the two ceilings that actually
decide admission side by side.

This endpoint answers with all three families at once, and marks the
deployment ones read-only with the environment variable that sets them, since
naming the variable is the only useful thing a settings page can say about a
value it cannot change.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.api.operations import (
    CodeInterpreterWorkspacePatch,
    get_code_interpreter_settings,
    patch_code_interpreter_workspace,
)
from app.models.security import SecurityAuditEvent


class _Request:
    def __init__(self, host: str = "203.0.113.9") -> None:
        self.client = type("C", (), {"host": host})()
        self.headers: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _no_redis_or_broker(monkeypatch):
    """The page must open whether or not Redis and the broker answer."""

    async def stats():
        return {"active": 2, "limit": 200, "available": 198}

    async def broker():
        return {"status": "ok", "max_concurrent": 50, "in_use": 0, "available": 50, "active_jobs": 0}

    monkeypatch.setattr("app.services.code_interpreter_capacity_service.code_interpreter_capacity_stats", stats)
    monkeypatch.setattr("app.api.operations._sandbox_broker_capacity", broker)


async def test_the_page_answers_with_all_three_families(db_session):
    payload = await get_code_interpreter_settings(db=db_session, _=None)
    assert set(payload) == {"policy", "workspace", "deployment", "effective", "broker"}
    assert set(payload["policy"]) == {
        "enabled",
        "max_concurrent_turns",
        "max_per_subject",
        "retry_after_seconds",
    }
    assert set(payload["workspace"]) == {"max_workspace_files", "max_workspace_total_mb"}


async def test_every_deployment_value_names_the_variable_that_sets_it(db_session):
    """A read-only number with no way to find out where it comes from is worse
    than not showing it."""
    deployment = (await get_code_interpreter_settings(db=db_session, _=None))["deployment"]
    assert set(deployment) == {
        "hard_max_concurrent_turns",
        "lease_ttl_seconds",
        "heartbeat_seconds",
        "execution_timeout_seconds",
        "broker_max_concurrent",
    }
    for entry in deployment.values():
        assert entry["env"] and entry["env"].isupper()
    assert deployment["broker_max_concurrent"]["env"] == "SANDBOX_MAX_CONCURRENT"
    assert deployment["broker_max_concurrent"]["value"] == 50


async def test_the_page_shows_which_of_the_two_gates_binds(db_session):
    effective = (await get_code_interpreter_settings(db=db_session, _=None))["effective"]
    assert effective["limited_by"] == "broker"
    assert effective["max_concurrent_turns"] == 50


async def test_the_page_opens_even_when_redis_is_down(db_session, monkeypatch):
    async def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.services.code_interpreter_capacity_service.code_interpreter_capacity_stats", boom)
    payload = await get_code_interpreter_settings(db=db_session, _=None)
    assert payload["policy"]["max_concurrent_turns"] >= 1


async def test_saving_the_workspace_limits_stores_and_records_them(db_session, admin):
    payload = await patch_code_interpreter_workspace(
        body=CodeInterpreterWorkspacePatch(max_workspace_files=7, max_workspace_total_mb=9),
        request=_Request(),
        db=db_session,
        admin=admin,
    )
    assert payload["workspace"] == {"max_workspace_files": 7, "max_workspace_total_mb": 9}

    event = (await db_session.execute(select(SecurityAuditEvent))).scalars().one()
    assert event.action == "code_interpreter_workspace_changed"
    assert event.resource_type == "code_interpreter"
    assert event.actor_username == admin.username
    detail = json.loads(event.detail_json)
    assert detail["after"]["max_code_interpreter_workspace_files"] == 7


async def test_the_same_limits_read_back_through_the_shared_service(db_session, admin):
    """Storage Management writes the same two keys. One store, two doors: a
    value saved here has to be the value that page shows, or the operator is
    tuning two different things that look like one."""
    from app.services.transfer_limits_service import get_transfer_limits

    await patch_code_interpreter_workspace(
        body=CodeInterpreterWorkspacePatch(max_workspace_files=4, max_workspace_total_mb=6),
        request=_Request(),
        db=db_session,
        admin=admin,
    )
    limits = await get_transfer_limits(db_session)
    assert limits["max_code_interpreter_workspace_files"] == 4
    assert limits["max_code_interpreter_workspace_total_mb"] == 6


def test_the_route_is_reachable_for_the_operations_menu():
    from app.services.rbac import MENU_PATH_PREFIXES

    assert "/admin/code-interpreter" in MENU_PATH_PREFIXES["operations"]


class TestCompatibilityOverrideIsAudited:
    """Pinning a model's Code Interpreter compatibility is an administrative act.

    It was already recorded as an evidence row on the compatibility table, but
    that row names the administrator inside a sentence and carries no user id,
    so "which models did this person pin" had no answer. The security event
    alongside it does, and it reaches Admin Logs like every other change.
    """

    async def _model(self, db):
        from app.models.connection import Connection
        from app.models.model_catalog import AIModel
        from app.services.secret_crypto import encrypt_secret

        connection = Connection(
            name="openai", provider_type="openai", api_key_encrypted=encrypt_secret("sk-test"), is_active=True
        )
        db.add(connection)
        await db.flush()
        model = AIModel(
            connection_id=connection.id, external_id="openai/gpt-4o", provider_type="openai", is_enabled=True
        )
        db.add(model)
        await db.flush()
        return model

    async def _put(self, db, admin, model, override):
        from app.api.admin import ModelCompatibilityOverrideIn, put_model_code_interpreter_compatibility

        return await put_model_code_interpreter_compatibility(
            model_id=model.id,
            body=ModelCompatibilityOverrideIn(override=override),
            request=_Request(),
            db=db,
            actor=admin,
        )

    async def test_pinning_and_releasing_are_both_recorded(self, db_session, admin):
        model = await self._model(db_session)
        await self._put(db_session, admin, model, "incompatible")
        await self._put(db_session, admin, model, "auto")

        events = (await db_session.execute(select(SecurityAuditEvent).order_by(SecurityAuditEvent.id))).scalars().all()
        assert [e.action for e in events] == ["code_interpreter_compatibility_override"] * 2
        assert events[0].resource_type == "model"
        assert events[0].resource_id == str(model.id)
        assert events[0].actor_username == admin.username
        first = json.loads(events[0].detail_json)
        assert (first["before"], first["after"]) == ("auto", "incompatible")
        assert json.loads(events[1].detail_json)["after"] == "auto"

    async def test_saving_the_same_value_twice_does_not_pad_the_trail(self, db_session, admin):
        model = await self._model(db_session)
        await self._put(db_session, admin, model, "compatible")
        await self._put(db_session, admin, model, "compatible")
        events = (await db_session.execute(select(SecurityAuditEvent))).scalars().all()
        assert len(events) == 1
