"""Admin › Tickets › Overview: how tickets came in, ended and wait, for a period. Aggregates only, never ticket text.

Periods, buckets, chart labels and the ``local``/``utc`` time zone are
Activity's (``app.services.activity_service``): the same period values, the
same window (the period ending now), the previous period of the same length
right before it, hourly buckets up to two days and daily buckets up to a
month. A year is shown by month (plan § Overview), with Activity's monthly
roll-up keys. "local" is the server's time zone, as on Activity.

Metric rules (shared with the Support reports):

- *opened*: ``created_at`` in the period;
- *resolved*: ``resolved_at`` in the period (auto-closed tickets never are);
- *first reply*: ``created_at`` → ``first_staff_reply_at`` for tickets opened in
  the period that have one; only a staff reply sets it, so the automatic reply
  and internal notes never count;
- *resolution*: ``created_at`` → ``resolved_at`` for tickets resolved in the period;
- *auto-closed*: ``closed_reason = auto`` and ``closed_at`` in the period;
- *unanswered*: active, and no staff reply yet.

The backlog at the end of each bucket is replayed from the thread: ``status``
events, ``reopened`` / ``resolved`` / ``auto_closed`` / ``closed_resolved``
events, and the person's replies (which move a waiting ticket back to open
without an event of their own), with the ticket's closing time as a fallback.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_ticket import SupportTicket, SupportTicketMessage
from app.services import activity_service as activity
from app.services import support_tickets as st

PRIORITY_COLORS = {"low": "#94a3b8", "normal": "#38bdf8", "high": "#f59e0b", "urgent": "#f87171"}
BACKLOG_COLORS = {"open": "#60a5fa", "in_progress": "#a78bfa", "waiting": "#fbbf24"}
ENDED_COLORS = {"staff": "#34d399", "user": "#5eead4", "auto": "#94a3b8"}
CATEGORY_COLORS = ("#fb7185", "#f59e0b", "#38bdf8", "#a78bfa", "#34d399", "#f472b6")

#: The labels the Activity period menu shows (frontend ``periodLabel``).
PERIOD_LABELS = {
    "15m": "Past 15 Minutes",
    "30m": "Past 30 Minutes",
    "1h": "Past 1 Hour",
    "3h": "Past 3 Hours",
    "day": "Past 1 Day",
    "2d": "Past 2 Days",
    "week": "Past 1 Week",
    "month": "Past 1 Month",
    "year": "Past 1 Year",
}
TOP_DEPARTMENTS = 5
_IN_CHUNK = 500
#: Keys a chart row already uses; a category slug never takes one.
_RESERVED_KEYS = frozenset({"label", "bucket"})
#: Events that set the status without saying ``to``.
_EVENT_STATUS = {"reopened": "open", "resolved": "resolved", "auto_closed": "closed", "closed_resolved": "closed"}


def _utcnow() -> datetime.datetime:
    """Naive UTC, like every ticket timestamp (tests replace it)."""
    return datetime.datetime.utcnow()


# --- filters and the window ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OverviewFilters:
    """The filter menu: each applies to every number on the page. Empty means "any"."""

    assignee: str | None = None  # a user id, or "none" for unassigned
    department: str | None = None
    priority: str | None = None
    category: str | None = None
    status: str | None = None

    def conditions(self) -> list[Any]:
        out: list[Any] = []
        if self.assignee == "none":
            out.append(SupportTicket.assignee_id.is_(None))
        elif self.assignee:
            out.append(SupportTicket.assignee_id == int(self.assignee))
        if self.department:
            out.append(SupportTicket.reporter_department == self.department)
        if self.priority:
            out.append(SupportTicket.priority == self.priority)
        if self.category:
            out.append(SupportTicket.category == self.category)
        if self.status:
            out.append(SupportTicket.status == self.status)
        return out

    def summary(self) -> list[tuple[str, str]]:
        """(name, value) for the filters that are set, as the CSV header states them."""
        named = [
            ("Assignee", "Unassigned" if self.assignee == "none" else self.assignee),
            ("Department", self.department),
            ("Priority", st.PRIORITY_LABELS.get(self.priority or "", self.priority)),
            ("Category", self.category),
            ("Status", st.STATUS_LABELS.get(self.status or "", self.status) if self.status else None),
        ]
        return [(name, str(value)) for name, value in named if value]


def bucket_key(dt: datetime.datetime, period: str, tz_mode: str) -> str:
    """Activity's bucket for ``dt``; a year rolls up by month."""
    if period == "year":
        return activity._explore_rollup_key(dt, "monthly", tz_mode)
    return activity._bucket_key(dt, period, tz_mode)


def bucket_keys(period: str, since: datetime.datetime, now: datetime.datetime, tz_mode: str) -> list[str]:
    if period == "year":
        return activity._explore_rollup_labels("monthly", since, now, tz_mode)
    return activity._bucket_labels(period, since, now, tz_mode)


def bucket_label(key: str, period: str, tz_mode: str) -> str:
    if period == "year":
        return activity._explore_chart_label(key, "monthly")
    return activity._chart_label(key, period, tz_mode)


@dataclass
class _Window:
    period: str
    tz_mode: str
    now: datetime.datetime
    since: datetime.datetime
    prev_since: datetime.datetime
    keys: list[str]

    @classmethod
    def for_period(cls, period: str, tz_mode: str, now: datetime.datetime) -> _Window:
        since = activity.activity_period_start(period, now)
        return cls(period, tz_mode, now, since, since - (now - since), bucket_keys(period, since, now, tz_mode))

    def key(self, dt: datetime.datetime) -> str:
        return bucket_key(dt, self.period, self.tz_mode)

    def label(self, key: str) -> str:
        return bucket_label(key, self.period, self.tz_mode)

    def current(self, dt: datetime.datetime | None) -> bool:
        return dt is not None and self.since <= dt <= self.now

    def previous(self, dt: datetime.datetime | None) -> bool:
        return dt is not None and self.prev_since <= dt < self.since


# --- loading -----------------------------------------------------------------------------------------------------

_TICKET_COLUMNS = (
    SupportTicket.id,
    SupportTicket.created_at,
    SupportTicket.status,
    SupportTicket.priority,
    SupportTicket.category,
    SupportTicket.reporter_department,
    SupportTicket.assignee_id,
    SupportTicket.first_staff_reply_at,
    SupportTicket.resolved_at,
    SupportTicket.resolved_by,
    SupportTicket.closed_at,
    SupportTicket.closed_reason,
)


async def _load_tickets(db: AsyncSession, window: _Window, filters: OverviewFilters) -> list[Any]:
    """Every ticket that touches the two periods: active now, or opened, resolved or closed since ``prev_since``.

    A done ticket outside that is done for the whole window: reopening clears
    its resolved/closed times, and ending it again sets new ones.
    """
    since = window.prev_since
    touching = or_(
        SupportTicket.status.in_(st.ACTIVE_STATUSES),
        SupportTicket.created_at >= since,
        SupportTicket.resolved_at >= since,
        SupportTicket.closed_at >= since,
    )
    query = select(*_TICKET_COLUMNS).where(touching, SupportTicket.created_at <= window.now, *filters.conditions())
    return list((await db.execute(query)).all())


async def _load_thread_facts(db: AsyncSession, ticket_ids: Sequence[int]) -> dict[int, list[Any]]:
    """Per ticket, its events and the person's replies (time and facts only, never text), oldest first."""
    out: dict[int, list[Any]] = defaultdict(list)
    for start in range(0, len(ticket_ids), _IN_CHUNK):
        chunk = list(ticket_ids[start : start + _IN_CHUNK])
        rows = await db.execute(
            select(
                SupportTicketMessage.ticket_id,
                SupportTicketMessage.kind,
                SupportTicketMessage.created_at,
                SupportTicketMessage.event_json,
            )
            .where(SupportTicketMessage.ticket_id.in_(chunk), SupportTicketMessage.kind.in_(("event", "user")))
            .order_by(SupportTicketMessage.created_at, SupportTicketMessage.id)
        )
        for row in rows.all():
            out[int(row.ticket_id)].append(row)
    return out


async def _options(db: AsyncSession, settings: st.TicketSettings, staff: list[st.Staff]) -> dict[str, Any]:
    departments = (
        await db.execute(
            select(SupportTicket.reporter_department)
            .where(SupportTicket.reporter_department.is_not(None), SupportTicket.reporter_department != "")
            .distinct()
        )
    ).scalars()
    found = (await db.execute(select(SupportTicket.category).distinct())).scalars()
    # Exact names: after "Bug" is renamed "BUG", tickets still filed as "Bug" are an old category of their own.
    known = set(settings.categories)
    old = sorted({str(c) for c in found if c and str(c) not in known}, key=lambda c: (c.casefold(), c))
    return {
        "departments": sorted({str(d) for d in departments}, key=str.casefold),
        "assignees": [{"id": s.id, "name": s.name} for s in staff],
        "categories": [*settings.categories, *old],
    }


# --- small helpers ----------------------------------------------------------------------------------------------


def _minutes(start: datetime.datetime, end: datetime.datetime) -> float:
    return (end - start).total_seconds() / 60.0


def _median(values: Iterable[float], ndigits: int = 1) -> float | None:
    data = list(values)
    return round(float(statistics.median(data)), ndigits) if data else None


def _change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return activity._pct_change(float(current), float(previous))


def _carry_forward(values: list[float | None]) -> list[float]:
    """A sparkline needs a number per bucket: an empty bucket repeats the last median (the first known one at the start)."""
    known = [v for v in values if v is not None]
    last = known[0] if known else 0.0
    out: list[float] = []
    for value in values:
        if value is not None:
            last = value
        out.append(last)
    return out


def _kpi(value: float | None, previous: float | None, sparkline: list[float]) -> dict[str, Any]:
    return {"value": value, "change_pct": _change(value, previous), "sparkline": sparkline}


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100.0, 1) if whole else None


def is_resolved(t: Any) -> bool:
    """Resolved by staff or by the person; an auto-closed ticket never is."""
    return t.resolved_at is not None and t.closed_reason != "auto"


def first_reply_minutes(t: Any) -> float | None:
    if t.first_staff_reply_at is None:
        return None
    return _minutes(t.created_at, t.first_staff_reply_at)


def resolution_hours(t: Any) -> float | None:
    if not is_resolved(t):
        return None
    return _minutes(t.created_at, t.resolved_at) / 60.0


def category_keys(labels: Iterable[str]) -> dict[str, str]:
    """Chart keys for categories: a slug of the name ("Feature request" → feature_request), unique per chart."""
    used = set(_RESERVED_KEYS)
    out: dict[str, str] = {}
    for label in labels:
        base = re.sub(r"\W+", "_", label.casefold()).strip("_") or "category"
        key, n = base, 2
        while key in used:
            key, n = f"{base}_{n}", n + 1
        used.add(key)
        out[label] = key
    return out


# --- the backlog, replayed ----------------------------------------------------------------------------------------


def _facts(value: Any) -> dict[str, Any]:
    try:
        data = json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _status_after(row: Any, status: str) -> str:
    if row.kind == "user":
        return "open" if status == "waiting" else status
    facts = _facts(row.event_json)
    kind = facts.get("type")
    if kind == "status":
        to = facts.get("to")
        return to if to in st.STATUSES else status
    return _EVENT_STATUS.get(str(kind), status)


def _timeline(t: Any, thread: list[Any], now: datetime.datetime) -> list[tuple[datetime.datetime, str]]:
    """When the ticket took each status, oldest first; it ends in the ticket's status now."""
    status = "open"
    changes = [(t.created_at, status)]
    for row in thread:
        new = _status_after(row, status)
        if new != status:
            changes.append((row.created_at, new))
            status = new
    if status != t.status:
        # Rows written without events (imports, older data): the ticket's own times say when it ended.
        ended = t.resolved_at if t.status == "resolved" else t.closed_at if t.status == "closed" else None
        changes.append((max(ended or now, changes[-1][0]), str(t.status)))
    return changes


def _status_at(changes: list[tuple[datetime.datetime, str]], at: datetime.datetime) -> str | None:
    status = None
    for when, value in changes:
        if when > at:
            break
        status = value
    return status


def _reopened_in(window: _Window, thread: list[Any]) -> bool:
    for row in thread:
        if row.kind != "event" or not window.current(row.created_at):
            continue
        facts = _facts(row.event_json)
        if facts.get("type") == "reopened":
            return True
        if (
            facts.get("type") == "status"
            and facts.get("from") in st.DONE_STATUSES
            and facts.get("to") in st.ACTIVE_STATUSES
        ):
            return True
    return False


def _backlog_rows(window: _Window, tickets: list[Any], timelines: dict[int, list]) -> list[dict[str, int]]:
    """Active tickets by status at the end of each bucket; the last bucket ends now, so it is today's status."""
    rows = [dict.fromkeys(st.ACTIVE_STATUSES, 0) for _ in window.keys]
    last = len(window.keys) - 1
    for t in tickets:
        keyed = [(window.key(when), status) for when, status in timelines[int(t.id)]]
        j, state = 0, None
        for i, key in enumerate(window.keys):
            while j < len(keyed) and keyed[j][0] <= key:
                state = keyed[j][1]
                j += 1
            current = str(t.status) if i == last else state
            if current in st.ACTIVE_STATUSES:
                rows[i][current] += 1
    return rows


# --- the blocks -------------------------------------------------------------------------------------------------


@dataclass
class _Data:
    window: _Window
    tickets: list[Any]
    threads: dict[int, list[Any]]
    timelines: dict[int, list[tuple[datetime.datetime, str]]]
    settings: st.TicketSettings
    staff: list[st.Staff]

    @property
    def active(self) -> list[Any]:
        return [t for t in self.tickets if t.status in st.ACTIVE_STATUSES]

    def opened(self, previous: bool = False) -> list[Any]:
        test = self.window.previous if previous else self.window.current
        return [t for t in self.tickets if test(t.created_at)]

    def resolved(self, previous: bool = False) -> list[Any]:
        test = self.window.previous if previous else self.window.current
        return [t for t in self.tickets if is_resolved(t) and test(t.resolved_at)]

    def auto_closed(self, previous: bool = False) -> list[Any]:
        test = self.window.previous if previous else self.window.current
        return [t for t in self.tickets if t.closed_reason == "auto" and test(t.closed_at)]

    def per_bucket(self, rows: Iterable[Any], when: str) -> dict[str, list[Any]]:
        out: dict[str, list[Any]] = defaultdict(list)
        for t in rows:
            out[self.window.key(getattr(t, when))].append(t)
        return out


def _kpis(data: _Data, backlog: list[dict[str, int]]) -> dict[str, Any]:
    w = data.window
    opened, prev_opened = data.opened(), data.opened(previous=True)
    resolved, prev_resolved = data.resolved(), data.resolved(previous=True)
    auto, prev_auto = data.auto_closed(), data.auto_closed(previous=True)
    by_created = data.per_bucket(opened, "created_at")
    by_resolved = data.per_bucket(resolved, "resolved_at")
    by_auto = data.per_bucket(auto, "closed_at")

    def replies(rows: Iterable[Any]) -> list[float]:
        return [m for m in (first_reply_minutes(t) for t in rows) if m is not None]

    def resolutions(rows: Iterable[Any]) -> list[float]:
        return [h for h in (resolution_hours(t) for t in rows) if h is not None]

    open_now = len(data.active)
    open_before = sum(1 for t in data.tickets if _status_at(data.timelines[int(t.id)], w.since) in st.ACTIVE_STATUSES)
    closed_in_period = sum(1 for t in data.tickets if w.current(t.closed_at))
    unanswered = sum(1 for t in data.active if t.first_staff_reply_at is None)
    return {
        "opened": _kpi(len(opened), len(prev_opened), [len(by_created.get(k, [])) for k in w.keys]),
        "resolved": _kpi(len(resolved), len(prev_resolved), [len(by_resolved.get(k, [])) for k in w.keys]),
        "open_now": {
            **_kpi(open_now, open_before, [sum(row.values()) for row in backlog]),
            "unanswered": unanswered,
        },
        "first_reply_minutes": _kpi(
            _median(replies(opened)),
            _median(replies(prev_opened)),
            _carry_forward([_median(replies(by_created.get(k, []))) for k in w.keys]),
        ),
        "resolution_hours": _kpi(
            _median(resolutions(resolved)),
            _median(resolutions(prev_resolved)),
            _carry_forward([_median(resolutions(by_resolved.get(k, []))) for k in w.keys]),
        ),
        "auto_closed": {
            **_kpi(len(auto), len(prev_auto), [len(by_auto.get(k, [])) for k in w.keys]),
            "share_pct": _pct(len(auto), closed_in_period),
        },
    }


def _top_departments(data: _Data) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for t in data.opened():
        if not t.reporter_department:
            continue
        row = stats.setdefault(
            t.reporter_department, {"department": t.reporter_department, "opened": 0, "still_open": 0, "urgent_open": 0}
        )
        row["opened"] += 1
        if t.status in st.ACTIVE_STATUSES:
            row["still_open"] += 1
            if t.priority == "urgent":
                row["urgent_open"] += 1
    ranked = sorted(stats.values(), key=lambda r: (-r["opened"], -r["still_open"], r["department"].casefold()))
    return ranked[:TOP_DEPARTMENTS]


def _workload(data: _Data) -> list[dict[str, Any]]:
    open_by: dict[int | None, int] = defaultdict(int)
    resolved_by: dict[int | None, int] = defaultdict(int)
    for t in data.active:
        open_by[t.assignee_id] += 1
    for t in data.resolved():
        resolved_by[t.assignee_id] += 1
    rows: list[dict[str, Any]] = [
        {
            "user_id": s.id,
            "name": s.name,
            "role_label": s.role_label,
            "open": open_by[s.id],
            "resolved": resolved_by[s.id],
        }
        for s in data.staff
    ]
    rows.sort(key=lambda r: (-r["open"], -r["resolved"], str(r["name"]).casefold()))
    waiting = [t.created_at for t in data.active if t.assignee_id is None]
    oldest = round(_minutes(min(waiting), data.window.now)) if waiting else None
    rows.append(
        {
            "user_id": None,
            "name": "Unassigned",
            "role_label": "",
            "open": open_by[None],
            "resolved": resolved_by[None],
            "oldest_wait_minutes": oldest,
        }
    )
    return rows


def _first_reply_by_priority(data: _Data) -> list[dict[str, Any]]:
    minutes: dict[str, list[float]] = defaultdict(list)
    for t in data.opened():
        value = first_reply_minutes(t)
        if value is not None:
            minutes[str(t.priority)].append(value)
    return [
        {"priority": p, "tickets": len(minutes[p]), "median_minutes": _median(minutes[p])}
        for p in reversed(st.PRIORITIES)
        if minutes[p]
    ]


def _opened_by_priority(data: _Data) -> dict[str, Any]:
    opened = data.opened()
    by_bucket = data.per_bucket(opened, "created_at")
    totals = {p: sum(1 for t in opened if t.priority == p) for p in st.PRIORITIES}
    chart = []
    for key in data.window.keys:
        row: dict[str, Any] = {"bucket": key, "label": data.window.label(key)}
        row.update({p: sum(1 for t in by_bucket.get(key, []) if t.priority == p) for p in st.PRIORITIES})
        chart.append(row)
    segments = [
        {"key": p, "label": st.PRIORITY_LABELS[p], "color": PRIORITY_COLORS[p], "value": totals[p]}
        for p in st.PRIORITIES
    ]
    return {"segments": segments, "chart": chart}


def _ended(data: _Data) -> dict[str, Any]:
    def how(t: Any) -> str:
        return "user" if t.resolved_by == "user" else "staff"

    resolved, auto = data.resolved(), data.auto_closed()
    by_resolved = data.per_bucket(resolved, "resolved_at")
    by_auto = data.per_bucket(auto, "closed_at")
    totals = {
        "staff": sum(1 for t in resolved if how(t) == "staff"),
        "user": sum(1 for t in resolved if how(t) == "user"),
        "auto": len(auto),
    }
    labels = {
        "staff": "Resolved by support",
        "user": "Resolved by the user",
        "auto": f"Auto-closed (no reply in {_days(data.settings.auto_close_days)})",
    }
    chart = []
    for key in data.window.keys:
        bucket = by_resolved.get(key, [])
        chart.append(
            {
                "bucket": key,
                "label": data.window.label(key),
                "staff": sum(1 for t in bucket if how(t) == "staff"),
                "user": sum(1 for t in bucket if how(t) == "user"),
                "auto": len(by_auto.get(key, [])),
            }
        )
    total = sum(totals.values())
    reopened = sum(1 for t in data.tickets if _reopened_in(data.window, data.threads.get(int(t.id), [])))
    return {
        "total": total,
        "segments": [
            {"key": k, "label": labels[k], "color": ENDED_COLORS[k], "value": totals[k]}
            for k in ("staff", "user", "auto")
        ],
        "chart": chart,
        "reopened": reopened,
        "reopened_pct": _pct(reopened, total),
    }


def _backlog(data: _Data, rows: list[dict[str, int]]) -> dict[str, Any]:
    active = data.active
    now_counts = {s: sum(1 for t in active if t.status == s) for s in st.ACTIVE_STATUSES}
    unanswered = [t.created_at for t in active if t.first_staff_reply_at is None]
    return {
        "total": len(active),
        "segments": [
            {"key": s, "label": st.STATUS_LABELS[s], "color": BACKLOG_COLORS[s], "value": now_counts[s]}
            for s in st.ACTIVE_STATUSES
        ],
        "chart": [
            {"bucket": key, "label": data.window.label(key), **row}
            for key, row in zip(data.window.keys, rows, strict=True)
        ],
        "oldest_unanswered_minutes": round(_minutes(min(unanswered), data.window.now)) if unanswered else None,
    }


def _by_category(data: _Data) -> dict[str, Any]:
    opened = data.opened()
    counts: dict[str, int] = defaultdict(int)
    for t in opened:
        counts[str(t.category)] += 1
    labels = list(data.settings.categories)
    # Exact names, as tickets store them: an old "Bug" next to a renamed "BUG" is its own segment.
    known = set(labels)
    old = sorted((c for c in counts if c not in known), key=lambda c: (-counts[c], c.casefold(), c))
    labels += old
    keys = category_keys(labels)
    segments: list[dict[str, Any]] = [
        {"key": keys[c], "label": c, "color": CATEGORY_COLORS[i % len(CATEGORY_COLORS)], "value": counts.get(c, 0)}
        for i, c in enumerate(labels)
    ]
    by_bucket = data.per_bucket(opened, "created_at")
    chart = []
    for key in data.window.keys:
        row: dict[str, Any] = {"bucket": key, "label": data.window.label(key)}
        row.update(dict.fromkeys(keys.values(), 0))
        for t in by_bucket.get(key, []):
            row[keys[str(t.category)]] += 1
        chart.append(row)
    total = len(opened)
    best = max(segments, key=lambda s: s["value"], default=None)
    most_common = (
        {"label": best["label"], "pct": _pct(best["value"], total)} if best is not None and best["value"] else None
    )
    return {"total": total, "segments": segments, "chart": chart, "most_common": most_common}


async def build_overview(
    db: AsyncSession,
    *,
    period: str = "week",
    timezone: str = "local",
    filters: OverviewFilters | None = None,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """The Overview tab, in the shape ``frontend/src/lib/tickets.ts`` ``TicketsOverview`` reads."""
    period = period if period in PERIOD_LABELS else "week"
    tz_mode = timezone if timezone in ("local", "utc") else "local"
    filters = filters or OverviewFilters()
    window = _Window.for_period(period, tz_mode, now or _utcnow())
    settings = await st.load_settings(db)
    staff = await st.assignable_staff(db)
    tickets = await _load_tickets(db, window, filters)
    threads = await _load_thread_facts(db, [int(t.id) for t in tickets])
    timelines = {int(t.id): _timeline(t, threads.get(int(t.id), []), window.now) for t in tickets}
    data = _Data(window, tickets, threads, timelines, settings, staff)
    backlog = _backlog_rows(window, tickets, timelines)
    return {
        "period": period,
        "period_label": PERIOD_LABELS[period],
        "timezone": tz_mode,
        "kpis": _kpis(data, backlog),
        "top_departments": _top_departments(data),
        "workload": _workload(data),
        "first_reply_by_priority": _first_reply_by_priority(data),
        "opened_by_priority": _opened_by_priority(data),
        "ended": _ended(data),
        "backlog": _backlog(data, backlog),
        "by_category": _by_category(data),
        "options": await _options(db, settings, staff),
    }


# --- CSV --------------------------------------------------------------------------------------------------------

CSV_COLUMNS = ("Section", "Item", "Measure", "Value")
_KPI_TITLES = (
    ("opened", "Tickets opened"),
    ("resolved", "Resolved"),
    ("open_now", "Open now"),
    ("first_reply_minutes", "Median first reply (minutes)"),
    ("resolution_hours", "Median resolution (hours)"),
    ("auto_closed", "Auto-closed"),
)


def _cell(value: Any) -> Any:
    """Numbers as they are; text a spreadsheet would run as a formula is written as text."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, int | float):
        text = str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
    return value


def _segment_rows(section: str, block: dict[str, Any], measure: str = "Tickets") -> list[list[Any]]:
    rows = [[section, s["label"], measure, s.get("value", 0)] for s in block["segments"]]
    for point in block["chart"]:
        for s in block["segments"]:
            rows.append([section, point["label"], s["label"], point.get(s["key"], 0)])
    return rows


def overview_csv_rows(payload: dict[str, Any], filters: OverviewFilters) -> list[list[Any]]:
    """The page's numbers as (section, item, measure, value) rows."""
    rows: list[list[Any]] = [
        ["Period", payload["period_label"], "", ""],
        ["Time zone", "UTC" if payload["timezone"] == "utc" else "Local time", "", ""],
    ]
    rows += [["Filter", name, "", value] for name, value in filters.summary()]
    kpis = payload["kpis"]
    for key, title in _KPI_TITLES:
        rows.append(["KPIs", title, "Value", kpis[key]["value"]])
        rows.append(["KPIs", title, "Change vs previous period (%)", kpis[key]["change_pct"]])
    rows.append(["KPIs", "Open now", "Waiting for a first answer", kpis["open_now"]["unanswered"]])
    rows.append(["KPIs", "Auto-closed", "Share of closed tickets (%)", kpis["auto_closed"]["share_pct"]])
    for d in payload["top_departments"]:
        rows += [
            ["Top departments", d["department"], "Opened", d["opened"]],
            ["Top departments", d["department"], "Still open", d["still_open"]],
            ["Top departments", d["department"], "Urgent open", d["urgent_open"]],
        ]
    for w in payload["workload"]:
        rows += [["Workload", w["name"], "Open", w["open"]], ["Workload", w["name"], "Resolved", w["resolved"]]]
        if w["user_id"] is None:
            rows.append(["Workload", w["name"], "Oldest wait (minutes)", w.get("oldest_wait_minutes")])
    for p in payload["first_reply_by_priority"]:
        label = st.PRIORITY_LABELS.get(p["priority"], p["priority"])
        rows += [
            ["First reply by priority", label, "Tickets", p["tickets"]],
            ["First reply by priority", label, "Median minutes", p["median_minutes"]],
        ]
    rows += _segment_rows("Opened by priority", payload["opened_by_priority"])
    ended = payload["ended"]
    rows += _segment_rows("How tickets ended", ended)
    rows += [
        ["How tickets ended", "Total", "Tickets", ended["total"]],
        ["How tickets ended", "Reopened after resolve", "Tickets", ended["reopened"]],
        ["How tickets ended", "Reopened after resolve", "Share (%)", ended["reopened_pct"]],
    ]
    backlog = payload["backlog"]
    rows += _segment_rows("Backlog by status", backlog)
    rows += [
        ["Backlog by status", "Open now", "Tickets", backlog["total"]],
        ["Backlog by status", "Oldest without a staff reply", "Minutes", backlog["oldest_unanswered_minutes"]],
    ]
    by_category = payload["by_category"]
    rows += _segment_rows("Tickets by category", by_category)
    if by_category["most_common"]:
        rows.append(
            [
                "Tickets by category",
                "Most common",
                by_category["most_common"]["label"],
                by_category["most_common"]["pct"],
            ]
        )
    return rows


def overview_csv(payload: dict[str, Any], filters: OverviewFilters) -> str:
    buffer = io.StringIO()
    buffer.write("﻿")  # Excel reads the file as UTF-8 (department and category names in Persian)
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in overview_csv_rows(payload, filters):
        writer.writerow([_cell(v) for v in row])
    return buffer.getvalue()
