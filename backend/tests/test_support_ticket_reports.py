"""The Support tickets reports: Ticket summary, Tickets by department, Support performance."""

from __future__ import annotations

import datetime

import pytest

from app.config import get_settings
from app.core.security import create_access_token
from app.models.support_ticket import SupportTicket, SupportTicketMessage
from app.models.user import User
from app.services import reports_service
from app.services.rbac import SUPPORT_SLUG
from app.services.reports_catalog import CATEGORY_LABELS, REPORT_CATALOG, REPORT_IDS
from app.services.support_ticket_reports import (
    DEPARTMENT_COLUMNS,
    PERFORMANCE_COLUMNS,
    TICKET_SUMMARY_COLUMNS,
    report_support_performance,
    report_ticket_summary,
    report_tickets_by_department,
)
from app.services.user_role_service import set_user_roles

START = datetime.datetime(2026, 10, 1)
END = datetime.datetime(2026, 10, 31, 23, 59, 59)
SECRET_TITLE = "Payroll file of the CEO"


def at(day: int, hour: int = 0, minute: int = 0, month: int = 10) -> datetime.datetime:
    return datetime.datetime(2026, month, day, hour, minute)


async def _person(db, username, *, roles=None, display=None) -> User:
    person = User(username=username, email=f"{username}@corp.test", display_name=display, is_active=True)
    person.auth_provider = "local"
    db.add(person)
    await db.flush()
    if roles:
        await set_user_roles(db, person, roles)
    await db.commit()
    return person


_SEQ = iter(range(1, 10_000))


async def _ticket(db, reporter, created, **fields) -> SupportTicket:
    values = {
        "number": 7000 + next(_SEQ),
        "user_id": reporter.id,
        "reporter_name": "Reporter",
        "reporter_username": reporter.username,
        "title": SECRET_TITLE,
        "category": "Bug",
        "priority": "normal",
        "status": "open",
        "needs_staff": True,
        "user_unread": False,
        "created_at": created,
        "updated_at": created,
        "reopened_count": 0,
    }
    values.update(fields)
    row = SupportTicket(**values)
    db.add(row)
    await db.flush()
    return row


def _message(db, ticket, when, kind, author=None) -> None:
    db.add(
        SupportTicketMessage(
            ticket_id=ticket.id,
            kind=kind,
            body=SECRET_TITLE,
            author_id=author.id if author else None,
            created_at=when,
        )
    )


@pytest.fixture
async def seeded(db_session, user, admin):
    db = db_session
    majid = await _person(db, "majid", roles=[SUPPORT_SLUG], display="Majid Arasskhani")
    sam = await _person(db, "sam", display="Sam Former")  # replied once, no longer on the team
    # A: urgent bug; automatic reply and a note first, Majid's reply after 40 minutes; resolved a day later.
    a = await _ticket(
        db,
        user,
        at(5, 10),
        reporter_department="Finance",
        priority="urgent",
        status="resolved",
        assignee_id=majid.id,
        first_staff_reply_at=at(5, 10, 40),
        resolved_at=at(6, 10),
        resolved_by="staff",
    )
    _message(db, a, at(5, 10), "auto")
    _message(db, a, at(5, 10, 10), "note", majid)
    _message(db, a, at(5, 10, 40), "staff", majid)
    # B: the admin answered after 2 hours; closed automatically (never "resolved").
    b = await _ticket(
        db,
        user,
        at(7, 9),
        reporter_department="Finance",
        status="closed",
        assignee_id=admin.id,
        first_staff_reply_at=at(7, 11),
        closed_at=at(15, 9),
        closed_reason="auto",
    )
    _message(db, b, at(7, 11), "staff", admin)
    # C: high, IT; Sam answered first after 20 minutes, Majid later; still in progress.
    c = await _ticket(
        db,
        user,
        at(10, 8),
        reporter_department="IT",
        category="Question",
        priority="high",
        status="in_progress",
        assignee_id=majid.id,
        first_staff_reply_at=at(10, 8, 20),
    )
    _message(db, c, at(10, 8, 20), "staff", sam)
    _message(db, c, at(10, 9), "staff", majid)
    # D: no department, nobody has answered.
    await _ticket(db, user, at(12, 9), category="Question", priority="low")
    # E: opened in September, resolved by the person in October, unassigned.
    await _ticket(
        db,
        user,
        at(20, 9, month=9),
        status="resolved",
        first_staff_reply_at=at(20, 10, month=9),
        resolved_at=at(2, 9),
        resolved_by="user",
    )
    # F: after the range.
    await _ticket(db, user, at(2, 9, month=11), reporter_department="Legal")
    await db.commit()
    return {"majid": majid, "sam": sam, "admin": admin}


def _records(frame):
    return frame.to_dict(orient="records")


def test_the_catalog_has_the_support_category():
    support = [r for r in REPORT_CATALOG if r["category"] == "support"]
    assert [r["id"] for r in support] == ["ticket_summary", "tickets_by_department", "support_performance"]
    assert all(r["needs_date"] and r["params"] == [] for r in support)
    assert CATEGORY_LABELS["support"] == "Support tickets"
    assert len(REPORT_CATALOG) == len(REPORT_IDS) == 41


async def test_ticket_summary(db_session, seeded):
    frame = await report_ticket_summary(db_session, START, END)
    assert list(frame.columns) == TICKET_SUMMARY_COLUMNS
    assert _records(frame) == [
        {
            "category": "Bug",
            "opened": 2,
            "resolved": 2,
            "closed": 1,
            "still_open": 0,
            "urgent_high": 1,
            "auto_closed": 1,
            "median_first_reply_minutes": 80.0,  # 40 and 120: the automatic reply and the note never count
            "median_resolution_hours": 156.0,  # 24 and 288
        },
        {
            "category": "Question",
            "opened": 2,
            "resolved": 0,
            "closed": 0,
            "still_open": 2,
            "urgent_high": 1,
            "auto_closed": 0,
            "median_first_reply_minutes": 20.0,
            "median_resolution_hours": "",
        },
        {
            "category": "All categories",
            "opened": 4,
            "resolved": 2,
            "closed": 1,
            "still_open": 2,
            "urgent_high": 2,
            "auto_closed": 1,
            "median_first_reply_minutes": 40.0,
            "median_resolution_hours": 156.0,
        },
    ]


async def test_tickets_by_department(db_session, seeded):
    frame = await report_tickets_by_department(db_session, START, END)
    assert list(frame.columns) == DEPARTMENT_COLUMNS
    assert _records(frame) == [
        {"department": "Finance", "opened": 2, "still_open": 0, "still_open_pct": 0.0},
        {"department": "(no department)", "opened": 1, "still_open": 1, "still_open_pct": 100.0},
        {"department": "IT", "opened": 1, "still_open": 1, "still_open_pct": 100.0},
        {"department": "All departments", "opened": 4, "still_open": 2, "still_open_pct": 50.0},
    ]


async def test_support_performance(db_session, seeded):
    frame = await report_support_performance(db_session, START, END)
    assert list(frame.columns) == PERFORMANCE_COLUMNS
    assert _records(frame) == [
        {
            "person": "Majid Arasskhani",
            "role": "Support",
            "tickets_handled": 2,
            "first_replies": 1,
            "median_first_reply_minutes": 40.0,
            "resolved": 1,
            "median_resolution_hours": 24.0,
            "open_backlog": 1,
        },
        {
            "person": "fixture_admin",
            "role": "Super Admin",
            "tickets_handled": 1,
            "first_replies": 1,
            "median_first_reply_minutes": 120.0,
            "resolved": 0,
            "median_resolution_hours": "",
            "open_backlog": 0,
        },
        {
            "person": "Sam Former",
            "role": "No longer on the team",
            "tickets_handled": 1,
            "first_replies": 1,
            "median_first_reply_minutes": 20.0,
            "resolved": 0,
            "median_resolution_hours": "",
            "open_backlog": 0,
        },
        {
            "person": "Unassigned",
            "role": "",
            "tickets_handled": 0,
            "first_replies": 0,
            "median_first_reply_minutes": "",
            "resolved": 1,
            "median_resolution_hours": 288.0,
            "open_backlog": 2,  # D, and F (opened after the range: the backlog is today's)
        },
    ]


async def test_empty_ranges(db_session, seeded):
    early, late = datetime.datetime(2020, 1, 1), datetime.datetime(2020, 1, 31)
    summary = await report_ticket_summary(db_session, early, late)
    assert summary.empty and list(summary.columns) == TICKET_SUMMARY_COLUMNS
    departments = await report_tickets_by_department(db_session, early, late)
    assert departments.empty and list(departments.columns) == DEPARTMENT_COLUMNS
    performance = _records(await report_support_performance(db_session, early, late))
    assert [r["tickets_handled"] for r in performance] == [0, 0, 0]  # the team, then Unassigned
    assert performance[-1]["open_backlog"] == 2  # backlog is "now", whatever the range


@pytest.mark.parametrize("report_type", ["ticket_summary", "tickets_by_department", "support_performance"])
@pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf"])
async def test_every_format_through_the_report_runner(db_session, seeded, report_type, fmt):
    frame = await reports_service.build_report(db_session, report_type, {"_start": START, "_end": END})
    assert not frame.empty
    content, media, name = reports_service.export_dataframe(frame, fmt, report_type)
    assert content and name == f"{report_type}.{fmt}"
    if fmt == "csv":
        assert SECRET_TITLE not in content.decode("utf-8")


async def test_preview_through_the_reports_api(client, db_session, admin, seeded, monkeypatch, session_factory):
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(admin.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, "csrf")
    for report_type in ("ticket_summary", "tickets_by_department", "support_performance"):
        response = await client.post(
            "/api/admin/reports/preview",
            json={"report_type": report_type, "start_date": "2026-10-01", "end_date": "2026-10-31"},
            headers={settings.csrf_header_name: "csrf"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["row_count"] > 0
        assert SECRET_TITLE not in response.text
