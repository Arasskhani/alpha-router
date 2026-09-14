"""Regression tests for async rate limiting on chat list/search endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api import user_chats
from app.services import rate_limit


def _user(user_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


async def _call_list(*, q: str | None = None, since: int | None = None) -> None:
    await user_chats.list_user_chats(
        limit=100,
        offset=0,
        q=q,
        since=since,
        min_activity_ms=None,
        max_activity_ms=None,
        user=_user(),
        db=object(),
    )


@pytest.mark.parametrize(
    ("operation", "expected_key"),
    [
        ("search", "chat-search:42"),
        ("since", "chat-list-since:42"),
        ("list", "chat-list:42"),
        ("message-search", "chat-msg-search:42"),
    ],
)
async def test_chat_handlers_await_rate_limiter(operation: str, expected_key: str) -> None:
    calls: list[str] = []

    async def track(key: str, *, limit: int, window_seconds: int = 60) -> None:
        del limit, window_seconds
        calls.append(key)

    async def run() -> None:
        with (
            patch.object(user_chats, "check_rate_limit", track),
            patch.object(user_chats, "list_chat_sessions", AsyncMock(return_value=([], 0, None))),
            patch.object(user_chats, "list_chat_folders", AsyncMock(return_value=[])),
            patch.object(user_chats, "load_user_prefs", AsyncMock(return_value={})),
            patch.object(user_chats, "search_chat_messages", AsyncMock(return_value=[])),
        ):
            if operation == "search":
                await _call_list(q="query")
            elif operation == "since":
                await _call_list(since=1)
            elif operation == "list":
                await _call_list()
            else:
                await user_chats.search_user_chat_messages(
                    q="query",
                    limit=20,
                    user=_user(),
                    db=object(),
                )

    await run()
    assert calls == [expected_key]


async def test_chat_list_enforces_429_with_redis_outage_fallback() -> None:
    key = "chat-list:42"
    with (
        patch.object(rate_limit, "_client", return_value=None),
        patch.object(user_chats, "list_chat_sessions", AsyncMock(return_value=([], 0, None))),
        patch.object(user_chats, "list_chat_folders", AsyncMock(return_value=[])),
        patch.object(user_chats, "load_user_prefs", AsyncMock(return_value={})),
        patch.object(user_chats.get_settings(), "chat_list_rate_limit_per_min", 2),
    ):
        rate_limit._buckets.pop(key, None)
        await _call_list()
        await _call_list()
        with pytest.raises(HTTPException) as exc:
            await _call_list()
        assert exc.value.status_code == 429
        rate_limit._buckets.pop(key, None)
