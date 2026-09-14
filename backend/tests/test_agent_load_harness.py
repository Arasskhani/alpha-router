"""Smoke checks for the privacy-safe external Agent load gate."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx

_SCRIPT = Path(__file__).parent / "load" / "agent_gateway_load.py"
_SPEC = importlib.util.spec_from_file_location("agent_gateway_load", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
load_gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = load_gate
_SPEC.loader.exec_module(load_gate)


async def _exercise_stream_request() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        status, latency, first_token, cancelled = await load_gate._one_request(
            client,
            url="https://alpharouter.test/v1/chat/completions",
            api_key="test-key",
            model="model::1",
            agent="it-helpdesk",
            prompt="health check",
            cancel_after_first_token=True,
        )
    assert status == 200
    assert latency >= 0
    assert first_token is not None
    assert cancelled
    assert captured["private_mode"] is True
    assert captured["persist_chat"] is False
    assert captured["agent_slug"] == "it-helpdesk"
    assert captured["alpharouter"]["session_id"].startswith("load-")


async def test_load_harness_streams_privately_and_supports_cancellation() -> None:
    await _exercise_stream_request()


def test_load_harness_percentiles_are_deterministic() -> None:
    assert load_gate._percentile([4, 1, 2, 3], 0.5) == 2
    assert load_gate._percentile([4, 1, 2, 3], 0.95) == 4
    assert load_gate._percentile([], 0.95) is None
