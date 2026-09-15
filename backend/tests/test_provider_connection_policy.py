"""Every outbound provider call should share one connection policy.

The video fix gave the OpenRouter video path a pooled, retrying client with a
short connect budget, and left the rest of the provider calls as they were:
built per call, with a *scalar* httpx timeout. A scalar timeout is the trap -
`httpx.Timeout(60.0)` sets connect to 60 seconds as well, so on a host that
loses new connections a catalog sync stalled for a minute with no second
attempt, and Replicate video (the same submit-then-poll shape as OpenRouter)
built a brand-new client for every single status GET.
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from app.services.provider_http import (
    build_provider_client,
    provider_connect_retries,
    provider_connect_timeout,
)

_PROVIDER_MODULES = (
    "app.services.model_sync",
    "app.services.provider_reconciliation_service",
    "app.services.video_providers.replicate",
    "app.services.proxy_service",
)


def test_a_scalar_timeout_really_does_set_the_connect_budget():
    """The premise, pinned: this is why the old call sites were wrong."""
    assert httpx.Timeout(60.0).connect == 60.0
    assert httpx.Timeout(60.0, connect=5.0).connect == 5.0


@pytest.mark.parametrize("module_name", _PROVIDER_MODULES)
def test_no_provider_module_builds_its_own_unpoliced_client(module_name):
    import importlib

    source = inspect.getsource(importlib.import_module(module_name))
    assert "httpx.AsyncClient(" not in source, f"{module_name} builds a client outside the shared policy"


async def test_a_caller_with_its_own_budget_still_gets_the_shared_connect_policy():
    client = build_provider_client(read_timeout=20.0)
    try:
        assert client.timeout.read == 20.0
        # The point of the helper: the read budget is the caller's, the
        # connect budget and the retries are not.
        assert client.timeout.connect == provider_connect_timeout()
        assert client._transport._pool._retries == provider_connect_retries()
        assert client._transport._pool._max_keepalive_connections > 0
    finally:
        await client.aclose()


async def test_the_default_read_budget_is_the_provider_timeout():
    from app.config import get_settings

    client = build_provider_client()
    try:
        assert client.timeout.read == get_settings().provider_http_timeout_seconds
    finally:
        await client.aclose()


async def test_the_shared_client_is_never_handed_out_closed():
    from app.services.provider_http import close_provider_rest_client, get_provider_rest_client

    first = get_provider_rest_client()
    await close_provider_rest_client()
    second = get_provider_rest_client()
    try:
        assert second is not first
        assert not second.is_closed
    finally:
        await close_provider_rest_client()


def test_replicate_does_not_close_the_shared_client():
    """Closing it would break every other provider request in flight."""
    from app.services.video_providers.replicate import ReplicateVideoAdapter

    source = inspect.getsource(ReplicateVideoAdapter._request)
    assert "get_provider_rest_client()" in source
    assert "aclose" not in source
    assert "async with" not in source


async def test_closing_the_shared_client_never_aborts_shutdown():
    """A pooled client holds live sockets; closing one can raise.

    It really does in the suite, where an earlier test leaves a connection
    belonging to a loop that has since closed. In production the same thing
    would abort the rest of the shutdown sequence and leave this module
    pointing at a client nobody can use.
    """
    from app.services import provider_http

    class _Exploding:
        is_closed = False

        async def aclose(self):
            raise RuntimeError("Event loop is closed")

    provider_http._shared_client = _Exploding()  # type: ignore[assignment]
    await provider_http.close_provider_rest_client()
    assert provider_http._shared_client is None

    fresh = provider_http.get_provider_rest_client()
    assert not fresh.is_closed
    await provider_http.close_provider_rest_client()
