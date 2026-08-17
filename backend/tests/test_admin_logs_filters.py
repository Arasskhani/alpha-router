"""Tests for admin API logs filters."""

import pytest
from sqlalchemy import select

from app.api.logs import _apply_log_filters
from app.models.logging import RequestLog


def test_apply_log_filters_prompt_cache_yes():
    q = select(RequestLog)
    q = _apply_log_filters(
        q,
        username=None,
        model_id=None,
        response_status=None,
        prompt_cache="yes",
        start_date=None,
        end_date=None,
    )
    sql = str(q.compile(compile_kwargs={"literal_binds": True}))
    assert "cached_tokens" in sql


def test_apply_log_filters_prompt_cache_no():
    q = select(RequestLog)
    q = _apply_log_filters(
        q,
        username=None,
        model_id=None,
        response_status=None,
        prompt_cache="no",
        start_date=None,
        end_date=None,
    )
    sql = str(q.compile(compile_kwargs={"literal_binds": True}))
    assert "cached_tokens" in sql


def test_apply_log_filters_api_key_id():
    q = select(RequestLog)
    q = _apply_log_filters(
        q,
        username=None,
        model_id=None,
        response_status=None,
        prompt_cache=None,
        start_date=None,
        end_date=None,
        api_key_id=7,
    )
    sql = str(q.compile(compile_kwargs={"literal_binds": True}))
    assert "alpha_router_api_key_id" in sql.lower()
    assert "7" in sql


def test_apply_log_filters_username_contains():
    q = select(RequestLog)
    q = _apply_log_filters(
        q,
        username="jdoe",
        model_id=None,
        response_status=None,
        prompt_cache=None,
        start_date=None,
        end_date=None,
    )
    sql = str(q.compile(compile_kwargs={"literal_binds": True}))
    assert "username" in sql.lower()


@pytest.mark.parametrize("prompt_cache", [None, "yes", "no"])
def test_apply_log_filters_accepts_prompt_cache_values(prompt_cache):
    q = _apply_log_filters(
        select(RequestLog),
        username=None,
        model_id=None,
        response_status=None,
        prompt_cache=prompt_cache,
        start_date=None,
        end_date=None,
    )
    assert q is not None
