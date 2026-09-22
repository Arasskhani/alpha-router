"""The read side of the sign-in history, over the real HTTP stack.

Everything here is a fact about a person, so the tests are about who may
see it, that the filters mean what the page says, that the export carries the
same filter as the page and leaves a record, and that a caller can never
turn the endpoint into an unbounded scan.
"""

from __future__ import annotations

import datetime
import json

import pytest
from sqlalchemy import select

from app.api import sign_in_activity as api
from app.core.security import create_access_token
from app.models.auth_event import AuthEvent
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services.user_role_service import set_user_roles


@pytest.fixture(autouse=True)
def _everything_on_the_test_engine(session_factory, monkeypatch):
    """Two places open a session of their own rather than taking the request's:
    the admin IP guard middleware, and the CSV streamer (so the file does not
    depend on the request session outliving the response). Both must land on
    the test engine, not the configured database."""
    from app.services import admin_ip_allowlist_service

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)
    admin_ip_allowlist_service.invalidate_restriction_cache()
    yield
    admin_ip_allowlist_service.invalidate_restriction_cache()


def _cookie_name() -> str:
    from app.config import get_settings

    return get_settings().session_cookie_name


async def _user(db, username: str, *, roles: list[str] | None = None, provider: str = "local") -> User:
    row = User(username=username, email=f"{username}@test", hashed_password="x", auth_provider=provider, is_active=True)
    db.add(row)
    await db.flush()
    if roles:
        await set_user_roles(db, row, roles)
    await db.commit()
    return row


def _sign_in(client, user: User) -> None:
    client.cookies.set(_cookie_name(), create_access_token(user.username, "user"))


async def _event(db, *, days_old: float = 0, **overrides) -> AuthEvent:
    fields = dict(
        occurred_at=datetime.datetime(2026, 9, 20, 12, 0, 0) - datetime.timedelta(days=days_old),
        username="alice",
        event_type="login_success",
        outcome="success",
        auth_method="local",
        ip="203.0.113.7",
    )
    fields.update(overrides)
    row = AuthEvent(**fields)
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def super_admin(db_session):
    return await _user(db_session, "root", roles=["super_admin"])


@pytest.fixture
async def auditor(db_session):
    return await _user(db_session, "auditor", roles=["read_only_super_admin"])


@pytest.fixture
async def api_key_admin(db_session):
    return await _user(db_session, "keys", roles=["api_keys_full_administrator"])


class TestAccess:
    async def test_anonymous_is_refused(self, client):
        assert (await client.get("/api/admin/sign-in-activity")).status_code == 401

    async def test_a_plain_user_is_refused(self, client, user):
        _sign_in(client, user)
        assert (await client.get("/api/admin/sign-in-activity")).status_code == 403

    async def test_a_scoped_administrator_is_refused(self, client, api_key_admin):
        """Sign-in history is personal data about every account; a role scoped
        to one other menu does not see it."""
        _sign_in(client, api_key_admin)
        assert (await client.get("/api/admin/sign-in-activity")).status_code == 403
        assert (await client.get("/api/admin/sign-in-activity/export.csv")).status_code == 403

    async def test_super_admin_reads(self, client, super_admin):
        _sign_in(client, super_admin)
        resp = await client.get("/api/admin/sign-in-activity")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"items": [], "limit": 100, "offset": 0, "has_more": False}

    async def test_read_only_super_admin_reads_and_exports(self, client, auditor):
        """Reading and exporting are both reads; the auditor role exists for them."""
        _sign_in(client, auditor)
        assert (await client.get("/api/admin/sign-in-activity")).status_code == 200
        assert (await client.get("/api/admin/sign-in-activity/filter-options")).status_code == 200
        resp = await client.get("/api/admin/sign-in-activity/export.csv")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/csv")

    def test_the_routes_are_read_guarded_by_the_sign_in_activity_menu(self):
        """No route here mutates, and every one hangs off the new menu key
        rather than api_logs — so the day the key gets a scoped role, it
        governs exactly this data."""
        import inspect

        for route in api.router.routes:
            methods = getattr(route, "methods", set())
            assert methods == {"GET"}, route.path
            guards = []
            for dep in route.dependant.dependencies:
                if getattr(dep.call, "__name__", "") == "_check":
                    nl = inspect.getclosurevars(dep.call).nonlocals
                    guards.append((nl.get("menu"), bool(nl.get("write"))))
            assert ("sign_in_activity", False) in guards, route.path


class TestList:
    async def test_newest_first_with_id_as_tiebreaker(self, client, db_session, super_admin):
        same = datetime.datetime(2026, 9, 20, 12, 0, 0)
        a = await _event(db_session, occurred_at=same)
        b = await _event(db_session, occurred_at=same)
        older = await _event(db_session, days_old=1)
        await db_session.commit()

        _sign_in(client, super_admin)
        items = (await client.get("/api/admin/sign-in-activity")).json()["items"]
        assert [i["id"] for i in items] == [b.id, a.id, older.id]

    async def test_a_row_carries_every_recorded_fact(self, client, db_session, super_admin):
        row = await _event(
            db_session,
            event_type="login_failed",
            outcome="failure",
            reason_code="bad_password",
            reason_detail="Invalid credentials",
            user_agent="Mozilla/5.0",
            session_id=None,
            correlation_id="corr-1",
            backfilled=True,
            source_event_id=77,
        )
        await db_session.commit()

        _sign_in(client, super_admin)
        item = (await client.get("/api/admin/sign-in-activity")).json()["items"][0]
        assert item == {
            "id": row.id,
            "occurred_at": "2026-09-20T12:00:00",
            "user_id": None,
            "username": "alice",
            "event_type": "login_failed",
            "outcome": "failure",
            "scope": None,
            "reason_code": "bad_password",
            "reason_detail": "Invalid credentials",
            "auth_method": "local",
            "ip": "203.0.113.7",
            "user_agent": "Mozilla/5.0",
            "session_id": None,
            "correlation_id": "corr-1",
            "backfilled": True,
        }

    async def test_paging_says_whether_there_is_more(self, client, db_session, super_admin):
        for _ in range(5):
            await _event(db_session)
        await db_session.commit()

        _sign_in(client, super_admin)
        first = (await client.get("/api/admin/sign-in-activity?limit=2")).json()
        assert len(first["items"]) == 2 and first["has_more"] is True
        last = (await client.get("/api/admin/sign-in-activity?limit=2&offset=4")).json()
        assert len(last["items"]) == 1 and last["has_more"] is False

    async def test_the_page_size_is_bounded(self, client, super_admin):
        _sign_in(client, super_admin)
        assert (await client.get("/api/admin/sign-in-activity?limit=100000")).status_code == 422
        assert (await client.get("/api/admin/sign-in-activity?limit=0")).status_code == 422
        assert (await client.get(f"/api/admin/sign-in-activity?limit={api.MAX_PAGE}")).status_code == 200


class TestFilters:
    @pytest.fixture
    async def corpus(self, db_session, user):
        bob = await _user(db_session, "bob", provider="ldap")
        rows = {
            "alice_ok": await _event(db_session, user_id=user.id, username=user.username),
            "alice_bad": await _event(
                db_session,
                user_id=user.id,
                username=user.username,
                event_type="login_failed",
                outcome="failure",
                reason_code="bad_password",
                ip="198.51.100.9",
                days_old=2,
            ),
            "bob_ok": await _event(
                db_session, user_id=bob.id, username="bob", auth_method="ldap", ip="198.51.100.9", days_old=5
            ),
            "ghost": await _event(
                db_session,
                username="al_ice%",
                event_type="login_failed",
                outcome="failure",
                reason_code="no_such_user",
                days_old=10,
            ),
            "revoked": await _event(
                db_session,
                user_id=bob.id,
                username="bob",
                event_type="session_revoked",
                outcome="n/a",
                scope="all_sessions",
                reason_code="password_changed",
                auth_method="ldap",
                days_old=1,
            ),
        }
        await db_session.commit()
        return rows

    async def _ids(self, client, query: str) -> list[int]:
        resp = await client.get(f"/api/admin/sign-in-activity?{query}")
        assert resp.status_code == 200, resp.text
        return sorted(i["id"] for i in resp.json()["items"])

    async def test_by_user_id(self, client, super_admin, corpus, user):
        _sign_in(client, super_admin)
        assert await self._ids(client, f"user_id={user.id}") == sorted([corpus["alice_ok"].id, corpus["alice_bad"].id])

    async def test_username_is_a_case_insensitive_prefix(self, client, super_admin, corpus):
        _sign_in(client, super_admin)
        assert await self._ids(client, "username=BO") == sorted([corpus["bob_ok"].id, corpus["revoked"].id])

    async def test_a_typed_wildcard_is_a_character(self, client, super_admin, corpus):
        """``%`` and ``_`` in the box must not widen the match."""
        _sign_in(client, super_admin)
        assert await self._ids(client, "username=al_ice%25") == [corpus["ghost"].id]
        assert await self._ids(client, "username=al%25") == []

    async def test_by_event_type_outcome_and_reason(self, client, super_admin, corpus):
        _sign_in(client, super_admin)
        assert await self._ids(client, "event_type=login_failed") == sorted(
            [corpus["alice_bad"].id, corpus["ghost"].id]
        )
        assert await self._ids(client, "outcome=failure&reason_code=no_such_user") == [corpus["ghost"].id]
        assert await self._ids(client, "event_type=session_revoked") == [corpus["revoked"].id]

    async def test_by_method_and_ip(self, client, super_admin, corpus):
        _sign_in(client, super_admin)
        assert await self._ids(client, "auth_method=ldap") == sorted([corpus["bob_ok"].id, corpus["revoked"].id])
        assert await self._ids(client, "ip=198.51.100.9") == sorted([corpus["alice_bad"].id, corpus["bob_ok"].id])

    async def test_by_date_range_inclusive(self, client, super_admin, corpus):
        _sign_in(client, super_admin)
        # alice_bad is 2026-09-18 12:00; bob_ok 2026-09-15; revoked 2026-09-19.
        assert await self._ids(client, "start_date=2026-09-18&end_date=2026-09-19") == sorted(
            [corpus["alice_bad"].id, corpus["revoked"].id]
        )
        assert await self._ids(client, "start_date=2026-09-15&end_date=2026-09-15") == [corpus["bob_ok"].id]

    async def test_an_unknown_catalogue_value_is_a_400_not_an_empty_page(self, client, super_admin):
        _sign_in(client, super_admin)
        for query in ("event_type=logn_success", "outcome=maybe", "reason_code=bad_pw", "auth_method=kerberos"):
            resp = await client.get(f"/api/admin/sign-in-activity?{query}")
            assert resp.status_code == 400, query
        assert (await client.get("/api/admin/sign-in-activity?start_date=2026-13-01")).status_code == 400
        assert (
            await client.get("/api/admin/sign-in-activity?start_date=2026-09-20&end_date=2026-09-01")
        ).status_code == 400

    async def test_the_filter_options_are_the_model_catalogue(self, client, super_admin):
        from app.models.auth_event import AUTH_METHODS, EVENT_TYPES, REASON_CODES

        _sign_in(client, super_admin)
        options = (await client.get("/api/admin/sign-in-activity/filter-options")).json()
        assert options == {
            "event_types": list(EVENT_TYPES),
            "outcomes": ["success", "failure", "n/a"],
            "reason_codes": list(REASON_CODES),
            "auth_methods": list(AUTH_METHODS),
        }


class TestDetail:
    async def test_one_event_with_the_account_as_it_is_now(self, client, db_session, super_admin, user):
        row = await _event(db_session, user_id=user.id, username="old-name")
        user.username = "new-name"
        await db_session.commit()

        _sign_in(client, super_admin)
        body = (await client.get(f"/api/admin/sign-in-activity/{row.id}")).json()
        assert body["username"] == "old-name", "the snapshot is what was true at the time"
        assert body["user"]["username"] == "new-name"
        assert body["user"]["id"] == user.id
        assert body["user"]["is_active"] is True

    async def test_an_event_for_a_gone_account_still_reads(self, client, db_session, super_admin):
        row = await _event(db_session, user_id=None, username="nobody")
        await db_session.commit()
        _sign_in(client, super_admin)
        body = (await client.get(f"/api/admin/sign-in-activity/{row.id}")).json()
        assert body["user"] is None and body["username"] == "nobody"

    async def test_missing_is_404(self, client, super_admin):
        _sign_in(client, super_admin)
        assert (await client.get("/api/admin/sign-in-activity/999999")).status_code == 404


class TestExport:
    async def test_the_file_carries_the_pages_rows_under_the_pages_filter(self, client, db_session, super_admin):
        kept = await _event(db_session, event_type="login_failed", outcome="failure", reason_code="bad_password")
        await _event(db_session)  # a success, filtered out
        await db_session.commit()

        _sign_in(client, super_admin)
        resp = await client.get("/api/admin/sign-in-activity/export.csv?event_type=login_failed")
        assert resp.status_code == 200, resp.text
        assert resp.headers["x-truncated"] == "false"
        assert resp.headers["x-row-count"] == "1"
        assert 'attachment; filename="alpharouter-sign-in-activity-' in resp.headers["content-disposition"]

        text = resp.content.decode("utf-8")
        assert text.startswith("﻿"), "BOM so Excel opens it as UTF-8"
        lines = text.lstrip("﻿").splitlines()
        assert lines[0].split(",") == list(api.CSV_COLUMNS)
        assert len(lines) == 2
        assert f",{kept.event_type},failure," in lines[1]
        assert "bad_password" in lines[1]

    async def test_the_export_is_written_to_the_administrative_trail_first(self, client, db_session, super_admin):
        await _event(db_session, ip="198.51.100.9")
        await _event(db_session, ip="198.51.100.9")
        await db_session.commit()

        _sign_in(client, super_admin)
        resp = await client.get("/api/admin/sign-in-activity/export.csv?ip=198.51.100.9&start_date=2026-09-01")
        assert resp.status_code == 200

        rows = (
            (
                await db_session.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "sign_in_activity_exported")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].actor_username == "root"
        assert rows[0].resource_type == "auth_events"
        detail = json.loads(rows[0].detail_json)
        assert detail == {
            "filters": {"ip": "198.51.100.9", "start_date": "2026-09-01"},
            "rows": 2,
            "truncated": False,
        }
        # The filter is recorded, never the names or addresses in the file.
        assert "alice" not in rows[0].detail_json

    async def test_the_export_is_bounded_and_says_so(self, client, db_session, super_admin, monkeypatch):
        monkeypatch.setattr(api, "EXPORT_MAX_ROWS", 3)
        monkeypatch.setattr(api, "_EXPORT_BATCH", 2)
        for _ in range(5):
            await _event(db_session)
        await db_session.commit()

        _sign_in(client, super_admin)
        resp = await client.get("/api/admin/sign-in-activity/export.csv")
        assert resp.headers["x-truncated"] == "true"
        assert resp.headers["x-row-count"] == "3"
        lines = resp.content.decode("utf-8").lstrip("﻿").splitlines()
        assert len(lines) == 1 + 3

        audit = (
            (
                await db_session.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "sign_in_activity_exported")
                )
            )
            .scalars()
            .one()
        )
        assert json.loads(audit.detail_json)["truncated"] is True

    async def test_cells_that_a_spreadsheet_would_run_are_neutralised(self, client, db_session, super_admin):
        """A user agent is attacker-controlled text and the file is opened by
        an administrator. ``=HYPERLINK(...)`` in a cell must stay text."""
        await _event(db_session, user_agent='=HYPERLINK("http://evil","click")', username="-alice", ip="+1")
        await db_session.commit()

        _sign_in(client, super_admin)
        text = (await client.get("/api/admin/sign-in-activity/export.csv")).content.decode("utf-8")
        assert "\"'=HYPERLINK(" in text
        assert ",'-alice," in text
        assert ",'+1," in text

    async def test_an_invalid_filter_exports_nothing_and_records_nothing(self, client, db_session, super_admin):
        _sign_in(client, super_admin)
        assert (await client.get("/api/admin/sign-in-activity/export.csv?outcome=nope")).status_code == 400
        rows = (
            (
                await db_session.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "sign_in_activity_exported")
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


class TestMenuWiring:
    def test_the_menu_key_exists_on_both_sides(self):
        from app.services.rbac import MENU_DEFINITIONS, MENU_PATH_PREFIXES, MENUS_BY_CATEGORY, path_to_menu

        assert ("sign_in_activity", "Sign-in Activity", "data_reports") in MENU_DEFINITIONS
        assert MENU_PATH_PREFIXES["sign_in_activity"] == ("/admin/sign-in-activity",)
        assert path_to_menu("/admin/sign-in-activity") == "sign_in_activity"
        assert path_to_menu("/admin/sign-in-activity/") == "sign_in_activity"
        assert "sign_in_activity" in MENUS_BY_CATEGORY["data_reports"]

    def test_super_admin_and_auditor_reach_it_and_nobody_scoped_does(self):
        from app.services.rbac import (
            API_KEY_ADMIN_SLUG,
            READ_ONLY_SUPER_ADMIN_SLUG,
            REPORTS_ACCESS_SLUG,
            SUPER_ADMIN_SLUG,
            can_access_menu,
            user_can_write_menu,
        )

        assert can_access_menu(SUPER_ADMIN_SLUG, "sign_in_activity")
        assert can_access_menu(READ_ONLY_SUPER_ADMIN_SLUG, "sign_in_activity")
        assert not can_access_menu(API_KEY_ADMIN_SLUG, "sign_in_activity")
        assert not can_access_menu(REPORTS_ACCESS_SLUG, "sign_in_activity"), "Reports Access is reports, not people"
        assert not user_can_write_menu([READ_ONLY_SUPER_ADMIN_SLUG], "sign_in_activity")
