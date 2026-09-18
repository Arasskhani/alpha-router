"""The admin IP allowlist cannot be passed with a forged loopback header.

``ip_matches_allowlist`` auto-passes anything ``ip_is_loopback`` accepts, which
is the whole of 127.0.0.0/8. The trusted-proxy set was ``127.0.0.1/32``. So
``127.0.0.2`` was *not* skipped as a proxy hop - it was returned as the client -
and then waved through the allowlist unconditionally.

Any request whose direct peer is a trusted proxy (the Docker bridge gateway is
trusted by default) could send ``X-Forwarded-For: 127.0.0.2`` and defeat enforce
mode across the entire admin surface. The existing allowlist tests only ever
used ``127.0.0.1``, which is the one loopback address both definitions agreed on.
"""

from __future__ import annotations

import pytest

from app.services.admin_ip_allowlist_service import ip_matches_allowlist
from app.services.client_ip import (
    canonical_ip,
    ip_in_networks,
    ip_is_loopback,
    resolve_client_ip,
    trusted_proxy_networks,
)


class _Request:
    def __init__(self, peer: str, forwarded: str | None = None) -> None:
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


@pytest.mark.parametrize("address", ["127.0.0.1", "127.0.0.2", "127.255.255.254", "::1"])
def test_every_address_the_allowlist_calls_loopback_is_a_trusted_hop(address):
    """The two definitions have to describe the same set."""

    assert ip_is_loopback(address)
    assert ip_in_networks(canonical_ip(address), trusted_proxy_networks()), (
        f"{address} passes the allowlist as loopback but is not skipped as a proxy hop"
    )


def test_a_forged_loopback_hop_does_not_become_the_client():
    resolved = resolve_client_ip(_Request("127.0.0.1", "127.0.0.2"), trusted_cidrs="127.0.0.1/32")
    assert not ip_is_loopback(resolved) or resolved == "127.0.0.1", resolved


def test_a_forged_loopback_hop_behind_a_gateway_does_not_pass_the_allowlist():
    """The realistic shape: the peer is a trusted proxy, the header is attacker-controlled."""

    resolved = resolve_client_ip(_Request("172.18.0.1", "127.0.0.2"), trusted_cidrs="172.18.0.1/32")
    assert resolved == "172.18.0.1"
    assert not ip_matches_allowlist(resolved, [], allow_loopback=True)


def test_a_real_client_behind_nginx_is_still_resolved():
    """nginx appends its own peer, so the rightmost untrusted hop is the client."""

    resolved = resolve_client_ip(
        _Request("127.0.0.1", "203.0.113.9, 127.0.0.1"),
        trusted_cidrs="127.0.0.1/32",
    )
    assert resolved == "203.0.113.9"
    assert not ip_matches_allowlist(resolved, [], allow_loopback=True)


def test_a_genuine_loopback_request_still_passes():
    """The auto-pass exists so an operator on the host is never locked out."""

    resolved = resolve_client_ip(_Request("127.0.0.1"), trusted_cidrs="127.0.0.1/32")
    assert resolved == "127.0.0.1"
    assert ip_matches_allowlist(resolved, [], allow_loopback=True)
