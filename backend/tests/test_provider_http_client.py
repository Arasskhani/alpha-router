"""The provider REST client must reuse connections and retry the handshake.

The bug these lock down: every video poll opened a brand-new TCP+TLS
connection (``Connection: close`` plus a pool with keep-alive disabled), so a
single clip paid for a few hundred handshakes and one dropped SYN anywhere in
that sequence killed the job. On a path that loses a third of new connections
the job could not finish at all, while the same host answered every request
instantly over one kept-alive socket.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import provider_http
from app.services.provider_http import (
    close_provider_rest_client,
    get_provider_rest_client,
    provider_connect_retries,
    provider_connect_timeout,
)


@pytest.fixture(autouse=True)
async def _fresh_client():
    await close_provider_rest_client()
    yield
    await close_provider_rest_client()


async def test_connections_are_kept_alive():
    # Read the live connection pool, not the arguments we passed: httpx drops
    # the client-level ``limits`` when a transport is supplied, so asserting on
    # our own inputs would have passed while the pool ran on stock defaults.
    pool = get_provider_rest_client()._transport._pool
    assert pool._max_keepalive_connections > 0, "a pooled client that keeps nothing alive is the bug"
    assert pool._keepalive_expiry == provider_http.DEFAULT_KEEPALIVE_EXPIRY
    assert pool._max_connections == provider_http._max_connections()


async def test_the_connect_budget_is_seconds_not_a_quarter_minute():
    # A healthy handshake takes tens of milliseconds; waiting 15s never
    # recovers a connection, it only postpones the error the user sees.
    assert 1.0 <= provider_connect_timeout() <= 10.0


async def test_establishing_a_connection_is_retried():
    assert provider_connect_retries() >= 1
    transport = get_provider_rest_client()._transport
    assert isinstance(transport, httpx.AsyncHTTPTransport)
    assert transport._pool._retries == provider_connect_retries()


async def test_proxy_environment_is_honoured():
    assert get_provider_rest_client().trust_env is True


async def test_retries_are_clamped_and_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(provider_http, "_setting", lambda name, default: default)

    class _Settings:
        provider_connect_retries = 0

    monkeypatch.setattr("app.config.get_settings", lambda: _Settings(), raising=False)
    assert provider_connect_retries() == 0

    _Settings.provider_connect_retries = 999
    assert provider_connect_retries() == 10


async def test_the_client_is_rebuilt_after_it_is_closed():
    first = get_provider_rest_client()
    await close_provider_rest_client()
    assert first.is_closed
    assert get_provider_rest_client() is not first


async def test_the_video_path_no_longer_forces_a_new_connection():
    import inspect

    from app.services import openrouter_video_service as video

    source = inspect.getsource(video)
    assert '"Connection", "close"' not in source
    assert "get_provider_rest_client" in source


async def test_the_ssrf_safe_client_also_retries_its_handshake():
    """Downloading a finished video is one handshake at the worst moment.

    `fetch_video_asset` gets the clip after the provider has generated and
    billed it. That fetch had a single connect attempt and a 10s budget, so on
    a host losing new connections the job could die holding a paid-for video.
    """
    from app.services.ssrf_guard import PinnedNetworkBackend, safe_client

    client = safe_client()
    try:
        pool = client._transport._pool
        assert pool._retries == provider_connect_retries() >= 1
        assert client.timeout.connect == provider_connect_timeout()
        # Retrying must not cost the SSRF guarantee: every dial still goes
        # through the pinning backend, which re-resolves and re-validates.
        assert isinstance(pool._network_backend, PinnedNetworkBackend)
        # And it must not start honouring a proxy, which would hand the
        # destination back to the proxy and defeat that pinning.
        assert client.trust_env is False
    finally:
        await client.aclose()


async def test_an_explicit_argument_still_wins_over_the_safe_default():
    from app.services.ssrf_guard import safe_client

    client = safe_client(timeout=httpx.Timeout(3.0, connect=1.0))
    try:
        assert client.timeout.connect == 1.0
    finally:
        await client.aclose()
