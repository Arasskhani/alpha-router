"""A pooled, retrying HTTP client for short provider control-plane calls.

Video generation is an async job: one POST to create it, then a GET every few
seconds until it finishes — up to a few hundred requests for a single clip.
Each one used to open a brand-new TCP+TLS connection, because the shared image
client disables keep-alive (``max_keepalive_connections=0``) and the video
service additionally sent ``Connection: close``. That policy is right for image
generation, where a request occupies the socket for two or three minutes and a
pooled connection is usually half-closed by the time it is reused. It is
exactly wrong here, where every request is a sub-second control-plane call.

The cost showed up as ``ConnectTimeout``. On a host where a stateful middlebox
drops a fraction of new SYNs — measured at ~37% on a Docker Desktop NAT, and
never zero on any network — opening 240 connections instead of one turns a
survivable per-connection failure rate into a certainty that the job dies:
0.63**240 is not a number anyone ships against. Meanwhile the very same host
served 8/8 requests instantly over a single kept-alive connection.

So this client:

* keeps connections alive, so a job pays for one handshake instead of hundreds;
* retries *establishing* a connection a few times. ``AsyncHTTPTransport``
  passes ``retries`` to httpcore, which retries only the connect attempt and
  never re-sends a request that was already put on the wire — so a video POST
  cannot be submitted twice and billed twice;
* budgets that connect at a few seconds rather than fifteen. A healthy
  handshake to a provider takes tens of milliseconds; a fifteen-second wait
  never recovers a connection, it only delays the failure;
* honours ``HTTPS_PROXY``/``NO_PROXY`` (``trust_env``), so an operator whose
  network cannot be fixed can route around it without a code change. Note the
  limit of that: the SSRF-guarded client in ``ssrf_guard`` -- which downloads
  the finished video and every other user-supplied URL -- deliberately keeps
  ``trust_env`` off, because sending those through a proxy would hand the
  destination back to the proxy and defeat its IP pinning. A proxy fixes the
  control-plane calls, not the asset download.
"""

from __future__ import annotations

import httpx

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_CONNECT_RETRIES = 3
DEFAULT_MAX_CONNECTIONS = 32
DEFAULT_KEEPALIVE_CONNECTIONS = 16
# Long enough to span a poll interval, short enough that a socket a middlebox
# has silently dropped is not still in the pool when the next poll needs it.
DEFAULT_KEEPALIVE_EXPIRY = 30.0

_shared_client: httpx.AsyncClient | None = None


def _setting(name: str, default: float) -> float:
    try:
        from app.config import get_settings

        value = float(getattr(get_settings(), name, 0) or 0)
    except Exception:  # noqa: BLE001 -- configuration must never break an upstream call
        return default
    return value if value > 0 else default


def provider_connect_timeout() -> float:
    """Seconds to wait for a TCP+TLS handshake (PROVIDER_CONNECT_TIMEOUT_SECONDS)."""
    return _setting("provider_connect_timeout_seconds", DEFAULT_CONNECT_TIMEOUT)


def provider_connect_retries() -> int:
    """How many extra connect attempts httpcore may make (PROVIDER_CONNECT_RETRIES).

    Zero is allowed and means "one attempt, as before".
    """
    try:
        from app.config import get_settings

        value = int(getattr(get_settings(), "provider_connect_retries", DEFAULT_CONNECT_RETRIES))
    except Exception:  # noqa: BLE001 -- configuration must never break an upstream call
        return DEFAULT_CONNECT_RETRIES
    return max(0, min(10, value))


def _max_connections() -> int:
    return int(_setting("openrouter_max_connections", DEFAULT_MAX_CONNECTIONS))


def get_provider_rest_client() -> httpx.AsyncClient:
    """The shared keep-alive client for short provider REST calls."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        max_connections = _max_connections()
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=min(DEFAULT_KEEPALIVE_CONNECTIONS, max_connections),
            keepalive_expiry=DEFAULT_KEEPALIVE_EXPIRY,
        )
        _shared_client = httpx.AsyncClient(
            # ``limits`` has to go on the transport: httpx silently ignores the
            # client-level argument whenever a transport is supplied, which
            # would leave the pool on httpcore's defaults instead of ours.
            transport=httpx.AsyncHTTPTransport(retries=provider_connect_retries(), limits=limits),
            timeout=httpx.Timeout(
                _setting("provider_http_timeout_seconds", 60.0),
                connect=provider_connect_timeout(),
            ),
            limits=limits,
            follow_redirects=True,
            http2=False,
            trust_env=True,
        )
    return _shared_client


async def close_provider_rest_client() -> None:
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None
