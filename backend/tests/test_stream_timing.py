"""Tests for stream_chat provider duration measurement."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import proxy_service


class _FakeDeltaChunk:
    def __init__(self, text: str) -> None:
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=text))]


async def _run_stream_timing_test() -> None:
    chunks = [_FakeDeltaChunk("hi"), _FakeDeltaChunk(" there")]

    async def fake_acompletion(**kwargs):
        async def _gen():
            for c in chunks:
                yield c

        return _gen()

    request = MagicMock()
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = AsyncMock(return_value=False)

    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            external_id="test/model",
            display_name="Test Model",
        ),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openrouter",
        model_id="test/model",
    )

    logged: dict = {}

    async def capture_log(*args, **kwargs):
        logged.update(kwargs)

    fake_db = AsyncMock()
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)

    body = {"model": "test/model", "messages": [{"role": "user", "content": "ping"}]}

    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(
            proxy_service,
            "augment_messages_with_tools",
            AsyncMock(side_effect=lambda db, m, t, **_kwargs: m),
        ),
        patch.object(proxy_service, "apply_prompt_cache_breakpoints", side_effect=lambda m: m),
        patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
        patch.object(proxy_service, "_usage_from_chunk", return_value=(10, 2, 0)),
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(0, 0, 0)),
        patch.object(proxy_service, "_serialize_stream_chunk", return_value="{}"),
        patch.object(
            proxy_service,
            "_compute_token_cost_usd",
            side_effect=lambda *a, **k: (time.sleep(0.08), 0.0)[1],
        ),
        patch.object(proxy_service, "log_usage", side_effect=capture_log),
    ):
        gen = proxy_service.stream_chat(
            request,
            body,
            user_id=1,
            username="admin",
            source="alpha_router_chat",
            skip_budget=False,
            resolved=resolved,
        )
        out = [chunk async for chunk in gen]

    assert out
    assert logged.get("response_time_ms") is not None
    assert logged["response_time_ms"] < 50


def test_stream_chat_logs_provider_stream_duration_not_post_processing():
    asyncio.run(_run_stream_timing_test())
