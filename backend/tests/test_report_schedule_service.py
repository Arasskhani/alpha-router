"""Scheduled reports are emailed: when each one runs, what it covers, what it sends.

Schedules used to be stored and never sent. These tests hold the sender to
what the Reports page promises:

* cron is read the standard way - Sunday is 0 (and 7), and a day matching
  either day-of-month or day-of-week runs - in the server's timezone, where
  APScheduler on its own would run "1" on Tuesdays;
* a run covers whole days before the one it runs on, counted in that zone;
* every recipient gets the report as an attachment in a message of their
  own, one refused address costs only that address, and a server that
  cannot send stops the run and says so;
* a due run is claimed before it is sent, so a run that dies half way is
  not repeated, and one schedule failing does not stop the others;
* an owned schedule stops, paused, when its owner may no longer have it.
"""

from __future__ import annotations

import datetime as dt
import email
import email.policy
import logging
import zoneinfo

import pytest
from sqlalchemy import select

from app.branding import PRODUCT_NAME
from app.models.system import ReportSchedule, SmtpSettings
from app.models.user import User, UserRoleAssignment
from app.services import report_schedule_service as svc
from app.services.smtp_service import SmtpSendError
from tests.smtp_test_server import MODE_PLAIN, SmtpTestServer

UTC = dt.UTC
TEHRAN = zoneinfo.ZoneInfo("Asia/Tehran")  # UTC+03:30, no daylight saving
#: A Thursday.
NOW = dt.datetime(2026, 9, 24, 6, 0)


def _fire(cron: str, after: dt.datetime, tz: dt.tzinfo = UTC) -> dt.datetime:
    return svc.next_run_after(svc.schedule_trigger(cron, tz), after)


# --- cron ------------------------------------------------------------------------


class TestStandardWeekdays:
    @pytest.mark.parametrize(
        ("field", "names"),
        [
            ("*", "*"),
            ("1", "mon"),
            ("0", "sun"),
            ("7", "sun"),
            ("1-5", "mon,tue,wed,thu,fri"),
            ("1-7", "sun,mon,tue,wed,thu,fri,sat"),
            ("0-6", "sun,mon,tue,wed,thu,fri,sat"),
            ("mon-sun", "sun,mon,tue,wed,thu,fri,sat"),
            ("MON-FRI", "mon,tue,wed,thu,fri"),
            ("6,0", "sun,sat"),
            ("sat,sun", "sun,sat"),
            ("*/2", "sun,tue,thu,sat"),
            ("1/2", "sun,mon,wed,fri"),
            ("1-5/2", "mon,wed,fri"),
        ],
    )
    def test_standard_numbering_becomes_day_names(self, field, names):
        assert svc.standard_weekdays(field) == names

    @pytest.mark.parametrize("field", ["8", "5-1", "funday", "*/0", "1/x", "", "1-"])
    def test_anything_else_is_refused(self, field):
        with pytest.raises(ValueError):
            svc.standard_weekdays(field)


class TestScheduleTrigger:
    def test_one_is_monday_as_in_standard_cron(self):
        # APScheduler's own from_crontab reads 1 as Tuesday.
        assert _fire("0 9 * * 1", NOW) == dt.datetime(2026, 9, 28, 9, 0)

    @pytest.mark.parametrize("sunday", ["0", "7", "sun"])
    def test_zero_and_seven_are_sunday(self, sunday):
        assert _fire(f"0 9 * * {sunday}", NOW) == dt.datetime(2026, 9, 27, 9, 0)

    def test_a_day_matching_either_day_field_runs(self):
        cron = "0 9 1 * 1"  # the 1st, and every Monday
        monday = _fire(cron, NOW)
        assert monday == dt.datetime(2026, 9, 28, 9, 0)
        assert _fire(cron, monday) == dt.datetime(2026, 10, 1, 9, 0)  # a Thursday, but the 1st

    def test_day_of_month_alone(self):
        assert _fire("30 7 15 * *", NOW) == dt.datetime(2026, 10, 15, 7, 30)

    def test_times_are_the_server_clock(self):
        # 09:00 in Tehran is 05:30 UTC.
        assert _fire("0 9 * * *", NOW, TEHRAN) == dt.datetime(2026, 9, 25, 5, 30)
        assert _fire("0 9 * * *", dt.datetime(2026, 9, 24, 5, 0), TEHRAN) == dt.datetime(2026, 9, 24, 5, 30)

    def test_the_next_run_is_strictly_after(self):
        fire = dt.datetime(2026, 9, 28, 9, 0)
        assert _fire("0 9 * * 1", fire) == dt.datetime(2026, 10, 5, 9, 0)
        assert _fire("0 9 * * 1", fire - dt.timedelta(microseconds=1)) == fire

    @pytest.mark.parametrize(
        "cron",
        ["0 9 * *", "0 9 * * * *", "61 9 * * *", "0 25 * * *", "0 9 32 * *", "0 9 * 13 *", "0 9 * * 8", "x 9 * * *"],
    )
    def test_malformed_expressions_are_refused(self, cron):
        with pytest.raises(ValueError):
            svc.first_run(cron, NOW, UTC)

    def test_a_date_that_never_comes_is_refused(self):
        with pytest.raises(ValueError, match="never"):
            svc.first_run("0 9 30 2 *", NOW, UTC)


# --- periods ---------------------------------------------------------------------


class TestPeriods:
    @pytest.mark.parametrize(
        ("period", "today", "expected"),
        [
            ("previous_day", dt.date(2026, 9, 24), (dt.date(2026, 9, 23), dt.date(2026, 9, 23))),
            ("previous_7_days", dt.date(2026, 9, 24), (dt.date(2026, 9, 17), dt.date(2026, 9, 23))),
            ("previous_30_days", dt.date(2026, 9, 24), (dt.date(2026, 8, 25), dt.date(2026, 9, 23))),
            ("previous_month", dt.date(2026, 9, 24), (dt.date(2026, 8, 1), dt.date(2026, 8, 31))),
            ("previous_month", dt.date(2026, 1, 15), (dt.date(2025, 12, 1), dt.date(2025, 12, 31))),
            ("previous_month", dt.date(2026, 3, 1), (dt.date(2026, 2, 1), dt.date(2026, 2, 28))),
            (None, dt.date(2026, 9, 24), (dt.date(2026, 9, 17), dt.date(2026, 9, 23))),
        ],
    )
    def test_whole_days_before_the_run(self, period, today, expected):
        assert svc.period_dates(period, today) == expected

    def test_every_offered_period_is_known(self):
        for period in svc.PERIODS:
            svc.period_dates(period, dt.date(2026, 9, 24))

    def test_an_unknown_period_is_refused(self):
        with pytest.raises(ValueError):
            svc.period_dates("previous_year", dt.date(2026, 9, 24))


class TestPeriodBounds:
    def test_the_server_s_days_as_utc(self):
        assert svc.period_bounds(dt.date(2026, 9, 23), dt.date(2026, 9, 23), TEHRAN) == (
            dt.datetime(2026, 9, 22, 20, 30),
            dt.datetime(2026, 9, 23, 20, 29, 59, 999999),
        )
        assert svc.period_bounds(dt.date(2026, 9, 17), dt.date(2026, 9, 23), UTC) == (
            dt.datetime(2026, 9, 17),
            dt.datetime(2026, 9, 23, 23, 59, 59, 999999),
        )

    def test_one_run_s_days_end_where_the_next_one_s_begin(self):
        _, last = svc.period_bounds(dt.date(2026, 9, 23), dt.date(2026, 9, 23), TEHRAN)
        first, _ = svc.period_bounds(dt.date(2026, 9, 24), dt.date(2026, 9, 24), TEHRAN)
        assert first - last == dt.timedelta(microseconds=1)

    def test_the_day_the_clocks_go_back_has_25_hours(self):
        berlin = zoneinfo.ZoneInfo("Europe/Berlin")
        first, last = svc.period_bounds(dt.date(2026, 10, 25), dt.date(2026, 10, 25), berlin)
        assert (first, last) == (dt.datetime(2026, 10, 24, 22, 0), dt.datetime(2026, 10, 25, 22, 59, 59, 999999))


# --- parameters ------------------------------------------------------------------


class TestCheckedParameters:
    def test_a_required_parameter_must_be_there(self):
        with pytest.raises(ValueError, match="plan_id required"):
            svc.checked_parameters("plan_usage", None)
        assert svc.checked_parameters("plan_usage", '{"plan_id": 3}') == {"plan_id": 3}

    @pytest.mark.parametrize("name", ["colour", "start_date", "end_date", "format", "report_type"])
    def test_what_the_schedule_decides_itself_or_nothing_takes_is_refused(self, name):
        with pytest.raises(ValueError, match="Unknown report parameter"):
            svc.checked_parameters("org_cost_summary", f'{{"{name}": "x"}}')

    def test_values_are_checked(self):
        with pytest.raises(ValueError, match="top_n"):
            svc.checked_parameters("top_users_by_spend", '{"top_n": 1000}')

    @pytest.mark.parametrize("text", ["[1]", '"x"', "{", "null"])
    def test_parameters_are_an_object(self, text):
        with pytest.raises(ValueError, match="JSON object"):
            svc.checked_parameters("org_cost_summary", text)


# --- one run ---------------------------------------------------------------------


async def _smtp(db, server) -> None:
    db.add(
        SmtpSettings(
            host="127.0.0.1",
            port=server.port,
            from_address="reports@example.com",
            security="none",
            verify_certificate=True,
        )
    )
    await db.commit()


async def _schedule(db, **values) -> ReportSchedule:
    row = ReportSchedule(
        **{
            "report_type": "new_users",
            "cron_expression": "0 9 * * 1",
            "recipients": "a@example.com,b@example.com",
            "format": "csv",
            "period": "previous_7_days",
            "is_active": True,
            **values,
        }
    )
    db.add(row)
    await db.commit()
    return row


async def _person(db, username: str, created_at: dt.datetime, **values) -> User:
    person = User(
        username=username,
        email=values.pop("email", f"{username}@example.com"),
        hashed_password="x",
        auth_provider="local",
        is_active=values.pop("is_active", True),
        created_at=created_at,
        **values,
    )
    db.add(person)
    await db.commit()
    return person


def _parsed(message):
    return email.message_from_bytes(message.data, policy=email.policy.default)


class TestRunSchedule:
    async def test_each_recipient_gets_the_report_for_the_period_in_a_message_of_their_own(self, db_session):
        await _person(db_session, "inside", dt.datetime(2026, 9, 20, 10, 0))
        await _person(db_session, "before", dt.datetime(2026, 9, 10, 10, 0))
        await _person(db_session, "today", dt.datetime(2026, 9, 24, 1, 0))
        row = await _schedule(db_session)
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            await _smtp(db_session, server)
            result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)

        assert result.status == "sent"
        assert result.sent == ["a@example.com", "b@example.com"]
        assert [m.recipients for m in server.messages] == [("a@example.com",), ("b@example.com",)]
        for received, address in zip(server.messages, ["a@example.com", "b@example.com"], strict=True):
            message = _parsed(received)
            assert message["To"] == address, "no recipient sees the others' addresses"
            assert message["Subject"] == f"{PRODUCT_NAME} report: New users, 2026-09-17 to 2026-09-23"
            body = message.get_body(preferencelist=("plain",)).get_content()
            assert "Period: 2026-09-17 to 2026-09-23 (the 7 days before)" in body
            assert "Rows: 1" in body
            (attachment,) = message.iter_attachments()
            assert attachment.get_filename() == "new_users_2026-09-17_2026-09-23.csv"
            assert attachment.get_content_type() == "text/csv"
            content = attachment.get_content()
            assert "inside" in content
            assert "before" not in content and "today" not in content
        assert (row.last_run_at, row.last_status, row.last_error) == (NOW, "sent", None)

    async def test_the_period_is_counted_in_the_server_timezone(self, db_session):
        row = await _schedule(db_session, period="previous_day", recipients="a@example.com")
        late_evening_utc = dt.datetime(2026, 9, 23, 22, 0)  # already the 24th in Tehran
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            await _smtp(db_session, server)
            await svc.run_schedule(db_session, row, now=late_evening_utc, tz=TEHRAN)
            await svc.run_schedule(db_session, row, now=late_evening_utc, tz=UTC)
        subjects = [_parsed(m)["Subject"] for m in server.messages]
        assert subjects == [
            f"{PRODUCT_NAME} report: New users, 2026-09-23",
            f"{PRODUCT_NAME} report: New users, 2026-09-22",
        ]

    async def test_the_days_are_the_server_s_calendar_days(self, db_session):
        """Just after midnight in Tehran, "the day before" is a day that has ended
        there. The report covers its 24 hours, not the UTC day of that date,
        which still had hours to go."""
        # The 23rd in Tehran (UTC+03:30) runs from 20:30 UTC on the 22nd to 20:30 UTC on the 23rd.
        await _person(db_session, "late_on_the_22nd", dt.datetime(2026, 9, 22, 20, 15))
        await _person(db_session, "early_on_the_23rd", dt.datetime(2026, 9, 22, 21, 0))
        await _person(db_session, "late_on_the_23rd", dt.datetime(2026, 9, 23, 20, 15))
        await _person(db_session, "on_the_24th", dt.datetime(2026, 9, 23, 20, 45))
        row = await _schedule(db_session, period="previous_day", recipients="a@example.com")
        just_after_midnight = dt.datetime(2026, 9, 23, 21, 0)  # 00:30 on the 24th in Tehran
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            await _smtp(db_session, server)
            await svc.run_schedule(db_session, row, now=just_after_midnight, tz=TEHRAN)
        message = _parsed(server.messages[0])
        assert message["Subject"] == f"{PRODUCT_NAME} report: New users, 2026-09-23"
        (attachment,) = message.iter_attachments()
        content = attachment.get_content()
        assert "early_on_the_23rd" in content and "late_on_the_23rd" in content
        assert "late_on_the_22nd" not in content and "on_the_24th" not in content

    async def test_a_snapshot_report_is_named_for_the_day_it_was_taken(self, db_session):
        await _person(db_session, "gone", dt.datetime(2026, 1, 1), is_active=False)
        row = await _schedule(db_session, report_type="deactivated_users", recipients="a@example.com", format="xlsx")
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            await _smtp(db_session, server)
            result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)
        assert result.status == "sent"
        message = _parsed(server.messages[0])
        assert message["Subject"].endswith(", 2026-09-24")
        assert "A snapshot taken on 2026-09-24." in message.get_body(preferencelist=("plain",)).get_content()
        (attachment,) = message.iter_attachments()
        assert attachment.get_filename() == "deactivated_users_2026-09-24.xlsx"
        assert attachment.get_content_type() == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert attachment.get_content()[:2] == b"PK", "a real workbook"

    async def test_a_refused_address_costs_only_that_address(self, db_session):
        row = await _schedule(db_session, recipients="gone@example.com,a@example.com")
        async with SmtpTestServer(mode=MODE_PLAIN, refuse_recipients=frozenset({"gone@example.com"})) as server:
            await _smtp(db_session, server)
            result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)
        assert result.status == "partial"
        assert result.sent == ["a@example.com"]
        assert list(result.not_sent) == ["gone@example.com"]
        assert [m.recipients for m in server.messages] == [("a@example.com",)]
        assert row.last_status == "partial"
        assert row.last_error.startswith("gone@example.com: ")

    async def test_every_address_refused_is_a_failed_run(self, db_session):
        row = await _schedule(db_session, recipients="gone@example.com")
        async with SmtpTestServer(mode=MODE_PLAIN, refuse_recipients=frozenset({"gone@example.com"})) as server:
            await _smtp(db_session, server)
            result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)
        assert (result.status, row.last_status) == ("failed", "failed")
        assert server.messages == []

    async def test_no_smtp_fails_the_run_and_says_so(self, db_session):
        row = await _schedule(db_session)
        result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)
        assert result.status == "failed"
        assert result.sent == []
        assert row.last_error == (
            "SMTP is not configured. Set it up under Admin → SMTP. Not sent to a@example.com, b@example.com."
        )

    async def test_a_server_that_stops_sending_stops_the_run(self, db_session, monkeypatch):
        row = await _schedule(db_session, recipients="a@example.com,b@example.com,c@example.com")
        tried: list[str] = []

        async def send(_db, *, to_address, **_kwargs):
            tried.append(to_address)
            if to_address == "b@example.com":
                raise SmtpSendError("The mail server closed the connection.")

        monkeypatch.setattr(svc, "send_email", send)
        result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)
        assert tried == ["a@example.com", "b@example.com"], "nothing more was tried once the server failed"
        assert result.status == "partial"
        assert result.not_sent == {
            "b@example.com": "The mail server closed the connection.",
            "c@example.com": "The mail server closed the connection.",
        }
        assert row.last_error == "The mail server closed the connection. Not sent to b@example.com, c@example.com."

    async def test_an_unexpected_sending_error_is_logged_and_stops_the_run(self, db_session, monkeypatch, caplog):
        row = await _schedule(db_session, recipients="a@example.com")

        async def send(*_a, **_k):
            raise RuntimeError("socket on fire")

        monkeypatch.setattr(svc, "send_email", send)
        with caplog.at_level(logging.ERROR, logger=svc.logger.name):
            result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)
        assert result.status == "failed"
        assert "RuntimeError" in row.last_error
        assert any(r.exc_info and "socket on fire" in str(r.exc_info[1]) for r in caplog.records)

    async def test_a_report_that_cannot_be_built_fails_the_run_before_anything_is_sent(self, db_session, monkeypatch):
        sent: list[str] = []

        async def send(_db, *, to_address, **_kwargs):
            sent.append(to_address)

        monkeypatch.setattr(svc, "send_email", send)
        missing = await _schedule(db_session, report_type="plan_usage")
        result = await svc.run_schedule(db_session, missing, now=NOW, tz=UTC)
        assert result.status == "failed"
        assert missing.last_error == "The report could not be built: plan_id required"

        stale = await _schedule(db_session, parameters_json='{"colour": "red"}')
        await svc.run_schedule(db_session, stale, now=NOW, tz=UTC)
        assert stale.last_error == "The report could not be built: Unknown report parameter: colour"

        gone = await _schedule(db_session, report_type="retired_report")
        await svc.run_schedule(db_session, gone, now=NOW, tz=UTC)
        assert gone.last_error == "Unknown report: retired_report"
        assert sent == []

    async def test_a_crash_while_building_is_logged_and_fails_the_run(self, db_session, monkeypatch, caplog):
        async def explode(*_a, **_k):
            raise RuntimeError("query planner fell over")

        monkeypatch.setattr(svc.reports_service, "build_report", explode)
        row = await _schedule(db_session)
        with caplog.at_level(logging.ERROR, logger=svc.logger.name):
            result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)
        assert result.status == "failed"
        assert row.last_error == "The report could not be built. The server log has the details."
        assert any(r.exc_info and "query planner" in str(r.exc_info[1]) for r in caplog.records)

    async def test_a_report_too_big_to_email_is_not_sent(self, db_session, monkeypatch):
        monkeypatch.setattr(svc, "MAX_ATTACHMENT_BYTES", 10)
        row = await _schedule(db_session)
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            await _smtp(db_session, server)
            result = await svc.run_schedule(db_session, row, now=NOW, tz=UTC)
        assert result.status == "failed"
        assert "download it from the Reports page" in row.last_error
        assert server.messages == []


class TestOwnedSchedules:
    async def _owner(self, db, *, role="reports_full_administrator", **values) -> User:
        owner = await _person(db, "owner", dt.datetime(2026, 1, 1), **values)
        db.add(UserRoleAssignment(user_id=owner.id, role_slug=role))
        await db.commit()
        return owner

    async def _run(self, db, owner) -> tuple[ReportSchedule, svc.RunResult, list]:
        row = await _schedule(db, owner_user_id=owner.id, recipients="owner@example.com")
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            await _smtp(db, server)
            result = await svc.run_schedule(db, row, now=NOW, tz=UTC)
        return row, result, server.messages

    async def test_an_owner_who_may_run_reports_gets_the_report(self, db_session):
        owner = await self._owner(db_session)
        row, result, messages = await self._run(db_session, owner)
        assert result.status == "sent"
        assert [m.recipients for m in messages] == [("owner@example.com",)]
        assert row.is_active

    async def _refused(self, db, owner, reason: str) -> None:
        row, result, messages = await self._run(db, owner)
        assert result.status == "failed"
        assert messages == []
        assert row.is_active is False, "the schedule is paused, not left failing every week"
        assert reason in row.last_error
        assert row.last_error.endswith("The schedule was paused.")

    async def test_an_owner_without_reports_access_any_more_stops_it(self, db_session):
        owner = await self._owner(db_session, role="user")
        await self._refused(db_session, owner, "owner may no longer run reports.")

    async def test_read_only_reports_access_is_not_enough(self, db_session):
        owner = await self._owner(db_session, role="read_only_super_admin")
        await self._refused(db_session, owner, "owner may no longer run reports.")

    async def test_a_disabled_owner_stops_it(self, db_session):
        owner = await self._owner(db_session, is_active=False)
        await self._refused(db_session, owner, "owner's account is disabled.")

    async def test_a_deleted_owner_stops_it(self, db_session):
        owner = await self._owner(db_session, deleted_at=dt.datetime(2026, 9, 1))
        await self._refused(db_session, owner, "no longer exists")

    async def test_an_owner_whose_address_changed_stops_it(self, db_session):
        owner = await self._owner(db_session, email="new-owner@example.com")
        await self._refused(db_session, owner, "no longer owner's")


# --- the job ---------------------------------------------------------------------


class TestRunDueSchedules:
    @pytest.fixture
    def sent(self, monkeypatch) -> list[tuple[int, dt.datetime]]:
        """Replaces the run itself: records which schedule ran, at what time."""
        runs: list[tuple[int, dt.datetime]] = []

        async def run(db, schedule, *, now=None, tz=None):
            runs.append((schedule.id, now))
            schedule.last_run_at = now
            schedule.last_status = "sent"
            return svc.RunResult("sent", sent=svc.recipients_of(schedule))

        monkeypatch.setattr(svc, "run_schedule", run)
        return runs

    async def _row(self, session_factory, **values) -> int:
        async with session_factory() as db:
            row = await _schedule(db, **values)
            return row.id

    async def _get(self, session_factory, schedule_id) -> ReportSchedule:
        async with session_factory() as db:
            return await db.get(ReportSchedule, schedule_id)

    async def test_a_due_schedule_runs_once_and_moves_to_its_next_time(self, session_factory, sent):
        due = await self._row(session_factory, next_run_at=dt.datetime(2026, 9, 24, 5, 59))
        counts = await svc.run_due_schedules(session_factory, now=NOW, tz=UTC)
        assert counts == {"ran": 1, "sent": 1, "partial": 0, "failed": 0}
        assert sent == [(due, NOW)]
        row = await self._get(session_factory, due)
        assert row.next_run_at == dt.datetime(2026, 9, 28, 9, 0), "next Monday 09:00"
        assert (row.last_run_at, row.last_status) == (NOW, "sent")

        await svc.run_due_schedules(session_factory, now=NOW + dt.timedelta(minutes=1), tz=UTC)
        assert len(sent) == 1, "not sent again the next minute"

    async def test_a_schedule_not_due_yet_or_paused_does_not_run(self, session_factory, sent):
        await self._row(session_factory, next_run_at=NOW + dt.timedelta(minutes=1))
        await self._row(session_factory, next_run_at=NOW - dt.timedelta(days=1), is_active=False)
        assert (await svc.run_due_schedules(session_factory, now=NOW, tz=UTC))["ran"] == 0
        assert sent == []

    async def test_runs_missed_while_the_server_was_down_go_out_once(self, session_factory, sent):
        daily = await self._row(
            session_factory, cron_expression="0 3 * * *", next_run_at=NOW - dt.timedelta(days=3, hours=3)
        )
        await svc.run_due_schedules(session_factory, now=NOW, tz=UTC)
        assert sent == [(daily, NOW)]
        assert (await self._get(session_factory, daily)).next_run_at == dt.datetime(2026, 9, 25, 3, 0)

    async def test_a_schedule_saved_before_runs_were_kept_waits_for_its_next_time(self, session_factory, sent):
        old = await self._row(session_factory, next_run_at=None)
        counts = await svc.run_due_schedules(session_factory, now=NOW, tz=UTC)
        assert counts["ran"] == 0 and sent == [], "not sent the moment the server is upgraded"
        row = await self._get(session_factory, old)
        assert row.next_run_at == dt.datetime(2026, 9, 28, 9, 0)
        assert row.last_status is None

    async def test_a_saved_expression_that_cannot_run_is_paused_with_the_reason(self, session_factory, sent):
        # APScheduler's own syntax, accepted before cron was read the standard way.
        odd = await self._row(session_factory, cron_expression="0 9 * * 5-1", next_run_at=None)
        never = await self._row(session_factory, cron_expression="0 9 30 2 *", next_run_at=NOW)
        await svc.run_due_schedules(session_factory, now=NOW, tz=UTC)
        assert sent == []
        for schedule_id in (odd, never):
            row = await self._get(session_factory, schedule_id)
            assert row.is_active is False
            assert row.last_status == "failed"
            assert row.last_error.startswith("This schedule cannot run: ")
            assert row.last_error.endswith("It was paused.")

    async def test_one_schedule_failing_does_not_stop_the_others(self, session_factory, monkeypatch, caplog):
        broken = await self._row(session_factory, next_run_at=NOW)
        healthy = await self._row(session_factory, next_run_at=NOW)
        ran: list[int] = []

        async def run(db, schedule, *, now=None, tz=None):
            if schedule.id == broken:
                raise RuntimeError("the database blinked")
            ran.append(schedule.id)
            schedule.last_status = "sent"
            return svc.RunResult("sent")

        monkeypatch.setattr(svc, "run_schedule", run)
        with caplog.at_level(logging.ERROR, logger=svc.logger.name):
            counts = await svc.run_due_schedules(session_factory, now=NOW, tz=UTC)
        assert ran == [healthy]
        assert counts == {"ran": 1, "sent": 1, "partial": 0, "failed": 1}
        assert any(r.exc_info and "the database blinked" in str(r.exc_info[1]) for r in caplog.records)
        row = await self._get(session_factory, broken)
        assert row.last_status == "failed"
        assert row.last_error == "The run failed unexpectedly. The server log has the details."
        assert row.next_run_at > NOW, "and it is not retried every minute"

    async def test_a_run_someone_else_claimed_is_left_to_them(self, session_factory, sent):
        schedule_id = await self._row(session_factory, next_run_at=dt.datetime(2026, 9, 28, 9, 0))
        # This worker saw it due at 05:59; another has run it and moved it on since.
        status = await svc._run_one(
            session_factory, schedule_id, "0 9 * * 1", dt.datetime(2026, 9, 24, 5, 59), NOW, UTC
        )
        assert status is None
        assert sent == []

    async def test_a_schedule_paused_after_it_was_found_due_is_not_run(self, session_factory, sent):
        schedule_id = await self._row(session_factory, next_run_at=NOW, is_active=False)
        # Found due a moment ago; an admin has paused it since.
        status = await svc._run_one(session_factory, schedule_id, "0 9 * * 1", NOW, NOW, UTC)
        assert status is None
        assert sent == []
        row = await self._get(session_factory, schedule_id)
        assert (row.next_run_at, row.last_status) == (NOW, None)

    async def test_a_run_that_dies_half_way_is_not_repeated(self, session_factory, monkeypatch):
        schedule_id = await self._row(session_factory, next_run_at=NOW)

        class ServerStopped(BaseException):
            pass

        async def die(*_a, **_k):
            raise ServerStopped

        monkeypatch.setattr(svc, "run_schedule", die)
        with pytest.raises(ServerStopped):
            await svc.run_due_schedules(session_factory, now=NOW, tz=UTC)
        row = await self._get(session_factory, schedule_id)
        assert row.last_status == "running"
        assert row.next_run_at == dt.datetime(2026, 9, 28, 9, 0), "claimed before it ran"

        ran: list[int] = []

        async def run(db, schedule, *, now=None, tz=None):
            ran.append(schedule.id)
            return svc.RunResult("sent")

        monkeypatch.setattr(svc, "run_schedule", run)
        await svc.run_due_schedules(session_factory, now=NOW + dt.timedelta(minutes=1), tz=UTC)
        assert ran == []

        assert svc.displayed_outcome(row, NOW + dt.timedelta(minutes=5)) == ("running", None)
        assert svc.displayed_outcome(row, NOW + dt.timedelta(hours=2)) == (
            "failed",
            "The run did not finish: the server stopped while it was running.",
        )

    async def test_end_to_end_through_a_mail_server(self, session_factory):
        schedule_id = await self._row(session_factory, next_run_at=NOW, recipients="a@example.com")
        async with SmtpTestServer(mode=MODE_PLAIN) as server:
            async with session_factory() as db:
                await _smtp(db, server)
            counts = await svc.run_due_schedules(session_factory, now=NOW, tz=UTC)
        assert counts["sent"] == 1
        assert [m.recipients for m in server.messages] == [("a@example.com",)]
        row = await self._get(session_factory, schedule_id)
        assert (row.last_status, row.last_error) == ("sent", None)


# --- the scheduler -----------------------------------------------------------------


def test_the_job_runs_every_minute_one_at_a_time(monkeypatch):
    from app.services import scheduler

    added: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(scheduler.scheduler, "add_job", lambda *a, **k: added.append((a, k)))
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    scheduler.start_scheduler()
    (args, kwargs) = next((a, k) for a, k in added if k.get("id") == "report_schedules")
    assert args == (scheduler.job_report_schedules, "interval")
    assert kwargs["minutes"] == 1
    assert kwargs["max_instances"] == 1 and kwargs["coalesce"] is True


async def test_the_job_runs_due_schedules_on_the_app_database(monkeypatch, session_factory):
    from app.services import scheduler

    seen: list = []

    async def run_due(factory, **_kwargs):
        seen.append(factory)
        return {"ran": 0, "sent": 0, "partial": 0, "failed": 0}

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(svc, "run_due_schedules", run_due)
    await scheduler.job_report_schedules()
    assert seen == [session_factory]


async def test_a_failure_in_the_job_is_contained_and_logged(monkeypatch, caplog):
    from app.services import scheduler

    async def explode(*_a, **_k):
        raise RuntimeError("no database")

    monkeypatch.setattr(svc, "run_due_schedules", explode)
    with caplog.at_level(logging.ERROR, logger="app.services.scheduler"):
        await scheduler.job_report_schedules()
    assert any(r.exc_info and "no database" in str(r.exc_info[1]) for r in caplog.records)


async def test_schedules_are_listed_in_the_order_they_were_made(session_factory, monkeypatch):
    """Due schedules run oldest first, so a flood of new ones cannot starve an old one."""
    order: list[int] = []

    async def run(db, schedule, *, now=None, tz=None):
        order.append(schedule.id)
        return svc.RunResult("sent")

    monkeypatch.setattr(svc, "run_schedule", run)
    async with session_factory() as db:
        ids = [(await _schedule(db, next_run_at=NOW)).id for _ in range(3)]
    await svc.run_due_schedules(session_factory, now=NOW, tz=UTC)
    assert order == ids
    async with session_factory() as db:
        rows = (await db.execute(select(ReportSchedule.next_run_at))).scalars().all()
    assert all(value > NOW for value in rows)
