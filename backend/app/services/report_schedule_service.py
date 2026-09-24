"""Scheduled reports: when each one runs, and running it into an email.

A schedule names a report from the catalog, its parameters, a format, the
period a dated report covers, a cron expression and up to twenty recipients.
A job on the leader worker (``scheduler.job_report_schedules``) looks every
minute for schedules whose next run time has come, builds each report once
and emails it to every recipient as an attachment: one message each, so no
recipient sees the others' addresses and a refused address costs only that
address.

Times
    The cron expression is read in the server's timezone, the one the other
    scheduled jobs use (``schedule_timezone``), and a period's days are that
    zone's calendar days. Cron is read the standard way: day-of-week 0 and 7
    are Sunday, and when day-of-month and day-of-week are both restricted, a
    day matching either one runs. APScheduler, which does the arithmetic,
    counts 0 as Monday and wants both to match, so expressions are translated
    rather than handed to ``CronTrigger.from_crontab``.

At most once
    A due run is claimed before its report is built: the row's next run time
    moves on and the claim is committed. A run that dies half way (the server
    stopped) is not repeated a minute later; its row says ``running`` until
    the next run, and the Reports page shows that it did not finish.

Owned schedules
    A schedule set up through ``POST /api/admin/reports/schedules/user``
    belongs to that account and goes to its own address. Each run checks
    again that the account may still run reports and that the address is
    still its own; when either has changed, the run fails and the schedule is
    paused.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.branding import PRODUCT_NAME
from app.models.system import ReportSchedule
from app.models.user import User
from app.services import reports_service
from app.services.rbac import user_can_access_menu, user_can_write_menu, user_is_admin_panel
from app.services.report_request import ReportRequest, report_params
from app.services.reports_catalog import REPORT_CATALOG
from app.services.schedule_timezone import get_server_timezone
from app.services.smtp_service import (
    EmailAttachment,
    SmtpNotConfiguredError,
    SmtpRecipientError,
    SmtpSendError,
    send_email,
)
from app.services.user_role_service import get_user_role_slugs

logger = logging.getLogger(__name__)

PERIOD_PREVIOUS_DAY = "previous_day"
PERIOD_PREVIOUS_7_DAYS = "previous_7_days"
PERIOD_PREVIOUS_30_DAYS = "previous_30_days"
PERIOD_PREVIOUS_MONTH = "previous_month"
DEFAULT_PERIOD = PERIOD_PREVIOUS_7_DAYS

#: Value and label of each period, in the order the Reports page offers them.
PERIODS: dict[str, str] = {
    PERIOD_PREVIOUS_DAY: "The day before",
    PERIOD_PREVIOUS_7_DAYS: "The 7 days before",
    PERIOD_PREVIOUS_30_DAYS: "The 30 days before",
    PERIOD_PREVIOUS_MONTH: "The calendar month before",
}

STATUS_RUNNING = "running"
STATUS_SENT = "sent"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"

#: A run still marked running after this long did not finish.
RUN_STALE_AFTER = dt.timedelta(hours=1)
#: What one email may carry. Most mail servers refuse much more than this.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
#: ``last_error`` is shown on the Reports page, not a log.
_MAX_ERROR_CHARS = 2000

#: What a schedule's parameters may set: everything a report request takes,
#: except what the schedule decides itself.
PARAMETER_NAMES = frozenset(ReportRequest.model_fields) - {"report_type", "start_date", "end_date", "format"}

_FORMAT_NAMES = {"pdf": "PDF", "xlsx": "Excel", "xls": "Excel", "csv": "CSV"}
_WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def utcnow() -> dt.datetime:
    """Naive UTC, what the columns store."""
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


# --- periods -------------------------------------------------------------------


def period_dates(period: str | None, today: dt.date) -> tuple[dt.date, dt.date]:
    """The first and last day a run on ``today`` covers.

    Today itself is never included: its data is still coming in.
    """
    period = period or DEFAULT_PERIOD
    yesterday = today - dt.timedelta(days=1)
    if period == PERIOD_PREVIOUS_DAY:
        return yesterday, yesterday
    if period == PERIOD_PREVIOUS_7_DAYS:
        return today - dt.timedelta(days=7), yesterday
    if period == PERIOD_PREVIOUS_30_DAYS:
        return today - dt.timedelta(days=30), yesterday
    if period == PERIOD_PREVIOUS_MONTH:
        last = today.replace(day=1) - dt.timedelta(days=1)
        return last.replace(day=1), last
    raise ValueError(f"Unknown period: {period}")


# --- cron ----------------------------------------------------------------------


def _weekday_number(token: str, *, end_of_range: bool = False) -> int:
    """0-7 in standard numbering (0 and 7 are Sunday) for a number or a name."""
    token = token.strip().lower()
    if token in _WEEKDAYS:
        number = _WEEKDAYS.index(token)
        # "mon-sun" runs to the end of the week.
        return 7 if end_of_range and number == 0 else number
    if token.isdigit() and int(token) <= 7:
        return int(token)
    raise ValueError(f"{token!r} is not a day of the week: use 0-7 (0 and 7 are Sunday) or sun-sat")


def standard_weekdays(field_text: str) -> str:
    """A day-of-week field in standard cron numbering, as APScheduler day names.

    Standard cron counts Sunday as 0 (and as 7), APScheduler counts Monday as
    0, so a "1" handed over as it is runs on Tuesdays. Each item is expanded
    to the days it means and the lot returned as names ("mon,wed,fri"), which
    also keeps "1-7" (Monday to Sunday) valid.
    """
    field_text = field_text.strip().lower()
    if field_text == "*":
        return "*"
    days: set[int] = set()
    for item in field_text.split(","):
        base, slash, step_text = item.partition("/")
        step = 1
        if slash:
            if not step_text.isdigit() or int(step_text) < 1:
                raise ValueError(f"{item!r}: a step is a whole number from 1 up")
            step = int(step_text)
        if base == "*":
            first, last = 0, 6
        elif "-" in base:
            start_text, _, end_text = base.partition("-")
            first = _weekday_number(start_text)
            last = _weekday_number(end_text, end_of_range=True)
            if first > last:
                raise ValueError(f"{item!r}: a range runs from the earlier day to the later one")
        else:
            first = _weekday_number(base)
            # "1/2" is every other day from Monday on, as in standard cron.
            last = 7 if slash else first
        days.update(number % 7 for number in range(first, last + 1, step))
    return ",".join(_WEEKDAYS[number] for number in sorted(days))


def schedule_trigger(cron_expression: str, tz: dt.tzinfo | None = None) -> BaseTrigger:
    """The trigger for a five-field cron expression, read as standard cron in ``tz``.

    Raises ValueError, with a message for the admin, for anything else.
    """
    fields = (cron_expression or "").split()
    if len(fields) != 5:
        raise ValueError("A cron expression has 5 fields: minute hour day-of-month month day-of-week")
    minute, hour, day, month, weekday = fields
    tz = tz or get_server_timezone()
    weekdays = standard_weekdays(weekday)
    try:
        if day != "*" and weekday != "*":
            # Standard cron: either field matching is enough.
            return OrTrigger(
                [
                    CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week="*", timezone=tz),
                    CronTrigger(minute=minute, hour=hour, day="*", month=month, day_of_week=weekdays, timezone=tz),
                ]
            )
        return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=weekdays, timezone=tz)
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc


def next_run_after(trigger: BaseTrigger, after: dt.datetime) -> dt.datetime | None:
    """The first time ``trigger`` fires strictly after ``after``; naive UTC in and out.

    None when it never fires again (the 30th of February).
    """
    start = after.replace(tzinfo=dt.UTC) + dt.timedelta(microseconds=1)
    fire = trigger.get_next_fire_time(None, start)
    if fire is None:
        return None
    return fire.astimezone(dt.UTC).replace(tzinfo=None)


# --- parameters ----------------------------------------------------------------


def _report(report_type: str) -> dict[str, Any] | None:
    return next((r for r in REPORT_CATALOG if r["id"] == report_type), None)


def parse_parameters(parameters_json: str | None) -> dict[str, Any]:
    if not parameters_json:
        return {}
    try:
        parameters = json.loads(parameters_json)
    except ValueError as exc:
        raise ValueError("parameters_json must be a JSON object") from exc
    if not isinstance(parameters, dict):
        raise ValueError("parameters_json must be a JSON object")
    return parameters


def build_request(
    report_type: str, parameters: dict[str, Any], fmt: str, start: dt.date, end: dt.date
) -> ReportRequest:
    """The report request one run makes. Raises ValueError for parameters a run would refuse."""
    unknown = sorted(set(parameters) - PARAMETER_NAMES)
    if unknown:
        raise ValueError(f"Unknown report parameter: {unknown[0]}")
    try:
        return ReportRequest(
            report_type=report_type,
            format=fmt,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            **parameters,
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ())) or "parameters"
        raise ValueError(f"Report parameter {where}: {first.get('msg', 'invalid')}") from exc


def checked_parameters(report_type: str, parameters_json: str | None) -> dict[str, Any]:
    """A schedule's parameters, checked the way its runs will use them.

    Raises ValueError for anything a run would refuse, so that a mistake is
    reported when the schedule is saved rather than by a failed email later.
    """
    parameters = parse_parameters(parameters_json)
    today = dt.date.today()
    request = build_request(report_type, parameters, "csv", today - dt.timedelta(days=7), today)
    try:
        report_params(request)
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc
    return parameters


# --- one run -------------------------------------------------------------------


@dataclass
class RunResult:
    status: str
    #: Who the report reached.
    sent: list[str] = field(default_factory=list)
    #: Who it did not reach, and why.
    not_sent: dict[str, str] = field(default_factory=dict)
    #: What the Reports page shows about the run; None when all went well.
    error: str | None = None


def displayed_outcome(schedule: ReportSchedule, now: dt.datetime) -> tuple[str | None, str | None]:
    """The last run's status and error as the Reports page shows them."""
    status = schedule.last_status
    if status == STATUS_RUNNING and schedule.last_run_at is not None and now - schedule.last_run_at > RUN_STALE_AFTER:
        return STATUS_FAILED, "The run did not finish: the server stopped while it was running."
    return status, schedule.last_error


def recipients_of(schedule: ReportSchedule) -> list[str]:
    return [r.strip() for r in (schedule.recipients or "").split(",") if r.strip()]


async def _owner_problem(db: AsyncSession, schedule: ReportSchedule) -> str | None:
    """Why an owned schedule may no longer run; None when it may (or has no owner)."""
    if schedule.owner_user_id is None:
        return None
    owner = await db.get(User, schedule.owner_user_id)
    if owner is None or owner.deleted_at is not None:
        return "The account that set this schedule up no longer exists."
    if not owner.is_active:
        return f"{owner.username}'s account is disabled."
    slugs = await get_user_role_slugs(db, owner.id)
    if not (
        user_is_admin_panel(slugs) and user_can_access_menu(slugs, "reports") and user_can_write_menu(slugs, "reports")
    ):
        return f"{owner.username} may no longer run reports."
    own = (owner.email or "").strip().lower()
    if not own or any(r.lower() != own for r in recipients_of(schedule)):
        return f"The schedule sends to an address that is no longer {owner.username}'s."
    return None


def _record(schedule: ReportSchedule, now: dt.datetime, result: RunResult) -> RunResult:
    schedule.last_run_at = now
    schedule.last_status = result.status
    schedule.last_error = result.error[:_MAX_ERROR_CHARS] if result.error else None
    return result


def _days(start: dt.date, end: dt.date) -> str:
    return start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"


def _attachment_name(report_type: str, exported_name: str, start: dt.date, end: dt.date) -> str:
    extension = exported_name.rsplit(".", 1)[-1]
    days = start.isoformat() if start == end else f"{start.isoformat()}_{end.isoformat()}"
    return f"{report_type}_{days}.{extension}"


def _message(
    *, title: str, dated: bool, start: dt.date, end: dt.date, today: dt.date, period: str, rows: int, fmt: str
) -> tuple[str, str]:
    if dated:
        when = _days(start, end)
        period_line = f"Period: {when} ({PERIODS.get(period, period).lower()})"
    else:
        when = today.isoformat()
        period_line = f"A snapshot taken on {when}."
    subject = f"{PRODUCT_NAME} report: {title}, {when}"
    body = "\n".join(
        [
            title,
            period_line,
            f"Rows: {rows}" if rows else "Rows: none (no data).",
            "",
            f"The report is attached as a {_FORMAT_NAMES.get(fmt, fmt.upper())} file.",
            "",
            f"This is a scheduled report from {PRODUCT_NAME}. To change or stop it, "
            "open Admin > Reports > Scheduled reports.",
        ]
    )
    return subject, body


async def run_schedule(
    db: AsyncSession,
    schedule: ReportSchedule,
    *,
    now: dt.datetime | None = None,
    tz: dt.tzinfo | None = None,
) -> RunResult:
    """Build the schedule's report and email it to each recipient.

    Records the outcome on the row (``last_run_at``, ``last_status``,
    ``last_error``) and pauses an owned schedule whose owner may no longer
    have it. The caller commits.
    """
    now = now or utcnow()
    tz = tz or get_server_timezone()

    problem = await _owner_problem(db, schedule)
    if problem is not None:
        schedule.is_active = False
        return _record(schedule, now, RunResult(STATUS_FAILED, error=f"{problem} The schedule was paused."))

    report = _report(schedule.report_type)
    if report is None:
        return _record(schedule, now, RunResult(STATUS_FAILED, error=f"Unknown report: {schedule.report_type}"))
    fmt = schedule.format or "pdf"
    period = schedule.period or DEFAULT_PERIOD
    today = now.replace(tzinfo=dt.UTC).astimezone(tz).date()
    try:
        start, end = period_dates(period, today)
        request = build_request(schedule.report_type, parse_parameters(schedule.parameters_json), fmt, start, end)
        frame = await reports_service.build_report(db, schedule.report_type, report_params(request))
        content, media_type, exported_name = reports_service.export_dataframe(frame, fmt, schedule.report_type)
    except HTTPException as exc:
        return _record(schedule, now, RunResult(STATUS_FAILED, error=f"The report could not be built: {exc.detail}"))
    except ValueError as exc:
        return _record(schedule, now, RunResult(STATUS_FAILED, error=f"The report could not be built: {exc}"))
    except Exception:
        logger.exception("Scheduled report %s: building %s failed", schedule.id, schedule.report_type)
        return _record(
            schedule,
            now,
            RunResult(STATUS_FAILED, error="The report could not be built. The server log has the details."),
        )

    if len(content) > MAX_ATTACHMENT_BYTES:
        size = len(content) / (1024 * 1024)
        limit = MAX_ATTACHMENT_BYTES // (1024 * 1024)
        return _record(
            schedule,
            now,
            RunResult(
                STATUS_FAILED,
                error=(
                    f"The report came to {size:.1f} MB, over the {limit} MB an email may carry. Narrow it "
                    "(a shorter period or a filter), or download it from the Reports page."
                ),
            ),
        )

    dated = bool(report["needs_date"])
    subject, body = _message(
        title=str(report["title"]),
        dated=dated,
        start=start,
        end=end,
        today=today,
        period=period,
        rows=len(frame.index),
        fmt=fmt,
    )
    attachment = EmailAttachment(
        filename=_attachment_name(schedule.report_type, exported_name, *((start, end) if dated else (today, today))),
        content=content,
        mime_type=media_type,
    )
    result = RunResult(STATUS_SENT)
    recipients = recipients_of(schedule)
    refused: dict[str, str] = {}
    stopped: str | None = None
    left: list[str] = []
    for index, address in enumerate(recipients):
        try:
            await send_email(db, to_address=address, subject=subject, body_text=body, attachments=[attachment])
        except SmtpRecipientError as exc:
            # That address's problem: the others still get the report.
            refused[address] = str(exc)
            continue
        except (SmtpNotConfiguredError, SmtpSendError) as exc:
            stopped = str(exc)
        except Exception as exc:
            logger.exception("Scheduled report %s: sending failed", schedule.id)
            stopped = f"Sending failed ({exc.__class__.__name__}). The server log has the details."
        if stopped is not None:
            # The server cannot send: every message after this one would fail the same way.
            left = recipients[index:]
            break
        result.sent.append(address)

    result.not_sent = {**refused, **dict.fromkeys(left, stopped or "")}
    if result.not_sent:
        result.status = STATUS_PARTIAL if result.sent else STATUS_FAILED
        lines = [f"{stopped} Not sent to {', '.join(left)}."] if left else []
        lines.extend(f"{address}: {reason}" for address, reason in refused.items())
        result.error = "\n".join(lines)
    log = logger.info if result.status == STATUS_SENT else logger.warning
    log(
        "Scheduled report %s (%s): %s, sent to %s of %s",
        schedule.id,
        schedule.report_type,
        result.status,
        len(result.sent),
        len(recipients),
    )
    return _record(schedule, now, result)


# --- the job -------------------------------------------------------------------


async def _pause_unrunnable(db: AsyncSession, schedule_id: int, reason: str, now: dt.datetime) -> None:
    await db.execute(
        update(ReportSchedule)
        .where(ReportSchedule.id == schedule_id)
        .values(
            is_active=False,
            last_run_at=now,
            last_status=STATUS_FAILED,
            last_error=f"This schedule cannot run: {reason} It was paused."[:_MAX_ERROR_CHARS],
        )
        .execution_options(synchronize_session=False)
    )


def first_run(cron_expression: str, now: dt.datetime, tz: dt.tzinfo | None = None) -> dt.datetime:
    """When a schedule set up (or resumed) at ``now`` first runs. Raises ValueError if never."""
    following = next_run_after(schedule_trigger(cron_expression, tz), now)
    if following is None:
        raise ValueError("The cron expression never comes round (a date that does not exist?).")
    return following


async def _run_one(
    session_factory: async_sessionmaker[AsyncSession],
    schedule_id: int,
    cron_expression: str,
    due_at: dt.datetime,
    now: dt.datetime,
    tz: dt.tzinfo,
) -> str | None:
    """Claim one due schedule and run it. The status, or None if someone else had it."""
    async with session_factory() as db:
        try:
            following = first_run(cron_expression, now, tz)
        except ValueError as exc:
            await _pause_unrunnable(db, schedule_id, str(exc), now)
            await db.commit()
            return STATUS_FAILED
        claimed = await db.execute(
            update(ReportSchedule)
            .where(
                ReportSchedule.id == schedule_id,
                ReportSchedule.next_run_at == due_at,
                ReportSchedule.is_active.is_(True),
            )
            .values(next_run_at=following, last_run_at=now, last_status=STATUS_RUNNING, last_error=None)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        if claimed.rowcount != 1:
            # Another worker ran it, or it was paused or deleted meanwhile.
            return None
        schedule = await db.get(ReportSchedule, schedule_id)
        if schedule is None:
            return None
        try:
            result = await run_schedule(db, schedule, now=now, tz=tz)
            await db.commit()
        except Exception:
            # Say so on the row rather than leave it running; the caller logs it.
            await db.rollback()
            await db.execute(
                update(ReportSchedule)
                .where(ReportSchedule.id == schedule_id)
                .values(
                    last_status=STATUS_FAILED,
                    last_error="The run failed unexpectedly. The server log has the details.",
                )
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            raise
        return result.status


async def run_due_schedules(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: dt.datetime | None = None,
    tz: dt.tzinfo | None = None,
) -> dict[str, int]:
    """Run every active schedule whose next run time has come.

    A schedule without a next run time (saved before runs were kept) is
    given one and waits for it. One schedule failing does not stop the rest.
    """
    now = now or utcnow()
    tz = tz or get_server_timezone()
    counts = {"ran": 0, STATUS_SENT: 0, STATUS_PARTIAL: 0, STATUS_FAILED: 0}
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(ReportSchedule.id, ReportSchedule.cron_expression, ReportSchedule.next_run_at)
                .where(ReportSchedule.is_active.is_(True))
                .order_by(ReportSchedule.id)
            )
        ).all()
        due: list[tuple[int, str, dt.datetime]] = []
        for schedule_id, cron_expression, next_run_at in rows:
            if next_run_at is not None:
                if next_run_at <= now:
                    due.append((int(schedule_id), str(cron_expression), next_run_at))
                continue
            try:
                start = first_run(str(cron_expression), now, tz)
            except ValueError as exc:
                await _pause_unrunnable(db, int(schedule_id), str(exc), now)
                continue
            await db.execute(
                update(ReportSchedule)
                .where(ReportSchedule.id == schedule_id, ReportSchedule.next_run_at.is_(None))
                .values(next_run_at=start)
                .execution_options(synchronize_session=False)
            )
        await db.commit()

    for schedule_id, cron_expression, due_at in due:
        try:
            status = await _run_one(session_factory, schedule_id, cron_expression, due_at, now, tz)
        except Exception:
            logger.exception("Scheduled report %s failed", schedule_id)
            counts[STATUS_FAILED] += 1
            continue
        if status is not None:
            counts["ran"] += 1
            counts[status] += 1
    return counts
