"""The filter panel must not scan the audit table four times per open.

``GET /admin-logs/filter-options`` runs four SELECT DISTINCTs over
``security_audit_events`` - action, resource_type, actor_username, and the
usernames behind the legacy actor ids. Two of those columns had no index at
all, so each was a sequential scan of the whole table, and the panel runs them
again every time it is opened.

The values themselves barely change: a handful of action names and resource
types, and the set of administrators. That is a cache, and the columns behind
it should be indexed either way.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api import admin_logs
from app.api.admin_logs import admin_log_filter_options
from app.models.security import SecurityAuditEvent


class _CountingSession:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.executions = 0

    async def execute(self, *args, **kwargs):
        self.executions += 1
        return await self._inner.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _event(**overrides) -> SecurityAuditEvent:
    values = {
        "action": "user_roles_changed",
        "resource_type": "user",
        "actor_username": "alice",
    }
    values.update(overrides)
    return SecurityAuditEvent(**values)


@pytest.fixture
def seeded_options(db_session):
    async def seed() -> None:
        db_session.add_all(
            [
                _event(),
                _event(action="model_access_changed", resource_type="model", actor_username="bob"),
            ]
        )
        await db_session.commit()

    return seed


async def test_the_second_open_does_not_touch_the_table(db_session, seeded_options):
    await seeded_options()

    first = _CountingSession(db_session)
    warm = await admin_log_filter_options(db=first, _=None, source=None)
    assert first.executions >= 1

    second = _CountingSession(db_session)
    cached = await admin_log_filter_options(db=second, _=None, source=None)

    assert cached == warm
    assert second.executions == 0, f"the cached panel still ran {second.executions} statements"


async def test_the_cache_expires(db_session, seeded_options, monkeypatch):
    await seeded_options()
    await admin_log_filter_options(db=db_session, _=None, source=None)

    db_session.add(_event(action="api_key_created", resource_type="api_key", actor_username="carol"))
    await db_session.commit()

    monkeypatch.setattr(admin_logs, "FILTER_OPTIONS_CACHE_TTL_SECONDS", 0)
    admin_logs.reset_filter_options_cache()
    fresh = await admin_log_filter_options(db=db_session, _=None, source=None)

    assert "carol" in fresh["actors"]
    assert "api_key_created" in fresh["actions"]


async def test_the_answer_is_still_right(db_session, seeded_options):
    await seeded_options()

    options = await admin_log_filter_options(db=db_session, _=None, source=None)

    assert options["actions"] == ["model_access_changed", "user_roles_changed"]
    assert options["resource_types"] == ["model", "user"]
    assert options["actors"] == ["alice", "bob"]


@pytest.mark.parametrize("column", ["resource_type", "actor_username"])
def test_the_scanned_columns_are_indexed(column):
    """An index-only scan beats a sequential one even behind a cache."""

    leading = {next(iter(index.columns)).name for index in SecurityAuditEvent.__table__.indexes if index.columns}
    assert column in leading, f"SELECT DISTINCT {column} has no index to read"


async def test_a_write_does_not_have_to_wait_for_the_cache(db_session, seeded_options):
    """The cache is read-through and never blocks a writer."""

    await seeded_options()
    await admin_log_filter_options(db=db_session, _=None, source=None)

    db_session.add(_event(action="later_action"))
    await db_session.commit()

    rows = (await db_session.execute(select(SecurityAuditEvent))).scalars().all()
    assert any(row.action == "later_action" for row in rows)
