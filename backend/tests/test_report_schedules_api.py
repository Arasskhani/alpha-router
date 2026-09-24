"""The scheduled reports API: set up, list, pause, resume, delete, send now.

What the Reports page relies on, and the rules around it: a schedule is
checked the way its runs will use it when it is saved, it knows when it runs
next, every change is in the admin trail, only those who may run reports can
make one, and "send now" sends without moving the next run.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.security import SecurityAuditEvent
from app.models.system import ReportSchedule, SmtpSettings
from app.models.user import User, UserRoleAssignment
from app.services import report_schedule_service as svc
from tests.smtp_test_server import MODE_PLAIN, SmtpTestServer

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
        "period": "previous_month",
        **values,
    }


async def _rows(db) -> list[ReportSchedule]:
    """The saved schedules as the database has them now (the API wrote them in another session)."""
    query = select(ReportSchedule).order_by(ReportSchedule.id).execution_options(populate_existing=True)
    return list((await db.execute(query)).scalars())


async def _trail(db, action: str) -> list[SecurityAuditEvent]:
    found = await db.execute(select(SecurityAuditEvent).where(SecurityAuditEvent.action == action))
    return list(found.scalars())


class TestCreate:
    async def test_a_schedule_is_saved_with_its_next_run(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        before = svc.utcnow()
        resp = await client.post(SCHEDULES, json=_body(), headers=headers)
        assert resp.status_code == 200, resp.text
        [row] = await _rows(db_session)
        assert resp.json()["schedule"]["id"] == row.id
        assert row.owner_user_id is None
        assert row.recipients == "a@example.com,b@example.com"
        assert (row.period, row.format, row.is_active) == ("previous_month", "pdf", True)
        assert row.last_run_at is None and row.last_status is None
        assert before < row.next_run_at <= before + dt.timedelta(days=7, minutes=1)
        assert row.next_run_at == svc.first_run("0 9 * * 1", row.next_run_at - dt.timedelta(days=7))

        [event] = await _trail(db_session, "report_schedule_created")
        assert event.actor_user_id == admin.id
        assert event.resource_type == "report_schedule" and event.resource_id == str(row.id)
        detail = json.loads(event.detail_json)
        assert detail["recipients"] == ["a@example.com", "b@example.com"]
        assert detail["report_type"] == "org_cost_summary"

    async def test_parameters_are_checked_and_kept_tidy(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        resp = await client.post(
            SCHEDULES,
            json=_body(report_type="top_users_by_spend", parameters_json='{"top_n": 5, "department": null}'),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        [row] = await _rows(db_session)
        assert json.loads(row.parameters_json) == {"department": None, "top_n": 5}

    async def test_excel_is_kept_as_xlsx(self, client, admin, db_session):
        headers = _sign_in(client, admin.username)
        assert (await client.post(SCHEDULES, json=_body(format="xls"), headers=headers)).status_code == 200
        [row] = await _rows(db_session)
        assert row.format == "xlsx"

    @pytest.mark.parametrize(
        ("values", "detail"),
        [
            ({"report_type": "plan_usage"}, "plan_id required"),
            ({"parameters_json": '{"colour": "red"}'}, "Unknown report parameter: colour"),
            ({"parameters_json": '{"start_date": "2020-01-01"}'}, "Unknown report parameter: start_date"),
            ({"period": "previous_year"}, "period must be one of"),
            ({"cron_expression": "0 9 30 2 *"}, "never"),
            ({"cron_expression": "0 9 * * 5-1"}, "Invalid cron_expression"),
            ({"cron_expression": "0 9 * *"}, "5 fields"),
            ({"recipients": "a@example.com, not-an-address"}, "Invalid recipient address: not-an-address"),
            ({"recipients": " "}, "At least one recipient"),
            ({"format": "docx"}, "format must be one of"),
            ({"report_type": "nope"}, "Unknown report_type"),
        ],
    )
    async def test_a_mistake_is_refused_when_the_schedule_is_saved(self, client, admin, db_session, values, detail):
        headers = _sign_in(client, admin.username)
        resp = await client.post(SCHEDULES, json=_body(**values), headers=headers)
        assert resp.status_code == 400
        assert detail in resp.json()["detail"]
        assert await _rows(db_session) == []

    async def test_read_only_reports_access_cannot_make_one(self, client, db_session):
        viewer = await _account(db_session, "viewer", "read_only_super_admin")
        headers = _sign_in(client, viewer.username)
        assert (await client.post(SCHEDULES, json=_body(), headers=headers)).status_code == 403
        assert await _rows(db_session) == []


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
        assert resp.json()["schedule"]["owner"] == "analyst"

    async def test_only_to_their_own_address(self, client, db_session):
        analyst = await _account(db_session, "analyst", "reports_full_administrator")
        headers = _sign_in(client, analyst.username)
        resp = await client.post(
            f"{SCHEDULES}/user", json=_body(recipients=f"{analyst.email}, boss@example.com"), headers=headers
        )
        assert resp.status_code == 400
        assert await _rows(db_session) == []


class TestList:
    async def test_the_list_says_what_each_schedule_is_and_how_it_went(self, client, admin, db_session):
        now = svc.utcnow()
        analyst = await _account(db_session, "analyst", "reports_full_administrator")
        db_session.add_all(
            [
                ReportSchedule(
                    report_type="org_cost_summary",
                    cron_expression="0 9 * * 1",
                    recipients="a@example.com",
                    format="pdf",
                    period="previous_month",
                    is_active=True,
                    next_run_at=dt.datetime(2030, 1, 7, 9, 0),
                    last_run_at=dt.datetime(2029, 12, 31, 9, 0),
                    last_status="partial",
                    last_error="gone@example.com: refused",
                    parameters_json='{"top_n": 5}',
                ),
                ReportSchedule(
                    report_type="users_without_budget",
                    cron_expression="0 9 * * *",
                    recipients="analyst@example.com",
                    format="csv",
                    is_active=False,
                    owner_user_id=analyst.id,
                    next_run_at=dt.datetime(2030, 1, 1, 9, 0),
                    last_run_at=now - dt.timedelta(hours=3),
                    last_status="running",
                ),
            ]
        )
        await db_session.commit()
        headers = _sign_in(client, admin.username)
        resp = await client.get(SCHEDULES, headers=headers)
        assert resp.status_code == 200
        first, second = resp.json()
        assert first["report_title"] == "Organization cost summary"
        assert first["needs_date"] is True
        assert first["period"] == "previous_month"
        assert first["parameters"] == {"top_n": 5}
        assert first["owner"] is None
        assert first["next_run_at"] == "2030-01-07T09:00:00Z"
        assert first["next_run_local"] is not None
        assert first["last_run_at"] == "2029-12-31T09:00:00Z"
        assert (first["last_status"], first["last_error"]) == ("partial", "gone@example.com: refused")

        assert second["owner"] == "analyst"
        assert second["needs_date"] is False
        assert second["period"] == "previous_7_days", "no period saved is the default"
        assert second["next_run_at"] is None, "a paused schedule has no next run"
        assert second["last_status"] == "failed", "a run marked running for hours did not finish"
        assert "did not finish" in second["last_error"]

    async def test_a_schedule_from_before_shows_when_it_will_run(self, client, admin, db_session):
        db_session.add(
            ReportSchedule(
                report_type="org_cost_summary", cron_expression="0 9 * * *", recipients="a@example.com", is_active=True
            )
        )
        await db_session.commit()
        headers = _sign_in(client, admin.username)
        [row] = (await client.get(SCHEDULES, headers=headers)).json()
        assert row["next_run_at"] is not None

    async def test_read_only_reports_access_can_see_them(self, client, db_session):
        viewer = await _account(db_session, "viewer", "read_only_super_admin")
        headers = _sign_in(client, viewer.username)
        assert (await client.get(SCHEDULES, headers=headers)).status_code == 200

    async def test_the_catalog_offers_the_periods_and_names_the_timezone(self, client, admin):
        headers = _sign_in(client, admin.username)
        data = (await client.get(f"{BASE}/catalog", headers=headers)).json()
        assert [p["value"] for p in data["schedule_periods"]] == list(svc.PERIODS)
        assert data["schedule_timezone"]


class TestChanges:
    async def _saved(self, db, **values) -> ReportSchedule:
        row = ReportSchedule(
            **{
                "report_type": "org_cost_summary",
                "cron_expression": "0 9 * * 1",
                "recipients": "a@example.com",
                "format": "csv",
                "is_active": True,
                "next_run_at": dt.datetime(2030, 1, 7, 9, 0),
                **values,
            }
        )
        db.add(row)
        await db.commit()
        return row

    async def test_pause_and_resume(self, client, admin, db_session):
        row = await self._saved(db_session, next_run_at=dt.datetime(2020, 1, 6, 9, 0))
        headers = _sign_in(client, admin.username)
        resp = await client.patch(f"{SCHEDULES}/{row.id}", json={"is_active": False}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["schedule"]["is_active"] is False
        [paused] = await _rows(db_session)
        assert paused.is_active is False
        assert len(await _trail(db_session, "report_schedule_paused")) == 1

        before = svc.utcnow()
        resp = await client.patch(f"{SCHEDULES}/{row.id}", json={"is_active": True}, headers=headers)
        assert resp.status_code == 200
        [resumed] = await _rows(db_session)
        assert resumed.is_active is True
        assert resumed.next_run_at > before, "the runs missed while paused are not sent late"
        assert len(await _trail(db_session, "report_schedule_resumed")) == 1

    async def test_asking_for_what_it_already_is_changes_nothing(self, client, admin, db_session):
        row = await self._saved(db_session)
        headers = _sign_in(client, admin.username)
        resp = await client.patch(f"{SCHEDULES}/{row.id}", json={"is_active": True}, headers=headers)
        assert resp.status_code == 200
        [same] = await _rows(db_session)
        assert same.next_run_at == dt.datetime(2030, 1, 7, 9, 0)
        assert await _trail(db_session, "report_schedule_resumed") == []

    async def test_a_schedule_that_cannot_run_cannot_be_resumed(self, client, admin, db_session):
        row = await self._saved(db_session, cron_expression="0 9 * * 5-1", is_active=False)
        headers = _sign_in(client, admin.username)
        resp = await client.patch(f"{SCHEDULES}/{row.id}", json={"is_active": True}, headers=headers)
        assert resp.status_code == 400
        assert resp.json()["detail"].startswith("This schedule cannot run:")

    async def test_delete(self, client, admin, db_session):
        row = await self._saved(db_session)
        headers = _sign_in(client, admin.username)
        assert (await client.delete(f"{SCHEDULES}/{row.id}", headers=headers)).status_code == 200
        assert await _rows(db_session) == []
        [event] = await _trail(db_session, "report_schedule_deleted")
        assert json.loads(event.detail_json)["recipients"] == ["a@example.com"]
        assert (await client.delete(f"{SCHEDULES}/{row.id}", headers=headers)).status_code == 404

    async def test_read_only_reports_access_cannot_change_anything(self, client, db_session):
        row = await self._saved(db_session)
        viewer = await _account(db_session, "viewer", "read_only_super_admin")
        headers = _sign_in(client, viewer.username)
        assert (
            await client.patch(f"{SCHEDULES}/{row.id}", json={"is_active": False}, headers=headers)
        ).status_code == 403
        assert (await client.delete(f"{SCHEDULES}/{row.id}", headers=headers)).status_code == 403
        assert (await client.post(f"{SCHEDULES}/{row.id}/send", headers=headers)).status_code == 403
        [same] = await _rows(db_session)
        assert same.is_active is True

    async def test_send_now_sends_without_moving_the_next_run(self, client, admin, db_session):
        row = await self._saved(db_session, recipients="a@example.com,b@example.com")
        headers = _sign_in(client, admin.username)
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            db_session.add(
                SmtpSettings(
                    host="127.0.0.1",
                    port=server.port,
                    from_address="reports@example.com",
                    security="none",
                    verify_certificate=True,
                )
            )
            await db_session.commit()
            resp = await client.post(f"{SCHEDULES}/{row.id}/send", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert (data["status"], data["sent"], data["not_sent"], data["error"]) == (
            "sent",
            ["a@example.com", "b@example.com"],
            {},
            None,
        )
        assert data["schedule"]["last_status"] == "sent"
        assert [m.recipients for m in server.messages] == [("a@example.com",), ("b@example.com",)]
        [sent] = await _rows(db_session)
        assert sent.next_run_at == dt.datetime(2030, 1, 7, 9, 0)
        assert sent.last_status == "sent" and sent.last_run_at is not None
        [event] = await _trail(db_session, "report_schedule_sent_now")
        assert json.loads(event.detail_json)["status"] == "sent"

    async def test_send_now_reports_a_failure(self, client, admin, db_session):
        row = await self._saved(db_session)
        headers = _sign_in(client, admin.username)
        resp = await client.post(f"{SCHEDULES}/{row.id}/send", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error"].startswith("SMTP is not configured.")
        assert data["not_sent"] == {"a@example.com": "SMTP is not configured. Set it up under Admin → SMTP."}

    async def test_unknown_schedule(self, client, admin):
        headers = _sign_in(client, admin.username)
        assert (await client.patch(f"{SCHEDULES}/999", json={"is_active": False}, headers=headers)).status_code == 404
        assert (await client.post(f"{SCHEDULES}/999/send", headers=headers)).status_code == 404
