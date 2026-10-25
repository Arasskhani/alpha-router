"""Finding a meeting time from free/busy (app.services.exchange_free_time): pure, no Exchange."""

from __future__ import annotations

import datetime

import pytest

from app.services.exchange_ews_types import Availability, BusyInterval, WorkingHours
from app.services.exchange_free_time import find_free_slots, zone

UTC = datetime.UTC
TEHRAN = zone("Asia/Tehran")
HALF_HOUR = datetime.timedelta(minutes=30)


def at(day: int, hour: int, minute: int = 0, tz=UTC) -> datetime.datetime:
    """A moment in October 2026 (the 26th is a Monday)."""
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=tz)


def person(email: str, *busy: tuple[datetime.datetime, datetime.datetime, str], hours=None, error="") -> Availability:
    return Availability(
        email=email,
        busy=tuple(BusyInterval(start=s, end=e, status=status) for s, e, status in busy),
        working_hours=hours,
        error=error,
    )


def starts(slots) -> list[tuple[int, int, int]]:
    return [(s.start.day, s.start.hour, s.start.minute) for s in slots]


class TestBusyTimes:
    def test_the_first_free_slot_of_a_day_where_both_are_free(self):
        a = person("a@x", (at(26, 9), at(26, 10), "Busy"))
        b = person("b@x", (at(26, 10), at(26, 11), "Busy"))
        slots = find_free_slots([a, b], start=at(26, 0), end=at(27, 0), duration=HALF_HOUR, tz="UTC", max_results=1)
        assert starts(slots) == [(26, 11, 0)]
        assert slots[0].end - slots[0].start == HALF_HOUR

    def test_out_of_office_and_tentative_are_busy_working_elsewhere_and_free_are_not(self):
        a = person(
            "a@x",
            (at(26, 9), at(26, 10), "OOF"),
            (at(26, 10), at(26, 11), "Tentative"),
            (at(26, 11), at(26, 12), "WorkingElsewhere"),
            (at(26, 12), at(26, 13), "Free"),
        )
        slots = find_free_slots([a], start=at(26, 0), end=at(27, 0), duration=HALF_HOUR, tz="UTC", max_results=1)
        assert starts(slots) == [(26, 11, 0)]

    def test_a_slot_that_touches_a_meeting_is_free(self):
        a = person("a@x", (at(26, 9), at(26, 9, 30), "Busy"))
        slots = find_free_slots([a], start=at(26, 9), end=at(26, 10), duration=HALF_HOUR, tz="UTC")
        assert starts(slots) == [(26, 9, 30)]

    def test_an_attendee_whose_free_busy_could_not_be_read_is_left_out(self):
        a = person("a@x")
        hidden = person("hidden@x", error="Free/busy is not visible.")
        slots = find_free_slots([a, hidden], start=at(26, 9), end=at(26, 10), duration=HALF_HOUR, tz="UTC")
        assert starts(slots) == [(26, 9, 0), (26, 9, 30)]

    def test_nobody_free_gives_nothing(self):
        a = person("a@x", (at(26, 0), at(31, 0), "Busy"))
        assert find_free_slots([a], start=at(26, 0), end=at(30, 0), duration=HALF_HOUR, tz="UTC") == []


class TestWorkingHours:
    def test_unknown_hours_are_nine_to_five_on_weekdays_in_the_shown_zone(self):
        slots = find_free_slots(
            [person("a@x")],
            start=at(24, 0),  # Saturday
            end=at(27, 0),
            duration=datetime.timedelta(hours=8),
            tz="UTC",
        )
        assert starts(slots) == [(26, 9, 0)]  # the weekend is skipped; one whole working day fits on Monday

    def test_each_attendee_s_own_hours_in_their_own_zone(self):
        # 08:00-12:00 in Tehran is 04:30-08:30 UTC; the other works 06:00-14:00 UTC.
        tehran = person("t@x", hours=WorkingHours("Asia/Tehran", (1, 2, 3, 4, 5), 8 * 60, 12 * 60))
        london = person("l@x", hours=WorkingHours("UTC", (1, 2, 3, 4, 5), 6 * 60, 14 * 60))
        slots = find_free_slots(
            [tehran, london],
            start=at(26, 0),
            end=at(27, 0),
            duration=datetime.timedelta(hours=2),
            tz="UTC",
            max_results=5,
        )
        assert [(s.start.hour, s.start.minute, s.end.hour, s.end.minute) for s in slots] == [(6, 0, 8, 0)]

    def test_any_time_when_working_hours_are_not_asked_for(self):
        slots = find_free_slots(
            [person("a@x")],
            start=at(24, 0),
            end=at(24, 2),
            duration=HALF_HOUR,
            tz="UTC",
            working_hours_only=False,
        )
        assert starts(slots) == [(24, 0, 0), (24, 0, 30), (24, 1, 0), (24, 1, 30)]

    def test_hours_that_make_no_sense_fall_back_to_the_default(self):
        odd = person("a@x", hours=WorkingHours("Not/AZone", (1,), 9 * 60, 8 * 60))
        slots = find_free_slots([odd], start=at(26, 0), end=at(27, 0), duration=HALF_HOUR, tz="UTC", max_results=1)
        assert starts(slots) == [(26, 9, 0)]


class TestSlots:
    def test_starts_fall_on_quarter_hours_of_the_shown_zone(self):
        # Tehran is UTC+3:30, so its quarter hours are UTC quarter hours too; the start is rounded up.
        slots = find_free_slots(
            [person("a@x")],
            start=at(26, 9, 7, tz=TEHRAN),
            end=at(26, 12, tz=TEHRAN),
            duration=HALF_HOUR,
            tz=TEHRAN,
            max_results=1,
        )
        local = slots[0].start.astimezone(TEHRAN)
        assert (local.hour, local.minute) == (9, 15)
        assert slots[0].start.tzinfo == UTC

    def test_slots_do_not_overlap(self):
        slots = find_free_slots(
            [person("a@x")], start=at(26, 9), end=at(26, 11), duration=datetime.timedelta(minutes=45), tz="UTC"
        )
        assert starts(slots) == [(26, 9, 0), (26, 9, 45)]

    def test_results_are_spread_over_the_days_and_kept_in_time_order(self):
        slots = find_free_slots(
            [person("a@x")], start=at(26, 0), end=at(29, 0), duration=HALF_HOUR, tz="UTC", max_results=4
        )
        assert starts(slots) == [(26, 9, 0), (26, 9, 30), (27, 9, 0), (28, 9, 0)]

    def test_a_meeting_longer_than_the_window_or_an_empty_window_finds_nothing(self):
        assert find_free_slots([person("a@x")], start=at(26, 9), end=at(26, 9, 20), duration=HALF_HOUR, tz="UTC") == []
        assert find_free_slots([person("a@x")], start=at(26, 9), end=at(26, 9), duration=HALF_HOUR, tz="UTC") == []

    def test_naive_times_are_refused(self):
        with pytest.raises(ValueError):
            find_free_slots(
                [person("a@x")],
                start=datetime.datetime(2026, 10, 26, 9),
                end=datetime.datetime(2026, 10, 26, 10),
                duration=HALF_HOUR,
                tz="UTC",
            )

    def test_a_zone_name_that_is_not_one_is_none(self):
        assert zone("Mars/Olympus") is None
        assert zone("") is None
        assert zone("Europe/Berlin") is not None
