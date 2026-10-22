"""The Support tickets reports (Admin › Reports): aggregates only, never a ticket's title or text.

The metric rules are the Overview's (``app.services.support_ticket_overview``):
"first reply" is the first staff reply (the automatic reply and internal notes
never count) and an auto-closed ticket is never "resolved". A report covers
``start`` .. ``end`` inclusive, in UTC like every ticket timestamp.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

import pandas as pd
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_ticket import SupportTicket, SupportTicketMessage
from app.models.user import User
from app.services import support_tickets as st
from app.services.support_ticket_overview import first_reply_minutes, is_resolved, resolution_hours

TICKET_SUMMARY_COLUMNS = [
    "category",
    "opened",
    "resolved",
    "closed",
    "still_open",
    "urgent_high",
    "auto_closed",
    "median_first_reply_minutes",
    "median_resolution_hours",
]
DEPARTMENT_COLUMNS = ["department", "opened", "still_open", "still_open_pct"]
PERFORMANCE_COLUMNS = [
    "person",
    "role",
    "tickets_handled",
    "first_replies",
    "median_first_reply_minutes",
    "resolved",
    "median_resolution_hours",
    "open_backlog",
]
NO_DEPARTMENT = "(no department)"


def _median(values: Iterable[float | None]) -> float | None:
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    mid = len(data) // 2
    value = data[mid] if len(data) % 2 else (data[mid - 1] + data[mid]) / 2
    return round(float(value), 1)


def _frame(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    """A missing median is a blank cell: NaN would break the JSON preview and print as "nan" in a PDF."""
    return pd.DataFrame([{k: ("" if v is None else v) for k, v in r.items()} for r in rows], columns=columns)


def _within(start: datetime.datetime, end: datetime.datetime) -> Callable[[datetime.datetime | None], bool]:
    return lambda dt: dt is not None and start <= dt <= end


async def _tickets_in_range(db: AsyncSession, start: datetime.datetime, end: datetime.datetime) -> list[Any]:
    """Tickets opened, resolved or closed in the range (their numbers and times, never their text)."""
    query = select(
        SupportTicket.id,
        SupportTicket.created_at,
        SupportTicket.status,
        SupportTicket.priority,
        SupportTicket.category,
        SupportTicket.reporter_department,
        SupportTicket.assignee_id,
        SupportTicket.first_staff_reply_at,
        SupportTicket.resolved_at,
        SupportTicket.closed_at,
        SupportTicket.closed_reason,
    ).where(
        or_(
            SupportTicket.created_at.between(start, end),
            SupportTicket.resolved_at.between(start, end),
            SupportTicket.closed_at.between(start, end),
        )
    )
    return list((await db.execute(query)).all())


def _summary_row(label: str, rows: list[Any], within: Callable[[datetime.datetime | None], bool]) -> dict[str, Any]:
    opened = [t for t in rows if within(t.created_at)]
    resolved = [t for t in rows if is_resolved(t) and within(t.resolved_at)]
    return {
        "category": label,
        "opened": len(opened),
        "resolved": len(resolved),
        "closed": sum(1 for t in rows if within(t.closed_at)),
        "still_open": sum(1 for t in opened if t.status in st.ACTIVE_STATUSES),
        "urgent_high": sum(1 for t in opened if t.priority in ("urgent", "high")),
        "auto_closed": sum(1 for t in rows if t.closed_reason == "auto" and within(t.closed_at)),
        "median_first_reply_minutes": _median(first_reply_minutes(t) for t in opened),
        "median_resolution_hours": _median(resolution_hours(t) for t in resolved),
    }


async def report_ticket_summary(db: AsyncSession, start: datetime.datetime, end: datetime.datetime) -> pd.DataFrame:
    """Per category: opened, resolved, closed, still open (of those opened), Urgent+High, auto-closed, medians."""
    tickets = await _tickets_in_range(db, start, end)
    if not tickets:
        return pd.DataFrame(columns=TICKET_SUMMARY_COLUMNS)
    within = _within(start, end)
    by_category: dict[str, list[Any]] = defaultdict(list)
    for t in tickets:
        by_category[str(t.category)].append(t)
    rows = [_summary_row(label, group, within) for label, group in by_category.items()]
    rows.sort(key=lambda r: (-r["opened"], -r["resolved"], str(r["category"]).casefold()))
    rows.append(_summary_row("All categories", tickets, within))
    return _frame(rows, TICKET_SUMMARY_COLUMNS)


async def report_tickets_by_department(
    db: AsyncSession, start: datetime.datetime, end: datetime.datetime
) -> pd.DataFrame:
    """Tickets opened per reporter department in the range, with how many (and what share) are still open."""
    rows = (
        await db.execute(
            select(SupportTicket.reporter_department, SupportTicket.status).where(
                SupportTicket.created_at.between(start, end)
            )
        )
    ).all()
    if not rows:
        return pd.DataFrame(columns=DEPARTMENT_COLUMNS)
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for department, status in rows:
        entry = counts[str(department).strip() if department and str(department).strip() else NO_DEPARTMENT]
        entry[0] += 1
        entry[1] += int(status in st.ACTIVE_STATUSES)

    def row(label: str, opened: int, still_open: int) -> dict[str, Any]:
        return {
            "department": label,
            "opened": opened,
            "still_open": still_open,
            "still_open_pct": round(still_open / opened * 100.0, 1) if opened else 0.0,
        }

    out = [row(label, o, s) for label, (o, s) in counts.items()]
    out.sort(key=lambda r: (-r["opened"], str(r["department"]).casefold()))
    out.append(row("All departments", sum(c[0] for c in counts.values()), sum(c[1] for c in counts.values())))
    return _frame(out, DEPARTMENT_COLUMNS)


async def report_support_performance(
    db: AsyncSession, start: datetime.datetime, end: datetime.datetime
) -> pd.DataFrame:
    """Per support person: tickets handled (replied to in the range), first replies, resolutions and backlog.

    - *tickets handled*: tickets the person wrote a staff reply on in the range (notes do not count);
    - *first replies*: tickets whose first staff reply was theirs and fell in the range, with the median
      minutes from opening to it;
    - *resolved*: tickets resolved in the range while assigned to them, with the median hours to resolve;
    - *open backlog*: active tickets assigned to them now.
    The last row, "Unassigned", holds what was resolved without an assignee and the unassigned backlog.
    """
    staff = await st.assignable_staff(db)
    replies = (
        await db.execute(
            select(SupportTicketMessage.ticket_id, SupportTicketMessage.author_id, SupportTicketMessage.created_at)
            .where(SupportTicketMessage.kind == "staff", SupportTicketMessage.created_at.between(start, end))
            .order_by(SupportTicketMessage.created_at, SupportTicketMessage.id)
        )
    ).all()
    first_replied = {
        int(t.id): t.created_at
        for t in (
            await db.execute(
                select(SupportTicket.id, SupportTicket.created_at).where(
                    SupportTicket.first_staff_reply_at.between(start, end)
                )
            )
        ).all()
    }
    resolved = [t for t in await _tickets_in_range(db, start, end) if is_resolved(t) and start <= t.resolved_at <= end]
    unassigned_open = len(
        (
            await db.execute(
                select(SupportTicket.id).where(
                    SupportTicket.assignee_id.is_(None), SupportTicket.status.in_(st.ACTIVE_STATUSES)
                )
            )
        ).all()
    )

    handled: dict[int, set[int]] = defaultdict(set)
    first_minutes: dict[int, list[float]] = defaultdict(list)
    seen_first: set[int] = set()
    for ticket_id, author_id, created_at in replies:
        if author_id is not None:
            handled[int(author_id)].add(int(ticket_id))
        if int(ticket_id) in first_replied and int(ticket_id) not in seen_first:
            seen_first.add(int(ticket_id))  # the earliest staff reply in the range is the first one
            if author_id is not None:
                first_minutes[int(author_id)].append(
                    (created_at - first_replied[int(ticket_id)]).total_seconds() / 60.0
                )
    resolved_by: dict[int | None, list[float]] = defaultdict(list)
    for t in resolved:
        resolved_by[t.assignee_id].append(resolution_hours(t) or 0.0)

    people: dict[int, tuple[str, str, int]] = {s.id: (s.name, s.role_label, s.open_count) for s in staff}
    others = (set(handled) | set(first_minutes) | {k for k in resolved_by if k is not None}) - set(people)
    if others:
        for person in (await db.execute(select(User).where(User.id.in_(others)))).scalars():
            people[int(person.id)] = (st.display_name(person), "No longer on the team", 0)

    def row(person: str, role: str, key: int | None, backlog: int) -> dict[str, Any]:
        minutes = first_minutes.get(key, []) if key is not None else []
        hours = resolved_by.get(key, [])
        return {
            "person": person,
            "role": role,
            "tickets_handled": len(handled.get(key, ())) if key is not None else 0,
            "first_replies": len(minutes),
            "median_first_reply_minutes": _median(minutes),
            "resolved": len(hours),
            "median_resolution_hours": _median(hours),
            "open_backlog": backlog,
        }

    out = [row(name, role, pid, backlog) for pid, (name, role, backlog) in people.items()]
    out.sort(key=lambda r: (-r["tickets_handled"], -r["resolved"], str(r["person"]).casefold()))
    out.append(row("Unassigned", "", None, unassigned_open))
    return _frame(out, PERFORMANCE_COLUMNS)


#: report id → builder, for ``reports_service.build_report``.
SUPPORT_REPORTS = {
    "ticket_summary": report_ticket_summary,
    "tickets_by_department": report_tickets_by_department,
    "support_performance": report_support_performance,
}
