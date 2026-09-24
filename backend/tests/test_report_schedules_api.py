"""The scheduled reports API.

A schedule of one's own used to take only an active account, so anyone could
have any report - the whole organisation's usage - mailed to them once
sending was wired up. It takes what running reports takes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.system import ReportSchedule
from app.models.user import User, UserRoleAssignment

BASE = "/api/admin/reports"
SCHEDULES = f"{BASE}/schedules"


@pytest.fixture(autouse=True)
def _guard_on_the_test_engine(session_factory, monkeypatch):
    from app.services import admin_ip_allowlist_service

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    admin_ip_allowlist_service.invalidate_restriction_cache()
    yield
    admin_ip_allowlist_service.invalidate_restriction_cache()


def _sign_in(client, username: str) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(username, "user"))
    client.cookies.set(settings.csrf_cookie_name, "csrf-token")
    return {settings.csrf_header_name: "csrf-token"}


async def _account(db, username: str, role: str | None) -> User:
    person = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(person)
    await db.flush()
    if role:
        db.add(UserRoleAssignment(user_id=person.id, role_slug=role))
    await db.commit()
    return person


def _body(**values) -> dict:
    return {
        "report_type": "org_cost_summary",
        "cron_expression": "0 9 * * 1",
        "recipients": "a@example.com; b@example.com",
        "format": "pdf",
        **values,
    }


async def _rows(db) -> list[ReportSchedule]:
    """The saved schedules as the database has them now (the API wrote them in another session)."""
    query = select(ReportSchedule).order_by(ReportSchedule.id).execution_options(populate_existing=True)
    return list((await db.execute(query)).scalars())


class TestOwnSchedules:
    async def test_someone_without_reports_access_cannot_schedule_one_to_themselves(self, client, db_session):
        """It used to take only an active account: any user could have the
        whole organisation's usage mailed to them once sending was wired up."""
        person = await _account(db_session, "person", None)
        headers = _sign_in(client, person.username)
        resp = await client.post(f"{SCHEDULES}/user", json=_body(recipients=person.email), headers=headers)
        assert resp.status_code == 403
        assert await _rows(db_session) == []

    async def test_read_only_reports_access_is_not_enough(self, client, db_session):
        viewer = await _account(db_session, "viewer", "read_only_super_admin")
        headers = _sign_in(client, viewer.username)
        resp = await client.post(f"{SCHEDULES}/user", json=_body(recipients=viewer.email), headers=headers)
        assert resp.status_code == 403
        assert await _rows(db_session) == []

    async def test_a_reports_administrator_can_schedule_one_to_their_own_address(self, client, db_session):
        analyst = await _account(db_session, "analyst", "reports_full_administrator")
        headers = _sign_in(client, analyst.username)
        resp = await client.post(f"{SCHEDULES}/user", json=_body(recipients=analyst.email), headers=headers)
        assert resp.status_code == 200, resp.text
        [row] = await _rows(db_session)
        assert row.owner_user_id == analyst.id

    async def test_only_to_their_own_address(self, client, db_session):
        analyst = await _account(db_session, "analyst", "reports_full_administrator")
        headers = _sign_in(client, analyst.username)
        resp = await client.post(
            f"{SCHEDULES}/user", json=_body(recipients=f"{analyst.email}, boss@example.com"), headers=headers
        )
        assert resp.status_code == 400
        assert await _rows(db_session) == []
