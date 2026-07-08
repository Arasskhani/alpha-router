"""Tests for per-user rate limiting buckets."""

import pytest
from fastapi import HTTPException

from app.services import rate_limit


@pytest.fixture(autouse=True)
def _clear_buckets():
    rate_limit._buckets.clear()
    yield
    rate_limit._buckets.clear()


def test_check_rate_limit_allows_under_limit():
    for _ in range(3):
        rate_limit.check_rate_limit("chat-list:1", limit=5)


def test_check_rate_limit_raises_at_limit():
    for _ in range(3):
        rate_limit.check_rate_limit("chat-list:1", limit=3)
    with pytest.raises(HTTPException) as exc:
        rate_limit.check_rate_limit("chat-list:1", limit=3)
    assert exc.value.status_code == 429


def test_separate_buckets_do_not_share_counts():
    for _ in range(5):
        rate_limit.check_rate_limit("chat-list:1", limit=5)
    with pytest.raises(HTTPException):
        rate_limit.check_rate_limit("chat-list:1", limit=5)

    rate_limit.check_rate_limit("chat-list-since:1", limit=5)
