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

from app.api.admin_logs import _apply_filters, _parse_date, _resolve_legacy_actors, _row
from app.database import Base
from app.models.security import SecurityAuditEvent
from app.models.user import User


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
        assert _row(_event(), {})["detail"] == {"https_port": 443}

    def test_a_row_whose_detail_will_not_parse_is_still_listed(self):
        """Dropping an event from the trail because one column is malformed
        would be the worst possible failure mode for an audit view."""
        out = _row(_event(detail_json="{not json"), {})
        assert out["detail"] == {"_unparsed": "{not json"}

    def test_a_redacted_row_says_so(self):
        """So the operator can tell 'nothing was recorded' from 'it aged out'."""
        out = _row(_event(detail_json=None, detail_redacted_at=datetime.datetime(2026, 9, 15, 4, 25)), {})
        assert out["detail"] is None
        assert out["detail_redacted_at"] == "2026-09-15T04:25:00"

    def test_timestamps_are_naive_utc_with_no_suffix(self):
        """The frontend appends Z itself; a mixed wire format across the admin
        API is how a viewer ends up 3.5 hours out in Tehran."""
        assert _row(_event(), {})["created_at"] == "2026-09-10T12:00:00"
        assert not _row(_event(), {})["created_at"].endswith("Z")

    def test_the_actor_name_is_served_from_the_row(self):
        out = _row(_event(actor_user_id=None, actor_username="alice"), {})
        assert out["actor_username"] == "alice"
        assert out["actor_resolved_live"] is False


class TestLegacyActorNames:
    """Events written before the identity columns existed name only an id.

    Left alone the viewer shows "User #2" for every one of them, which is the
    question the page is supposed to answer, unanswered.
    """

    async def _user(self, db, **kw) -> User:
        defaults = dict(username="bob", email="bob@test", hashed_password="x", is_active=True)
        defaults.update(kw)
        user = User(**defaults)
        db.add(user)
        await db.flush()
        return user

    async def test_a_legacy_row_is_resolved_to_the_live_name(self, db):
        user = await self._user(db)
        event = _event(actor_user_id=user.id, actor_username=None, actor_email=None)
        db.add(event)
        await db.commit()

        resolved = await _resolve_legacy_actors(db, [event])
        out = _row(event, resolved)
        assert out["actor_username"] == "bob"
        assert out["actor_email"] == "bob@test"
        assert out["actor_resolved_live"] is True

    async def test_a_soft_deleted_account_still_has_a_name(self, db):
        """Deleted Users are soft-deleted rows; only a permanent delete removes
        one, and an admin who was disabled is exactly who you look for."""
        user = await self._user(db, deleted_at=datetime.datetime(2026, 9, 1))
        event = _event(actor_user_id=user.id, actor_username=None)
        db.add(event)
        await db.commit()

        resolved = await _resolve_legacy_actors(db, [event])
        assert _row(event, resolved)["actor_username"] == "bob"

    async def test_a_permanently_deleted_actor_has_no_name_to_find(self, db):
        """Honest, not clever: the name was never recorded and the account is
        gone, so the id is genuinely all that is left."""
        event = _event(actor_user_id=999, actor_username=None, actor_email=None)
        db.add(event)
        await db.commit()

        resolved = await _resolve_legacy_actors(db, [event])
        out = _row(event, resolved)
        assert out["actor_username"] is None
        assert out["actor_resolved_live"] is False

    async def test_the_stored_copy_wins_over_the_live_account(self, db):
        """A renamed account must not rewrite what an old event says happened."""
        user = await self._user(db, username="bob-renamed")
        event = _event(actor_user_id=user.id, actor_username="bob", actor_email="bob@test")
        db.add(event)
        await db.commit()

        resolved = await _resolve_legacy_actors(db, [event])
        out = _row(event, resolved)
        assert out["actor_username"] == "bob"
        assert out["actor_resolved_live"] is False

    async def test_one_query_covers_the_whole_page(self, db):
        """The lookup is batched; a per-row query would be N+1 on every page."""
        user = await self._user(db)
        events = [_event(actor_user_id=user.id, actor_username=None) for _ in range(5)]
        db.add_all(events)
        await db.commit()

        resolved = await _resolve_legacy_actors(db, events)
        assert resolved == {user.id: ("bob", "bob@test")}

    async def test_no_query_at_all_when_every_row_carries_its_copy(self, db):
        assert await _resolve_legacy_actors(db, [_event(actor_user_id=1)]) == {}

    async def test_filtering_by_name_finds_legacy_rows(self, db):
        """The list shows the resolved name, so typing it must not hide the row
        it came from - that would be the display and the filter disagreeing."""
        user = await self._user(db)
        db.add_all(
            [
                _event(actor_user_id=user.id, actor_username=None),
                _event(actor_username="alice", actor_user_id=None),
            ]
        )
        await db.commit()

        found = await _rows(db, actor="bob")
        assert len(found) == 1
        assert found[0].actor_user_id == user.id

    async def test_filtering_by_name_still_finds_recorded_rows(self, db):
        await self._user(db)
        db.add_all([_event(actor_username="alice"), _event(actor_username="bob", actor_user_id=None)])
        await db.commit()
        assert len(await _rows(db, actor="alice")) == 1

    async def test_a_legacy_row_is_not_matched_by_another_persons_name(self, db):
        user = await self._user(db)
        await self._user(db, username="carol", email="carol@test")
        db.add(_event(actor_user_id=user.id, actor_username=None))
        await db.commit()
        assert await _rows(db, actor="carol") == []

    async def test_the_combobox_offers_legacy_actors_too(self, db):
        """Otherwise the list omits exactly the administrators on screen, and
        the operator concludes those events cannot be filtered."""
        from app.api.admin_logs import admin_log_filter_options

        user = await self._user(db)
        db.add_all(
            [
                _event(actor_user_id=user.id, actor_username=None),
                _event(actor_username="alice", actor_user_id=None),
            ]
        )
        await db.commit()

        options = await admin_log_filter_options(db=db, _=None)
        assert options["actors"] == ["alice", "bob"]

    async def test_the_combobox_does_not_list_an_actor_twice(self, db):
        from app.api.admin_logs import admin_log_filter_options

        user = await self._user(db)
        db.add_all(
            [
                _event(actor_user_id=user.id, actor_username=None),
                _event(actor_user_id=user.id, actor_username="bob"),
            ]
        )
        await db.commit()

        assert (await admin_log_filter_options(db=db, _=None))["actors"] == ["bob"]


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
