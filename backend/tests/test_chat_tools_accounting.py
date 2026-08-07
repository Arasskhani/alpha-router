"""Accounting coverage for built-in web tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.services import chat_tools_service as tools


def test_web_search_emits_one_metered_request():
    asyncio.run(_test_web_search_emits_one_metered_request())


async def _test_web_search_emits_one_metered_request() -> None:
    metered_call = object()
    start = AsyncMock(return_value=metered_call)
    finish = AsyncMock()
    rows = [{"title": "Result", "href": "https://example.com", "body": "Snippet"}]
    with (
        patch.object(tools, "start_metered_usage", start),
        patch.object(tools, "finish_metered_usage", finish),
        patch.object(tools, "_run_duckduckgo_search", return_value=rows),
    ):
        context = await tools.web_search_context(
            "query",
            "medium",
            user_id=7,
            username="alice",
            reserve_budget=False,
        )

    assert "https://example.com" in context
    start.assert_awaited_once()
    assert start.await_args.kwargs["provider_type"] == "duckduckgo"
    assert start.await_args.kwargs["service_type"] == "web_search"
    finish.assert_awaited_once_with(
        metered_call,
        success=True,
        quantity=1,
        unit="request",
    )


def test_gateway_key_is_propagated_to_web_search_metering():
    asyncio.run(_test_gateway_key_is_propagated_to_web_search_metering())


async def _test_gateway_key_is_propagated_to_web_search_metering() -> None:
    start = AsyncMock(return_value=object())
    finish = AsyncMock()
    with (
        patch.object(tools, "start_metered_usage", start),
        patch.object(tools, "finish_metered_usage", finish),
        patch.object(tools, "_run_duckduckgo_search", return_value=[]),
    ):
        await tools.web_search_context(
            "query",
            "low",
            user_id=None,
            alpha_router_api_key_id=9,
            username="gateway-key",
        )

    start.assert_awaited_once()
    assert start.await_args.kwargs["user_id"] is None
    assert start.await_args.kwargs["alpha_router_api_key_id"] == 9
