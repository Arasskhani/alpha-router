"""The read side of the administrative audit trail.

Filtering is the whole point of the endpoint: an investigation starts from a
date, a person, or a kind of action, and before this existed the only way to
answer any of those was a database client.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.admin_logs import _apply_filters, _parse_date, _row
from app.database import Base
from app.models.security import SecurityAuditEvent


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _event(**kw) -> SecurityAuditEvent:
    defaults = dict(
        actor_username="alice",
        actor_email="alice@test",
        actor_ip="10.0.0.1",
        action="tls_activate",
        resource_type="tls_certificate",
        detail_json=json.dumps({"https_port": 443}),
        created_at=datetime.datetime(2026, 9, 10, 12, 0, 0),
    )
    defaults.update(kw)
    return SecurityAuditEvent(**defaults)


async def _rows(db, **filters):
    from sqlalchemy import select

    stmt = _apply_filters(
        select(SecurityAuditEvent),
        actor=filters.get("actor"),
        action=filters.get("action"),
        resource_type=filters.get("resource_type"),
        start=filters.get("start"),
        end=filters.get("end"),
    )
    return (await db.execute(stmt)).scalars().all()


class TestDateParsing:
    def test_a_plain_day_becomes_a_lower_bound(self):
        assert _parse_date("2026-09-10") == datetime.datetime(2026, 9, 10, 0, 0, 0)

    def test_the_end_bound_covers_the_whole_day(self):
        """Otherwise 'to 10 September' silently excludes everything that day."""
        assert _parse_date("2026-09-10", end_of_day=True) == datetime.datetime(2026, 9, 10, 23, 59, 59)

    def test_a_typo_is_a_client_error_not_a_crash(self):
        """The request-log endpoint turns the same mistake into a 500."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _parse_date("10-09-2026")
        assert exc.value.status_code == 400

    def test_no_filter_is_no_bound(self):
        assert _parse_date(None) is None and _parse_date("") is None


class TestFilters:
    async def test_actor_matches_part_of_a_name(self, db):
        db.add_all([_event(actor_username="alice"), _event(actor_username="bob")])
        await db.commit()
        assert [r.actor_username for r in await _rows(db, actor="ali")] == ["alice"]

    async def test_action_matches_exactly(self, db):
        """Substring matching here would make 'tls_delete' also return
        'tls_deactivate' - two very different events."""
        db.add_all([_event(action="tls_delete"), _event(action="tls_deactivate")])
        await db.commit()
        assert [r.action for r in await _rows(db, action="tls_delete")] == ["tls_delete"]

    async def test_resource_type_matches_exactly(self, db):
        db.add_all([_event(resource_type="user"), _event(resource_type="storage")])
        await db.commit()
        assert [r.resource_type for r in await _rows(db, resource_type="user")] == ["user"]

    async def test_a_date_range_is_inclusive_at_both_ends(self, db):
        db.add_all(
            [
                _event(created_at=datetime.datetime(2026, 9, 9, 23, 0)),
                _event(created_at=datetime.datetime(2026, 9, 10, 23, 30)),
                _event(created_at=datetime.datetime(2026, 9, 11, 1, 0)),
            ]
        )
        await db.commit()
        rows = await _rows(db, start=_parse_date("2026-09-10"), end=_parse_date("2026-09-10", end_of_day=True))
        assert len(rows) == 1

    async def test_blank_filters_do_not_narrow_anything(self, db):
        db.add_all([_event(), _event()])
        await db.commit()
        assert len(await _rows(db, actor="   ", action=None)) == 2


class TestSerialisation:
    def test_detail_comes_back_as_an_object(self):
        assert _row(_event())["detail"] == {"https_port": 443}

    def test_a_row_whose_detail_will_not_parse_is_still_listed(self):
        """Dropping an event from the trail because one column is malformed
        would be the worst possible failure mode for an audit view."""
        out = _row(_event(detail_json="{not json"))
        assert out["detail"] == {"_unparsed": "{not json"}

    def test_a_redacted_row_says_so(self):
        """So the operator can tell 'nothing was recorded' from 'it aged out'."""
        out = _row(_event(detail_json=None, detail_redacted_at=datetime.datetime(2026, 9, 15, 4, 25)))
        assert out["detail"] is None
        assert out["detail_redacted_at"] == "2026-09-15T04:25:00"

    def test_timestamps_are_naive_utc_with_no_suffix(self):
        """The frontend appends Z itself; a mixed wire format across the admin
        API is how a viewer ends up 3.5 hours out in Tehran."""
        assert _row(_event())["created_at"] == "2026-09-10T12:00:00"
        assert not _row(_event())["created_at"].endswith("Z")

    def test_the_actor_name_is_served_from_the_row(self):
        out = _row(_event(actor_user_id=None, actor_username="alice"))
        assert out["actor_username"] == "alice"


def test_the_viewer_is_gated_on_an_existing_menu():
    """Reusing api_logs rather than inventing a MenuKey: every role in this
    codebase carries exactly one menu key, so a new one would be visible to
    Super Admin alone and could not be granted to anybody else without a new
    role definition."""
    import inspect

    from app.api import admin_logs

    assert "require_api_logs" in inspect.getsource(admin_logs)


def test_the_route_is_reachable_for_that_menu():
    from app.services.rbac import MENU_PATH_PREFIXES

    assert "/admin/admin-logs" in MENU_PATH_PREFIXES["api_logs"]


def test_paging_orders_by_id_as_well_as_time():
    """Several events share a timestamp to the microsecond; ordering by time
    alone lets a row repeat or vanish between pages."""
    import inspect

    from app.api import admin_logs

    source = inspect.getsource(admin_logs.list_admin_logs)
    assert "SecurityAuditEvent.id.desc()" in source
