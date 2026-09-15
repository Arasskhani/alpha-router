"""One description of a failed upstream call: a stable code and a real message.

Every call site used to store ``str(exc)`` verbatim. That is empty for a whole
family of failures — every httpx timeout, a bare ``ConnectError``, an
``asyncio.TimeoutError`` — so the failure was recorded with no reason at all:
an empty ``error_message`` on the job row, on the RequestLog, in the ledger,
and a user staring at "Error: Video generation failed" with nothing to go on.

The exception class name is never empty, and for an HTTP failure the status and
the host it was talking to say more than the text does. ``describe_failure``
builds that, plus a short code the UI can filter on.

Query strings are dropped from any URL we quote: video assets and object
storage arrive as signed links, and a log is the last place their signature
should end up.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

#: Longest message we store. The DB columns are Text, but a provider that
#: echoes the whole prompt back in an error should not fill the table.
MAX_MESSAGE_CHARS = 2000
#: How much of an error response body is worth keeping.
MAX_BODY_CHARS = 500

CODE_CANCELLED = "cancelled"
CODE_TIMEOUT = "timeout"
CODE_CONNECT = "connect_error"
CODE_NETWORK = "network_error"
CODE_HTTP_CLIENT = "http_client_error"
CODE_HTTP_SERVER = "http_server_error"
CODE_INVALID_RESPONSE = "invalid_response"
CODE_PROVIDER = "provider_error"


@dataclass(frozen=True, slots=True)
class FailureDetail:
    """What to store about one failure."""

    code: str
    message: str
    http_status: int | None = None


def _safe_url(url: object) -> str:
    """Scheme, host and path only — never the query (signed URLs live there)."""
    try:
        parts = urlsplit(str(url))
    except Exception:  # noqa: BLE001 -- an unparseable URL just means less context
        return ""
    if not parts.hostname:
        return ""
    return f"{parts.scheme}://{parts.hostname}{parts.path}" if parts.scheme else parts.hostname


def _request_context(exc: BaseException) -> str:
    try:
        # httpx exposes .request as a property that *raises* when the exception
        # was built without one, so this has to be guarded: a function that
        # describes failures must never become one.
        request = getattr(exc, "request", None)
    except Exception:  # noqa: BLE001 -- no request context is simply less detail
        return ""
    if request is None:
        return ""
    url = _safe_url(getattr(request, "url", ""))
    method = str(getattr(request, "method", "") or "").upper()
    if url and method:
        return f"{method} {url}"
    return url or ""


def _with_context(text: str, context: str) -> str:
    if context and context not in text:
        return f"{text} ({context})" if text else context
    return text


def describe_failure(exc: BaseException, *, fallback: str = "") -> FailureDetail:
    """Classify one exception and produce a message that is never empty."""
    raw = str(exc).strip()
    context = _request_context(exc)

    if isinstance(exc, asyncio.CancelledError):
        return FailureDetail(CODE_CANCELLED, raw or fallback or "Cancelled")

    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status = int(getattr(response, "status_code", 0) or 0) or None
        body = ""
        try:
            body = (response.text or "").strip()[:MAX_BODY_CHARS]
        except Exception:  # noqa: BLE001 -- a streamed body may not be readable here
            body = ""
        parts = [p for p in (f"HTTP {status}" if status else "", context, body) if p]
        message = raw if raw and not raw.startswith("Client error") and not raw.startswith("Server error") else ""
        message = " — ".join([p for p in (message, *parts) if p]) or "Upstream HTTP error"
        code = CODE_HTTP_SERVER if status and status >= 500 else CODE_HTTP_CLIENT
        return FailureDetail(code, message[:MAX_MESSAGE_CHARS], status)

    if isinstance(exc, httpx.TimeoutException | asyncio.TimeoutError | TimeoutError):
        text = _with_context(raw or f"Upstream timed out ({type(exc).__name__})", context)
        return FailureDetail(CODE_TIMEOUT, text[:MAX_MESSAGE_CHARS])

    if isinstance(exc, httpx.ConnectError):
        text = _with_context(raw or "Could not connect to the upstream host", context)
        return FailureDetail(CODE_CONNECT, text[:MAX_MESSAGE_CHARS])

    if isinstance(exc, httpx.TransportError):
        text = _with_context(raw or f"Upstream transport error ({type(exc).__name__})", context)
        return FailureDetail(CODE_NETWORK, text[:MAX_MESSAGE_CHARS])

    if isinstance(exc, (ValueError, TypeError, KeyError)):
        text = raw or f"Unusable upstream response ({type(exc).__name__})"
        return FailureDetail(CODE_INVALID_RESPONSE, text[:MAX_MESSAGE_CHARS])

    status = None
    detail = getattr(exc, "detail", None)
    if detail is not None and not raw:
        raw = str(detail).strip()
    if getattr(exc, "status_code", None):
        try:
            status = int(exc.status_code)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            status = None
    text = raw or fallback or f"Upstream call failed ({type(exc).__name__})"
    code = CODE_PROVIDER
    if status is not None:
        code = CODE_HTTP_SERVER if status >= 500 else CODE_HTTP_CLIENT
    return FailureDetail(code, _with_context(text, context)[:MAX_MESSAGE_CHARS], status)


def failure_message(exc: BaseException, *, fallback: str = "") -> str:
    """Just the message — for call sites that have nowhere to put a code yet."""
    return describe_failure(exc, fallback=fallback).message
