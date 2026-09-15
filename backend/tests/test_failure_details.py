"""A recorded failure must never be a blank string.

The bug these cover: `str(exc)` is empty for every httpx timeout and for a bare
ConnectError, so a video job (or a chat turn) was stored with status=failed and
an empty error_message — which the UI renders as "Video generation failed",
telling nobody anything.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.failure_details import (
    CODE_CANCELLED,
    CODE_CONNECT,
    CODE_HTTP_CLIENT,
    CODE_HTTP_SERVER,
    CODE_INVALID_RESPONSE,
    CODE_NETWORK,
    CODE_PROVIDER,
    CODE_TIMEOUT,
    MAX_MESSAGE_CHARS,
    describe_failure,
)

_REQUEST = httpx.Request("GET", "https://cdn.example.com/videos/abc.mp4?signature=SECRET&x=1")


@pytest.mark.parametrize(
    "exc,expected_code",
    [
        (httpx.ReadTimeout("", request=_REQUEST), CODE_TIMEOUT),
        (httpx.ConnectTimeout("", request=_REQUEST), CODE_TIMEOUT),
        (httpx.PoolTimeout(""), CODE_TIMEOUT),
        (TimeoutError(), CODE_TIMEOUT),  # asyncio.TimeoutError is this since 3.11
        (httpx.ConnectError("", request=_REQUEST), CODE_CONNECT),
        (httpx.RemoteProtocolError("", request=_REQUEST), CODE_NETWORK),
        (ValueError(""), CODE_INVALID_RESPONSE),
        (RuntimeError(""), CODE_PROVIDER),
    ],
)
def test_every_empty_exception_still_gets_a_message(exc, expected_code):
    detail = describe_failure(exc)
    assert detail.code == expected_code
    # Not just non-empty: it has to say something a person can act on.
    assert len(detail.message.strip()) > 10, f"{type(exc).__name__} produced {detail.message!r}"


def test_the_exception_class_is_named_when_there_is_nothing_better():
    detail = describe_failure(httpx.ReadTimeout("", request=_REQUEST))
    assert "ReadTimeout" in detail.message
    assert describe_failure(RuntimeError("")).message.endswith("(RuntimeError)")


def test_the_signed_part_of_a_url_is_not_logged():
    detail = describe_failure(httpx.ConnectError("", request=_REQUEST))
    assert "cdn.example.com/videos/abc.mp4" in detail.message
    assert "SECRET" not in detail.message
    assert "signature" not in detail.message


def test_http_status_error_keeps_status_and_body():
    response = httpx.Response(429, request=_REQUEST, text='{"error":{"message":"rate limited"}}')
    detail = describe_failure(httpx.HTTPStatusError("Client error '429'", request=_REQUEST, response=response))
    assert detail.code == CODE_HTTP_CLIENT
    assert detail.http_status == 429
    assert "rate limited" in detail.message
    assert "HTTP 429" in detail.message


def test_server_errors_are_classified_apart_from_client_errors():
    response = httpx.Response(503, request=_REQUEST, text="upstream unavailable")
    detail = describe_failure(httpx.HTTPStatusError("Server error", request=_REQUEST, response=response))
    assert detail.code == CODE_HTTP_SERVER
    assert detail.http_status == 503


def test_a_real_message_is_kept_as_is():
    detail = describe_failure(RuntimeError("Video job is missing a duration"))
    assert detail.message == "Video job is missing a duration"
    assert detail.code == CODE_PROVIDER


def test_cancellation_is_not_a_provider_failure():
    assert describe_failure(asyncio.CancelledError()).code == CODE_CANCELLED


def test_message_is_capped():
    detail = describe_failure(RuntimeError("x" * (MAX_MESSAGE_CHARS * 2)))
    assert len(detail.message) <= MAX_MESSAGE_CHARS


def test_http_exception_detail_is_used_when_str_is_empty():
    from fastapi import HTTPException

    detail = describe_failure(HTTPException(status_code=402, detail="Budget exceeded"))
    assert "Budget exceeded" in detail.message
    assert detail.http_status == 402
    assert detail.code == CODE_HTTP_CLIENT


def test_chat_error_frame_is_never_blank():
    """A timeout used to produce an SSE error frame with an empty message."""
    from app.services.provider_utils import format_provider_error

    timeout = httpx.ReadTimeout("", request=_REQUEST)
    assert format_provider_error(timeout, "openrouter").strip()
    assert format_provider_error(timeout, "openai").strip()


def test_video_provider_failure_without_text_says_what_the_provider_reported():
    from types import SimpleNamespace

    from app.services.video_job_service import _provider_failure_text

    snapshot = SimpleNamespace(
        error_message=None,
        provider_status="failed",
        raw={"id": "vid_1", "status": "failed"},
    )
    text = _provider_failure_text(snapshot, "failed")
    assert "failed" in text
    assert "vid_1" in text
    assert text.strip()

    with_text = SimpleNamespace(error_message="content policy", provider_status="failed", raw={})
    assert _provider_failure_text(with_text, "failed") == "content policy"


def test_video_adapter_reads_a_structured_provider_error():
    from app.services.video_providers.openrouter import _error_text

    assert _error_text({"status": "failed", "error": "moderation blocked"}) == "moderation blocked"
    assert _error_text({"error": {"message": "invalid duration", "code": 400}}) == "invalid duration"
    assert _error_text({"error": {"code": "E42"}}) == "E42"
    assert _error_text({"status": "completed"}) is None
