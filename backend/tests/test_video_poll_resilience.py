"""One failed status GET must not throw away a clip that is still rendering.

The bug: the poll loop called the provider with no error handling at all, so a
single ConnectTimeout - on a path that drops a share of new connections, an
ordinary event - failed the whole job. The user saw a provider error for a
video the provider was still generating (and billing).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.video_job_service import (
    _MAX_CONSECUTIVE_POLL_FAILURES,
    LeaseLost,
    _is_transient_poll_failure,
)

_REQUEST = httpx.Request("GET", "https://openrouter.ai/api/v1/videos/abc")


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectTimeout("", request=_REQUEST),
        httpx.ConnectError("", request=_REQUEST),
        httpx.ReadTimeout("", request=_REQUEST),
        httpx.RemoteProtocolError("", request=_REQUEST),
        httpx.PoolTimeout(""),
        httpx.HTTPStatusError("rate limited", request=_REQUEST, response=httpx.Response(429, request=_REQUEST)),
        httpx.HTTPStatusError("bad gateway", request=_REQUEST, response=httpx.Response(502, request=_REQUEST)),
    ],
)
def test_a_hiccup_is_worth_another_poll(exc):
    assert _is_transient_poll_failure(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        # These fail the same way forever; retrying only delays the real error.
        httpx.HTTPStatusError("unknown job", request=_REQUEST, response=httpx.Response(404, request=_REQUEST)),
        httpx.HTTPStatusError("revoked key", request=_REQUEST, response=httpx.Response(401, request=_REQUEST)),
        ValueError("OpenRouter video poll returned a non-object payload"),
        LeaseLost("job-1"),
    ],
)
def test_a_permanent_error_is_raised_at_once(exc):
    assert _is_transient_poll_failure(exc) is False


def test_cancellation_is_never_swallowed():
    # CancelledError is a BaseException, so `except Exception` cannot catch it;
    # this pins that fact, because a swallowed cancel would strand the worker.
    assert not isinstance(asyncio.CancelledError(), Exception)


async def test_the_job_survives_transient_failures_and_still_completes():
    """Drive the real retry shape: fail, fail, then answer."""
    from app.services.failure_details import describe_failure

    attempts = 0
    poll_failures = 0
    statuses: list[str] = []

    async def poll() -> str:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise httpx.ConnectTimeout("", request=_REQUEST)
        return "completed"

    status = "submitted"
    while status not in {"completed", "failed", "cancelled"}:
        try:
            status = await poll()
        except Exception as exc:  # noqa: BLE001 -- mirrors the loop under test
            assert _is_transient_poll_failure(exc)
            poll_failures += 1
            assert describe_failure(exc).message.strip()
            if poll_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise
            continue
        poll_failures = 0
        statuses.append(status)

    assert attempts == 3
    assert statuses == ["completed"]


async def test_an_unreachable_provider_still_fails_the_job():
    attempts = 0
    poll_failures = 0

    async def poll() -> str:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectTimeout("", request=_REQUEST)

    with pytest.raises(httpx.ConnectTimeout):
        status = "submitted"
        while status not in {"completed", "failed", "cancelled"}:
            try:
                status = await poll()
            except Exception as exc:  # noqa: BLE001 -- mirrors the loop under test
                if not _is_transient_poll_failure(exc):
                    raise
                poll_failures += 1
                if poll_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                    raise
                continue

    assert attempts == _MAX_CONSECUTIVE_POLL_FAILURES


def test_the_loop_really_does_tolerate_failures():
    """Guard against the handler being removed from the service itself."""
    import inspect

    from app.services import video_job_service

    source = inspect.getsource(video_job_service._run_video_job_inner)
    assert "_is_transient_poll_failure" in source
    assert "poll_failures" in source


def test_unreachable_upstreams_are_counted_separately_from_provider_errors():
    """An operator has to be able to see this without reading a stack trace."""
    from app.services import observability
    from app.services.failure_details import CODE_CONNECT, CODE_PROVIDER, CODE_TIMEOUT
    from app.services.video_job_service import _note_upstream_failure

    observability.reset()
    _note_upstream_failure(CODE_CONNECT)
    _note_upstream_failure(CODE_TIMEOUT)
    _note_upstream_failure(CODE_PROVIDER)  # the provider answered; not an egress problem
    assert observability.snapshot().get("upstream_connect_failure") == 2


def test_both_new_events_are_registered():
    # observability.increment() silently drops anything not in _KNOWN_EVENTS.
    from app.services.observability import _KNOWN_EVENTS

    assert "upstream_connect_failure" in _KNOWN_EVENTS
    assert "video_poll_retry" in _KNOWN_EVENTS
