"""A settlement that gives up after retries leaves a hold behind and says so.

The ``budget_hold_leak`` counter existed since the first review but nothing
ever incremented it; ops had no signal that money was stuck in ``held`` rows.
"""

from __future__ import annotations

import asyncio
import datetime
from unittest.mock import patch

from app.services import metered_usage_service as mus


class _Boom:
    async def __aenter__(self):
        raise RuntimeError("db down")

    async def __aexit__(self, *a):
        return False


def test_metered_settlement_failure_counts_a_hold_leak():
    call = mus.MeteredUsageCall(
        id="m1", user_id=1, alpha_router_api_key_id=None, connection_id=None, username="u",
        provider_type="duckduckgo", service_type="web_search", operation_name="web_search",
        model_id="duckduckgo-search", budget_reservation_id="r1",
        started_at=datetime.datetime.utcnow(),
    )

    async def run():
        with (
            patch.object(mus, "AsyncSessionLocal", _Boom),
            patch.object(mus.asyncio, "sleep", side_effect=lambda *_a, **_k: asyncio.sleep(0)),
            patch.object(mus, "increment") as inc,
        ):
            await mus.finish_metered_usage(call, success=True, quantity=1, unit="request")
        return inc

    inc = asyncio.run(run())
    inc.assert_any_call("budget_hold_leak")


def test_metric_name_is_registered():
    from app.services.observability import _KNOWN_EVENTS

    assert "budget_hold_leak" in _KNOWN_EVENTS
