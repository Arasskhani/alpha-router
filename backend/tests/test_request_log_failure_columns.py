"""A failed request must record *why*, not just that it failed.

request_logs gained error_code / http_status / correlation_id /
provider_job_id (revision 6d2e3f4a5b6c). These check the whole path: the
classifier feeds the columns, log_usage writes them, and a background job
stamps its own correlation id so the container log and the row can be joined.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.models.logging import RequestLog
from app.services.failure_details import describe_failure
from app.services.observability import correlation_id, correlation_scope
from app.services.usage_logging_service import log_usage
from app.services.video_billing_service import VideoBillingCapture, log_video_usage


async def test_log_usage_persists_the_failure_detail(db_session, user) -> None:
    failure = describe_failure(
        httpx.ConnectError("", request=httpx.Request("GET", "https://cdn.example.com/v/1.mp4?sig=x"))
    )
    log_id = await log_usage(
        db_session,
        user_id=user.id,
        username=user.username,
        model_id="bytedance/seedance-1-pro",
        prompt_tokens=0,
        completion_tokens=0,
        cached_tokens=0,
        total_cost_usd=0.0,
        response_time_ms=12.0,
        prompt_language="en",
        source_ip=None,
        source="alpha_router_chat",
        success=False,
        error_message=failure.message,
        error_code=failure.code,
        http_status=failure.http_status,
        correlation_id="job-abc",
        provider_job_id="vid_123",
        operation_type="video",
    )
    await db_session.commit()
    row = await db_session.get(RequestLog, log_id)
    assert row is not None
    assert row.success is False
    assert row.error_code == "connect_error"
    assert row.error_message and "cdn.example.com" in row.error_message
    assert "sig=x" not in row.error_message
    assert row.correlation_id == "job-abc"
    assert row.provider_job_id == "vid_123"


async def test_http_status_is_recorded_from_the_upstream_response(db_session, user) -> None:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/videos")
    failure = describe_failure(
        httpx.HTTPStatusError(
            "Client error", request=request, response=httpx.Response(400, request=request, text="bad duration")
        )
    )
    log_id = await log_usage(
        db_session,
        user_id=user.id,
        username=user.username,
        model_id="m",
        prompt_tokens=0,
        completion_tokens=0,
        cached_tokens=0,
        total_cost_usd=0.0,
        response_time_ms=1.0,
        prompt_language="en",
        source_ip=None,
        source="alpha_router_chat",
        success=False,
        error_message=failure.message,
        error_code=failure.code,
        http_status=failure.http_status,
        operation_type="video",
    )
    await db_session.commit()
    row = await db_session.get(RequestLog, log_id)
    assert row.http_status == 400
    assert row.error_code == "http_client_error"
    assert "bad duration" in row.error_message


async def test_correlation_id_defaults_to_the_current_scope(db_session, user) -> None:
    with correlation_scope("corr-42"):
        assert correlation_id() == "corr-42"
        log_id = await log_usage(
            db_session,
            user_id=user.id,
            username=user.username,
            model_id="m",
            prompt_tokens=1,
            completion_tokens=1,
            cached_tokens=0,
            total_cost_usd=0.0,
            response_time_ms=1.0,
            prompt_language="en",
            source_ip=None,
            source="alpha_router_chat",
            success=True,
        )
    await db_session.commit()
    row = await db_session.get(RequestLog, log_id)
    assert row.correlation_id == "corr-42"
    # The scope is restored, so the next request is not tagged with this one.
    assert correlation_id() != "corr-42"


async def test_video_logger_forwards_the_failure_detail() -> None:
    capture = VideoBillingCapture(model_id="bytedance/seedance-1-pro", provider_type="openrouter")
    capture.add_usage(None, success=False, error_message="timeout")
    with patch("app.services.video_billing_service.log_usage", new_callable=AsyncMock) as mocked:
        await log_video_usage(
            AsyncMock(),
            user=SimpleNamespace(id=1, username="tester"),
            capture=capture,
            prompt="a cat",
            response_time_ms=10.0,
            success=False,
            error_message="Upstream timed out (ReadTimeout)",
            error_code="timeout",
            http_status=None,
            provider_job_id="vid_9",
            correlation_id="job-9",
            job_id="job-9",
        )
        kwargs = mocked.await_args.kwargs
    assert kwargs["error_code"] == "timeout"
    assert kwargs["provider_job_id"] == "vid_9"
    assert kwargs["correlation_id"] == "job-9"
