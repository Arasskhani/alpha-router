"""Admin › Tickets › Overview: every block, the filters, the previous period, buckets, the backlog replay, access."""

from __future__ import annotations

import csv
import datetime
import io
import json

import pytest

from app.config import get_settings
from app.core.security import create_access_token
from app.models.support_ticket import SupportTicket, SupportTicketMessage
from app.models.user import User
from app.services import support_ticket_overview as ov
from app.services import support_tickets as st
from app.services.rbac import READ_ONLY_SUPER_ADMIN_SLUG, SUPPORT_SLUG
from app.services.user_role_service import set_user_roles

BASE = "/api/admin/tickets"
CSRF = "csrf-token"
NOW = datetime.datetime(2026, 10, 22, 12, 0, 0)
WEEK_LABELS = ["10-15", "10-16", "10-17", "10-18", "10-19", "10-20", "10-21", "10-22"]


def at(day: int, hour: int = 0, minute: int = 0, month: int = 10) -> datetime.datetime:
    return datetime.datetime(2026, month, day, hour, minute)


@pytest.fixture(autouse=True)
def _frozen(monkeypatch, session_factory):
    monkeypatch.setattr(ov, "_utcnow", lambda: NOW)
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)


def sign_in(client, account) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(account.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


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
        "number": 5000 + next(_SEQ),
        "user_id": reporter.id,
        "reporter_name": "Reporter",
        "reporter_username": reporter.username,
        "title": "Never in the overview",
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


def _event(db, ticket, when, **facts) -> None:
    db.add(
        SupportTicketMessage(ticket_id=ticket.id, kind="event", body="", event_json=json.dumps(facts), created_at=when)
    )


def _message(db, ticket, when, kind) -> None:
    db.add(SupportTicketMessage(ticket_id=ticket.id, kind=kind, body="text", created_at=when))


def _status(db, ticket, when, old, new) -> None:
    _event(db, ticket, when, type="status", by="Staff", by_id=1, to=new, **{"from": old})


@pytest.fixture
async def team(db_session, admin):
    majid = await _person(db_session, "majid", roles=[SUPPORT_SLUG], display="Majid Arasskhani")
    return {"admin": admin, "majid": majid}


@pytest.fixture
async def seeded(db_session, user, team):
    """Ten tickets around a week ending 2026-10-22 12:00 UTC (the window starts 10-15 12:00, the previous one 10-08 12:00)."""
    db = db_session
    majid, boss = team["majid"], team["admin"]
    t = {}
    # T1: urgent, Finance, nobody has answered.
    t[1] = await _ticket(db, user, at(20, 9), reporter_department="Finance", priority="urgent")
    # T2: IT, answered in 30 minutes, in progress, Majid's.
    t[2] = await _ticket(
        db,
        user,
        at(21, 10),
        reporter_department="IT",
        category="Question",
        status="in_progress",
        assignee_id=majid.id,
        first_staff_reply_at=at(21, 10, 30),
        needs_staff=False,
    )
    _message(db, t[2], at(21, 10, 0), "auto")
    _message(db, t[2], at(21, 10, 5), "note")
    _message(db, t[2], at(21, 10, 30), "staff")
    _status(db, t[2], at(21, 10, 30), "open", "in_progress")
    # T3: Finance, high, answered in 1 hour, resolved by staff a day later; the admin's.
    t[3] = await _ticket(
        db,
        user,
        at(16, 8),
        reporter_department="Finance",
        priority="high",
        status="resolved",
        assignee_id=boss.id,
        first_staff_reply_at=at(16, 9),
        resolved_at=at(17, 8),
        resolved_by="staff",
        needs_staff=False,
    )
    _status(db, t[3], at(16, 9), "open", "in_progress")
    _status(db, t[3], at(17, 8), "in_progress", "resolved")
    # T4: Finance, Problem, answered in 2 hours, waited, closed automatically.
    t[4] = await _ticket(
        db,
        user,
        at(18, 12),
        reporter_department="Finance",
        category="Problem",
        status="closed",
        first_staff_reply_at=at(18, 14),
        closed_at=at(21, 14),
        closed_reason="auto",
        needs_staff=False,
    )
    _status(db, t[4], at(18, 14), "open", "waiting")
    _event(db, t[4], at(21, 14), type="auto_closed", days=3)
    # T5: opened in the previous period, resolved by the person, reopened in this one, resolved again by them.
    t[5] = await _ticket(
        db,
        user,
        at(10, 12),
        reporter_department="Legal",
        priority="low",
        status="resolved",
        first_staff_reply_at=at(10, 13),
        resolved_at=at(19, 12),
        resolved_by="user",
        reopened_count=1,
        needs_staff=False,
    )
    _event(db, t[5], at(11, 12), type="resolved", by="Reporter", by_id=user.id)
    _message(db, t[5], at(16, 12), "user")
    _event(db, t[5], at(16, 12), type="reopened", by="Reporter", by_id=user.id)
    _event(db, t[5], at(19, 12), type="resolved", by="Reporter", by_id=user.id)
    # T6: a category the settings no longer offer; waited, then the person replied (no event for that).
    t[6] = await _ticket(
        db,
        user,
        at(19, 8),
        reporter_department="IT",
        category="Billing",
        status="open",
        assignee_id=majid.id,
        first_staff_reply_at=at(19, 9),
    )
    _status(db, t[6], at(19, 9), "open", "waiting")
    _message(db, t[6], at(20, 10), "user")
    # T7: opened and closed by staff in the previous period.
    t[7] = await _ticket(db, user, at(9, 12), status="closed", closed_at=at(12, 9), closed_reason="manual")
    _status(db, t[7], at(12, 9), "open", "closed")
    # T8: long gone; touches nothing.
    t[8] = await _ticket(
        db, user, at(1, 9, month=9), status="closed", closed_at=at(2, 9, month=9), closed_reason="manual"
    )
    # T9: opened in the previous period and in progress ever since; the admin's.
    t[9] = await _ticket(
        db,
        user,
        at(12, 10),
        reporter_department="IT",
        category="Question",
        status="in_progress",
        assignee_id=boss.id,
        first_staff_reply_at=at(12, 11),
        needs_staff=False,
    )
    _status(db, t[9], at(12, 11), "open", "in_progress")
    # T10: resolved long ago, closed when its reopen window passed, in this period.
    t[10] = await _ticket(
        db,
        user,
        at(1, 9),
        status="closed",
        resolved_at=at(3, 9),
        resolved_by="staff",
        closed_at=at(17, 9),
        closed_reason="resolved",
    )
    _status(db, t[10], at(3, 9), "open", "resolved")
    _event(db, t[10], at(17, 9), type="closed_resolved", days=14)
    await db.commit()
    return t


async def _overview(db, **kwargs):
    filters = ov.OverviewFilters(**kwargs.pop("filters", {}))
    return await ov.build_overview(db, timezone=kwargs.pop("timezone", "utc"), filters=filters, **kwargs)


def _labels(chart):
    return [row["label"] for row in chart]


class TestKpis:
    async def test_every_kpi_and_its_change_against_the_previous_week(self, db_session, seeded):
        data = await _overview(db_session, period="week")
        assert (data["period"], data["period_label"], data["timezone"]) == ("week", "Past 1 Week", "utc")
        k = data["kpis"]
        assert k["opened"] == {"value": 5, "change_pct": 66.7, "sparkline": [0, 1, 0, 1, 1, 1, 1, 0]}
        assert k["resolved"]["value"] == 2 and k["resolved"]["change_pct"] == 100.0  # nothing resolved before
        assert k["resolved"]["sparkline"] == [0, 0, 1, 0, 1, 0, 0, 0]
        # Active now: T1, T2, T6, T9; at the start of the week only T9 was.
        assert k["open_now"]["value"] == 4 and k["open_now"]["change_pct"] == 300.0
        assert k["open_now"]["unanswered"] == 1
        assert k["open_now"]["sparkline"] == [1, 3, 2, 3, 3, 4, 4, 4]
        # 30, 60, 120, 60 minutes this week; 60 and 60 the week before.
        assert k["first_reply_minutes"]["value"] == 60.0 and k["first_reply_minutes"]["change_pct"] == 0.0
        assert k["first_reply_minutes"]["sparkline"] == [60.0, 60.0, 60.0, 120.0, 60.0, 60.0, 30.0, 30.0]
        # T3 took 24 hours, T5 216 (opened 10-10, resolved 10-19); nothing to compare with.
        assert k["resolution_hours"]["value"] == 120.0 and k["resolution_hours"]["change_pct"] is None
        assert k["auto_closed"]["value"] == 1 and k["auto_closed"]["change_pct"] == 100.0
        assert k["auto_closed"]["share_pct"] == 50.0  # T4 of T4 and T10 closed this week
        assert k["auto_closed"]["sparkline"] == [0, 0, 0, 0, 0, 0, 1, 0]

    async def test_the_automatic_reply_and_notes_are_never_a_first_reply(self, db_session, user, team, monkeypatch):
        clock = {"now": NOW - datetime.timedelta(hours=5)}
        monkeypatch.setattr(st, "_now", lambda: clock["now"])
        ticket = await st.create_ticket(
            db_session,
            user=user,
            title="Export fails",
            description="It stops at 90%.",
            category="Bug",
            priority="high",
            context=None,
            images=[],
            settings=st.TicketSettings(),
        )
        clock["now"] += datetime.timedelta(minutes=10)
        await st.add_staff_message(
            db_session, ticket=ticket, staff=team["majid"], body="Looking", internal=True, images=[], status=None
        )
        clock["now"] += datetime.timedelta(minutes=35)
        await st.add_staff_message(
            db_session, ticket=ticket, staff=team["majid"], body="Fixed?", internal=False, images=[], status=None
        )
        await db_session.commit()
        data = await _overview(db_session, period="day")
        assert data["kpis"]["first_reply_minutes"]["value"] == 45.0
        assert data["first_reply_by_priority"] == [{"priority": "high", "tickets": 1, "median_minutes": 45.0}]
        assert data["kpis"]["open_now"]["unanswered"] == 0
        # The staff reply moved it to In progress, with an event the backlog replays.
        assert data["backlog"]["segments"][1] == {
            "key": "in_progress",
            "label": "In progress",
            "color": "#a78bfa",
            "value": 1,
        }


class TestLists:
    async def test_top_departments(self, db_session, seeded):
        data = await _overview(db_session, period="week")
        assert data["top_departments"] == [
            {"department": "Finance", "opened": 3, "still_open": 1, "urgent_open": 1},
            {"department": "IT", "opened": 2, "still_open": 2, "urgent_open": 0},
        ]

    async def test_workload_lists_the_team_and_unassigned_last(self, db_session, seeded, team):
        data = await _overview(db_session, period="week")
        assert data["workload"] == [
            {
                "user_id": team["majid"].id,
                "name": "Majid Arasskhani",
                "role_label": "Support",
                "open": 2,
                "resolved": 0,
            },
            {
                "user_id": team["admin"].id,
                "name": "fixture_admin",
                "role_label": "Super Admin",
                "open": 1,
                "resolved": 1,
            },
            {
                "user_id": None,
                "name": "Unassigned",
                "role_label": "",
                "open": 1,
                "resolved": 1,
                "oldest_wait_minutes": 51 * 60,  # T1, opened 10-20 09:00
            },
        ]

    async def test_first_reply_by_priority_urgent_first(self, db_session, seeded):
        data = await _overview(db_session, period="week")
        assert data["first_reply_by_priority"] == [
            {"priority": "high", "tickets": 1, "median_minutes": 60.0},
            {"priority": "normal", "tickets": 3, "median_minutes": 60.0},
        ]

    async def test_options(self, db_session, seeded, team):
        data = await _overview(db_session, period="week")
        assert data["options"] == {
            "departments": ["Finance", "IT", "Legal"],
            "assignees": [
                {"id": team["admin"].id, "name": "fixture_admin"},
                {"id": team["majid"].id, "name": "Majid Arasskhani"},
            ],
            "categories": ["Bug", "Problem", "Question", "Feature request", "Billing"],
        }


class TestCharts:
    async def test_opened_by_priority_stacks_per_day(self, db_session, seeded):
        block = (await _overview(db_session, period="week"))["opened_by_priority"]
        assert [(s["key"], s["label"], s["color"], s["value"]) for s in block["segments"]] == [
            ("low", "Low", "#94a3b8", 0),
            ("normal", "Normal", "#38bdf8", 3),
            ("high", "High", "#f59e0b", 1),
            ("urgent", "Urgent", "#f87171", 1),
        ]
        assert _labels(block["chart"]) == WEEK_LABELS
        by_label = {row["label"]: row for row in block["chart"]}
        assert by_label["10-16"]["high"] == 1 and by_label["10-20"]["urgent"] == 1
        assert sum(row["normal"] for row in block["chart"]) == 3

    async def test_how_tickets_ended(self, db_session, seeded):
        ended = (await _overview(db_session, period="week"))["ended"]
        assert ended["total"] == 3
        assert [(s["key"], s["label"], s["color"], s["value"]) for s in ended["segments"]] == [
            ("staff", "Resolved by support", "#34d399", 1),
            ("user", "Resolved by the user", "#5eead4", 1),
            ("auto", "Auto-closed (no reply in 7 days)", "#94a3b8", 1),
        ]
        by_label = {row["label"]: row for row in ended["chart"]}
        assert (by_label["10-17"]["staff"], by_label["10-19"]["user"], by_label["10-21"]["auto"]) == (1, 1, 1)
        assert (ended["reopened"], ended["reopened_pct"]) == (1, 33.3)

    async def test_backlog_is_replayed_from_the_thread(self, db_session, seeded):
        backlog = (await _overview(db_session, period="week"))["backlog"]
        assert backlog["total"] == 4
        assert [(s["key"], s["label"], s["color"], s["value"]) for s in backlog["segments"]] == [
            ("open", "Open", "#60a5fa", 2),
            ("in_progress", "In progress", "#a78bfa", 2),
            ("waiting", "Waiting for user", "#fbbf24", 0),
        ]
        assert [(row["label"], row["open"], row["in_progress"], row["waiting"]) for row in backlog["chart"]] == [
            ("10-15", 0, 1, 0),  # T9
            ("10-16", 1, 2, 0),  # T3 in progress, T5 reopened
            ("10-17", 1, 1, 0),  # T3 resolved
            ("10-18", 1, 1, 1),  # T4 waits
            ("10-19", 0, 1, 2),  # T5 resolved again, T6 waits
            ("10-20", 2, 1, 1),  # T1 opened, T6's reply moved it back to open
            ("10-21", 2, 2, 0),  # T2 in progress, T4 closed automatically
            ("10-22", 2, 2, 0),
        ]
        assert backlog["oldest_unanswered_minutes"] == 51 * 60

    async def test_by_category_keeps_settings_order_and_old_categories(self, db_session, seeded):
        block = (await _overview(db_session, period="week"))["by_category"]
        assert block["total"] == 5
        assert [(s["key"], s["label"], s["color"], s["value"]) for s in block["segments"]] == [
            ("bug", "Bug", "#fb7185", 2),
            ("problem", "Problem", "#f59e0b", 1),
            ("question", "Question", "#38bdf8", 1),
            ("feature_request", "Feature request", "#a78bfa", 0),
            ("billing", "Billing", "#34d399", 1),
        ]
        assert block["most_common"] == {"label": "Bug", "pct": 40.0}
        assert {row["label"]: row["billing"] for row in block["chart"]}["10-19"] == 1
        assert set(block["chart"][0]) == {"bucket", "label", "bug", "problem", "question", "feature_request", "billing"}

    def test_category_keys_stay_unique_and_off_the_row_fields(self):
        keys = ov.category_keys(["Bug", "bug!", "Label", "باگ", "???"])
        assert keys == {"Bug": "bug", "bug!": "bug_2", "Label": "label_2", "باگ": "باگ", "???": "category"}


class TestBuckets:
    async def test_a_day_is_hourly(self, db_session, seeded):
        data = await _overview(db_session, period="day")
        chart = data["ended"]["chart"]
        assert len(chart) == 25 and chart[0]["label"] == "12:00" and chart[-1]["label"] == "12:00"
        assert next(row for row in chart if row["auto"])["label"] == "14:00"
        assert len(data["kpis"]["opened"]["sparkline"]) == 25
        assert data["kpis"]["opened"]["value"] == 0  # T2 was opened at 10:00 the day before

    async def test_a_year_is_monthly(self, db_session, seeded):
        data = await _overview(db_session, period="year")
        labels = _labels(data["opened_by_priority"]["chart"])
        assert labels[0] == "2025-10" and labels[-1] == "2026-10" and len(labels) == 13
        assert data["kpis"]["opened"]["value"] == 10  # all of them, T8 (September) included
        assert data["kpis"]["opened"]["sparkline"][-2:] == [1, 9]

    async def test_local_time_uses_the_activity_buckets(self, db_session, seeded):
        data = await _overview(db_session, period="week", timezone="local")
        since = NOW - datetime.timedelta(days=7)
        expected = [ov.bucket_label(k, "week", "local") for k in ov.bucket_keys("week", since, NOW, "local")]
        assert data["timezone"] == "local" and _labels(data["backlog"]["chart"]) == expected


class TestFilters:
    @pytest.mark.parametrize(
        ("filters", "opened", "open_now"),
        [
            ({"priority": "normal"}, 3, 3),  # T2, T4, T6 opened; T2, T6, T9 open
            ({"department": "Finance"}, 3, 1),
            ({"category": "Billing"}, 1, 1),
            ({"status": "closed"}, 1, 0),
            ({"assignee": "none"}, 2, 1),
        ],
    )
    async def test_filters_apply_to_every_number(self, db_session, seeded, filters, opened, open_now):
        data = await _overview(db_session, period="week", filters=filters)
        assert data["kpis"]["opened"]["value"] == opened
        assert data["kpis"]["open_now"]["value"] == open_now
        assert data["backlog"]["total"] == open_now
        assert data["by_category"]["total"] == opened
        assert sum(s["value"] for s in data["opened_by_priority"]["segments"]) == opened

    async def test_one_assignee(self, db_session, seeded, team):
        data = await _overview(db_session, period="week", filters={"assignee": str(team["majid"].id)})
        assert data["kpis"]["open_now"]["value"] == 2
        rows = {row["name"]: row for row in data["workload"]}
        assert rows["Majid Arasskhani"]["open"] == 2 and rows["fixture_admin"]["open"] == 0
        assert rows["Unassigned"]["open"] == 0 and rows["Unassigned"]["oldest_wait_minutes"] is None
        # Options never narrow: the menu still offers everything.
        assert len(data["options"]["departments"]) == 3


class TestEmpty:
    async def test_no_tickets(self, db_session, admin):
        data = await _overview(db_session, period="week")
        k = data["kpis"]
        assert k["opened"] == {"value": 0, "change_pct": None, "sparkline": [0] * 8}
        assert k["first_reply_minutes"] == {"value": None, "change_pct": None, "sparkline": [0.0] * 8}
        assert k["auto_closed"]["share_pct"] is None and k["open_now"]["unanswered"] == 0
        assert data["top_departments"] == [] and data["first_reply_by_priority"] == []
        assert [w["name"] for w in data["workload"]] == ["fixture_admin", "Unassigned"]
        assert data["ended"]["total"] == 0 and data["ended"]["reopened_pct"] is None
        assert data["backlog"]["oldest_unanswered_minutes"] is None
        assert all(row["open"] == row["in_progress"] == row["waiting"] == 0 for row in data["backlog"]["chart"])
        assert data["by_category"]["most_common"] is None
        assert [s["value"] for s in data["by_category"]["segments"]] == [0, 0, 0, 0]
        assert data["options"]["categories"] == list(st.DEFAULT_CATEGORIES)


class TestApi:
    async def test_a_plain_user_is_refused(self, client, user):
        headers = sign_in(client, user)
        assert (await client.get(f"{BASE}/overview", headers=headers)).status_code == 403
        assert (await client.get(f"{BASE}/overview.csv", headers=headers)).status_code == 403

    @pytest.mark.parametrize("slug", [SUPPORT_SLUG, READ_ONLY_SUPER_ADMIN_SLUG])
    async def test_support_and_read_only_super_admin_read_it(self, client, db_session, slug):
        reader = await _person(db_session, "reader", roles=[slug])
        headers = sign_in(client, reader)
        response = await client.get(f"{BASE}/overview", headers=headers)
        assert response.status_code == 200
        assert set(response.json()) == {
            "period",
            "period_label",
            "timezone",
            "kpis",
            "top_departments",
            "workload",
            "first_reply_by_priority",
            "opened_by_priority",
            "ended",
            "backlog",
            "by_category",
            "options",
        }

    async def test_the_query_the_page_sends(self, client, admin, seeded):
        headers = sign_in(client, admin)
        response = await client.get(
            f"{BASE}/overview?period=week&timezone=utc&department=Finance&priority=&status=", headers=headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["kpis"]["opened"]["value"] == 3 and body["timezone"] == "utc"
        assert "Never in the overview" not in response.text  # no ticket text, ever

    @pytest.mark.parametrize(
        "query",
        ["period=fortnight", "timezone=tehran", "priority=critical", "status=done", "assignee=me", "assignee=0"],
    )
    async def test_bad_values_are_refused(self, client, admin, query):
        headers = sign_in(client, admin)
        assert (await client.get(f"{BASE}/overview?{query}", headers=headers)).status_code == 422

    async def test_csv_has_the_page_numbers_and_safe_cells(self, client, db_session, admin, user, seeded):
        await _ticket(db_session, user, at(22, 8), reporter_department="=HYPERLINK(evil)")
        await db_session.commit()
        headers = sign_in(client, admin)
        response = await client.get(f"{BASE}/overview.csv?period=week&timezone=utc", headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert 'filename="tickets-overview-week.csv"' in response.headers["content-disposition"]
        text = response.content.decode("utf-8")
        assert text.startswith("﻿")
        rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
        assert rows[0] == ["Section", "Item", "Measure", "Value"]
        assert ["Period", "Past 1 Week", "", ""] in rows
        assert ["KPIs", "Tickets opened", "Value", "6"] in rows
        assert ["KPIs", "Open now", "Waiting for a first answer", "2"] in rows
        assert ["Top departments", "'=HYPERLINK(evil)", "Opened", "1"] in rows
        assert ["Backlog by status", "10-19", "Waiting for user", "2"] in rows
        assert ["Tickets by category", "Most common", "Bug", "50.0"] in rows
        assert not any(cell.startswith("=") for row in rows for cell in row)
        assert "Never in the overview" not in text

    async def test_csv_states_the_filters(self, client, admin, seeded):
        headers = sign_in(client, admin)
        response = await client.get(f"{BASE}/overview.csv?period=week&assignee=none&priority=urgent", headers=headers)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8").lstrip("﻿"))))
        assert ["Filter", "Assignee", "", "Unassigned"] in rows
        assert ["Filter", "Priority", "", "Urgent"] in rows
        assert ["KPIs", "Tickets opened", "Value", "1"] in rows
