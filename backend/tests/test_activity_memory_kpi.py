"""Automatic memory gets a card of its own in the Activity overview.

It is part of total spend, not additional to it — the row is an ordinary
request log. It earns a separate figure because it is the only money here
that the person did not ask to spend, and because it does not move their
budget: without somewhere to see it, "my spend went up and my allowance
didn't" has no explanation on the page.
"""

from __future__ import annotations

import datetime as dt

from app.models.logging import RequestLog
from app.services.activity_service import build_activity_payload
from app.utils.display import MEMORY_USAGE_SOURCE, format_app_source

NOW = dt.datetime(2026, 9, 21, 12, 0, 0)


def _row(*, source: str, cost: float, minutes_ago: int = 30, prompt: int = 1000) -> RequestLog:
    return RequestLog(
        user_id=1,
        username="someone",
        model_id="gpt-x",
        source=source,
        client_app="Memory" if source == MEMORY_USAGE_SOURCE else "Alpharouter Chat",
        prompt_tokens=prompt,
        completion_tokens=50,
        cached_tokens=0,
        total_cost_usd=cost,
        request_time=NOW - dt.timedelta(minutes=minutes_ago),
        success=True,
    )


def _overview(rows, prev_rows=None):
    return build_activity_payload(
        rows,
        period="day",
        since=NOW - dt.timedelta(days=1),
        now=NOW,
        prev_rows=prev_rows or [],
    )["overview"]


def test_the_card_totals_only_the_extraction_rows() -> None:
    overview = _overview(
        [
            _row(source="alpha_router_chat", cost=2.00),
            _row(source=MEMORY_USAGE_SOURCE, cost=0.25),
            _row(source=MEMORY_USAGE_SOURCE, cost=0.15),
        ]
    )
    assert overview["kpis"]["memory_spend"]["value"] == 0.40
    # And it is a slice of total spend, not an addition to it.
    assert overview["kpis"]["spend"]["value"] == 2.40


def test_it_reads_zero_rather_than_missing_when_memory_never_ran() -> None:
    overview = _overview([_row(source="alpha_router_chat", cost=1.00)])
    assert overview["kpis"]["memory_spend"]["value"] == 0.0
    assert overview["kpis"]["memory_spend"]["sparkline"]


def test_it_compares_against_the_previous_period_like_the_others() -> None:
    overview = _overview(
        [_row(source=MEMORY_USAGE_SOURCE, cost=0.30)],
        prev_rows=[_row(source=MEMORY_USAGE_SOURCE, cost=0.15, minutes_ago=2000)],
    )
    assert overview["kpis"]["memory_spend"]["change_pct"] == 100.0


def test_extraction_shows_up_as_its_own_app() -> None:
    """The App column groups on `source`; the label is what makes it readable."""
    assert format_app_source(MEMORY_USAGE_SOURCE) == "Memory"
    payload = build_activity_payload(
        [_row(source=MEMORY_USAGE_SOURCE, cost=0.25), _row(source="alpha_router_chat", cost=1.0)],
        period="day",
        since=NOW - dt.timedelta(days=1),
        now=NOW,
        group_by="app",
    )
    assert "Memory" in {segment["label"] for segment in payload["models"]}
