"""Finding a time when everyone is free, from the free/busy Exchange gives for each person.

Pure: no Exchange, no database. The chat's ``calendar_find_free_time`` tool
asks Exchange for each attendee's busy times and working hours, and this
module picks the slots.

- **Busy.** ``Busy``, ``OOF`` (out of office) and ``Tentative`` block a slot;
  ``WorkingElsewhere`` and ``Free`` do not.
- **Working hours.** With ``working_hours_only`` a slot has to sit inside
  each attendee's own working hours, in their own time zone, when Exchange
  told them; for an attendee whose hours are unknown, 09:00-17:00 Monday to
  Friday in the zone the slots are shown in.
- **Slots.** Starts fall on ``step_minutes`` boundaries of the shown zone;
  slots do not overlap. A free morning would otherwise fill every result, so
  the slots are taken a day at a time (each day's first, then each day's
  second, ...) and given back in time order.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.exchange_ews_types import Availability, BusyInterval, FreeSlot, WorkingHours

#: Free/busy statuses that keep a person from a meeting.
BUSY_STATUSES = frozenset({"busy", "oof", "tentative"})
#: Working hours assumed for someone whose hours Exchange did not give: 09:00-17:00, Monday to Friday.
DEFAULT_WORKING_HOURS = (frozenset({1, 2, 3, 4, 5}), 9 * 60, 17 * 60)

UTC = datetime.UTC


def zone(name: str | ZoneInfo | None) -> ZoneInfo | None:
    """The IANA zone ``name`` names, or ``None`` when it is not one."""
    if isinstance(name, ZoneInfo):
        return name
    text = str(name or "").strip()
    if not text:
        return None
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _minutes(moment: datetime.datetime) -> int:
    return moment.hour * 60 + moment.minute


def _aligned_start(start: datetime.datetime, tz: ZoneInfo, step: int) -> datetime.datetime:
    """The first instant at or after ``start`` that falls on a ``step``-minute boundary of ``tz``."""
    local = start.astimezone(tz)
    base = local.replace(second=0, microsecond=0)
    if base < local:
        base += datetime.timedelta(minutes=1)
    remainder = _minutes(base) % step
    if remainder:
        base += datetime.timedelta(minutes=step - remainder)
    return base.astimezone(UTC)


class _Person:
    """One attendee as the slot finder needs them: busy times in order, and the window they work in."""

    def __init__(self, availability: Availability, default_zone: ZoneInfo) -> None:
        self.busy: list[BusyInterval] = sorted(
            (b for b in availability.busy if (b.status or "Busy").strip().lower() in BUSY_STATUSES),
            key=lambda b: b.start,
        )
        hours = _usable_hours(availability.working_hours)
        if hours is None:
            days, first, last = DEFAULT_WORKING_HOURS
            self.zone, self.days, self.first, self.last = default_zone, days, first, last
        else:
            self.zone, self.days, self.first, self.last = hours

    def free(self, start: datetime.datetime, end: datetime.datetime) -> bool:
        for interval in self.busy:
            if interval.start >= end:
                break
            if interval.end > start:
                return False
        return True

    def working(self, start: datetime.datetime, end: datetime.datetime) -> bool:
        """The slot sits inside one working day of this person, in their zone."""
        local_start = start.astimezone(self.zone)
        local_end = end.astimezone(self.zone)
        last_minute = local_end - datetime.timedelta(microseconds=1)
        if last_minute.date() != local_start.date() or local_start.isoweekday() not in self.days:
            return False
        end_minute = 24 * 60 if local_end.date() != local_start.date() else _minutes(local_end)
        return _minutes(local_start) >= self.first and end_minute <= self.last


def _usable_hours(hours: WorkingHours | None) -> tuple[ZoneInfo, frozenset[int], int, int] | None:
    """Working hours Exchange gave, when they make sense (a known zone, some days, an end after the start)."""
    if hours is None:
        return None
    tz = zone(hours.timezone)
    days = frozenset(d for d in hours.days if 1 <= d <= 7)
    if tz is None or not days or not 0 <= hours.start_minute < hours.end_minute <= 24 * 60:
        return None
    return tz, days, hours.start_minute, hours.end_minute


def find_free_slots(
    availabilities: Sequence[Availability],
    *,
    start: datetime.datetime,
    end: datetime.datetime,
    duration: datetime.timedelta,
    tz: str | ZoneInfo,
    working_hours_only: bool = True,
    step_minutes: int = 15,
    max_results: int = 5,
) -> list[FreeSlot]:
    """Slots of ``duration`` between ``start`` and ``end`` when every attendee is free; at most ``max_results``.

    ``start`` and ``end`` are timezone-aware; the slots come back in UTC.
    Attendees whose free/busy could not be read (``error``) are left out: the
    caller says so. ``tz`` is the zone the slots are shown in: starts fall on
    its quarter hours, and it is the zone of the default working hours.
    """
    shown = zone(tz) or ZoneInfo("UTC")
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if duration <= datetime.timedelta(0) or max_results <= 0 or step_minutes <= 0 or end <= start:
        return []
    people = [_Person(a, shown) for a in availabilities if not a.error]
    step = datetime.timedelta(minutes=step_minutes)
    by_day: dict[datetime.date, list[FreeSlot]] = {}
    candidate = _aligned_start(start, shown, step_minutes)
    while candidate + duration <= end:
        slot_end = candidate + duration
        if all(p.free(candidate, slot_end) for p in people) and (
            not working_hours_only or all(p.working(candidate, slot_end) for p in people)
        ):
            by_day.setdefault(candidate.astimezone(shown).date(), []).append(FreeSlot(start=candidate, end=slot_end))
            # The next slot starts where this one ends (on the next boundary): slots never overlap.
            candidate = _aligned_start(slot_end, shown, step_minutes)
            continue
        candidate += step
    return _spread(by_day, max_results)


def _spread(by_day: dict[datetime.date, list[FreeSlot]], max_results: int) -> list[FreeSlot]:
    """Each day's first slot, then each day's second, ... until ``max_results``; in time order."""
    picked: list[FreeSlot] = []
    rank = 0
    days = sorted(by_day)
    while len(picked) < max_results and any(rank < len(by_day[d]) for d in days):
        for day in days:
            if rank < len(by_day[day]) and len(picked) < max_results:
                picked.append(by_day[day][rank])
        rank += 1
    return sorted(picked, key=lambda slot: slot.start)
