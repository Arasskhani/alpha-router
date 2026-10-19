"""Web Search in a chat turn: results reach the model, and a failure is said, never hidden."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.services import chat_tools_service as tools
from app.services.web_search_providers import SearchResult
from app.services.web_search_service import SearchFailure, WebSearchOutcome, WebSearchUnavailable


async def test_web_search_results_go_to_the_model_with_their_source():
    outcome = WebSearchOutcome(
        results=[SearchResult(title="Result", url="https://example.com", snippet="Snippet")], label="Brave"
    )
    search = AsyncMock(return_value=outcome)
    with patch.object(tools, "search_web", search):
        context = await tools.web_search_context("query", "medium", user_id=7, username="alice", reserve_budget=False)
    assert "https://example.com" in context and "from Brave" in context
    kwargs = search.await_args.kwargs
    assert (kwargs["user_id"], kwargs["username"], kwargs["reserve_budget"]) == (7, "alice", False)
    assert search.await_args.args == ("query", 5)


async def test_gateway_key_is_propagated_to_web_search():
    search = AsyncMock(return_value=WebSearchOutcome(results=[], label="DuckDuckGo"))
    with patch.object(tools, "search_web", search):
        context = await tools.web_search_context("query", "low", user_id=None, alpha_router_api_key_id=9)
    assert search.await_args.kwargs["alpha_router_api_key_id"] == 9
    assert search.await_args.args == ("query", 3)
    assert "found nothing" in context


async def test_a_failed_search_is_told_to_the_model():
    failure = WebSearchUnavailable(
        [SearchFailure(label="Brave", code="quota", message="Brave's search quota is used up.")]
    )
    with patch.object(tools, "search_web", AsyncMock(side_effect=failure)):
        context = await tools.web_search_context("query", "medium")
    assert "did not work this time" in context
    assert "quota is used up" in context
    assert "Do not claim to have searched" in context
