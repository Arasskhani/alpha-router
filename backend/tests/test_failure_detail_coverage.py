"""Every path that records a failure must record a real one.

The failure-detail work landed on chat and video first. Image, speech, the
embedding path and the chat tools kept writing `str(exc)`, which is empty for
every httpx timeout and a bare ConnectError - so the exact bug that made a
video read "Video generation failed" was still live for an image, and the new
Error Code filter in API Logs could never match an image or speech row at all.
"""

from __future__ import annotations

import inspect
import re

import httpx
import pytest

from app.services.failure_details import CODE_TIMEOUT, failure_message

_BLANK = (
    httpx.ConnectTimeout("", request=httpx.Request("POST", "https://openrouter.ai/api/v1/images")),
    httpx.ReadTimeout("", request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat")),
    httpx.PoolTimeout(""),
    httpx.ConnectError("", request=httpx.Request("GET", "https://openrouter.ai/api/v1/models")),
)


@pytest.mark.parametrize("exc", _BLANK)
def test_the_exceptions_this_is_about_really_do_stringify_to_nothing(exc):
    # If httpx ever changes this, the guards below become unnecessary - so pin
    # the premise rather than leaving it as folklore in a commit message.
    assert str(exc) == ""
    assert failure_message(exc).strip()


def _sources() -> dict[str, str]:
    from app.api import images, speech
    from app.services import chat_tools_service, proxy_service

    return {
        "app/api/images.py": inspect.getsource(images),
        "app/api/speech.py": inspect.getsource(speech),
        "app/services/proxy_service.py": inspect.getsource(proxy_service),
        "app/services/chat_tools_service.py": inspect.getsource(chat_tools_service),
    }


def test_no_recorded_failure_is_a_bare_str_of_an_exception():
    """`error_message=str(exc)` is the bug, in every module that logs usage."""
    offenders: list[str] = []
    for name, source in _sources().items():
        for match in re.finditer(r"error_message=str\((exc|e|retry_exc|attempt_exc)\)(?!\s*or)", source):
            offenders.append(f"{name}: {match.group(0)}")
    assert offenders == []


def test_image_and_speech_pass_a_failure_code_to_the_log():
    """Without a code the Error Code filter silently excludes these rows."""
    from app.services.image_billing_service import log_image_usage
    from app.services.speech_billing_service import log_speech_usage

    for fn in (log_image_usage, log_speech_usage):
        params = inspect.signature(fn).parameters
        assert "error_code" in params, fn.__name__
        assert "http_status" in params, fn.__name__
        body = inspect.getsource(fn)
        assert "error_code=error_code" in body, fn.__name__
        assert "http_status=http_status" in body, fn.__name__


def test_an_image_timeout_is_classified_rather_than_swallowed():
    from app.api.images import _classify

    code, status = _classify(_BLANK[0])
    assert code == CODE_TIMEOUT
    assert status is None


def test_an_image_http_error_keeps_the_upstream_status():
    from app.api.images import _classify

    request = httpx.Request("POST", "https://openrouter.ai/api/v1/images")
    response = httpx.Response(429, request=request, text="rate limited")
    code, status = _classify(httpx.HTTPStatusError("429", request=request, response=response))
    assert status == 429
    assert code == "http_client_error"
