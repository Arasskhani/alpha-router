"""Trusted-proxy client IP resolution."""

import ipaddress

import pytest
from starlette.requests import Request

from app.services import client_ip as client_ip_module
from app.services.client_ip import _parse_proc_route_gateways, resolve_client_ip


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = []
    if forwarded is not None:
        headers.append((b"x-forwarded-for", forwarded.encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "headers": headers,
            "query_string": b"",
            "client": (peer, 4321),
            "server": ("test", 80),
            "scheme": "http",
        }
    )


def test_untrusted_peer_ignores_spoofed_xff():
    ip = resolve_client_ip(_request("203.0.113.9", "1.2.3.4"), trusted_cidrs="127.0.0.1/32")
    assert ip == "203.0.113.9"


def test_trusted_peer_uses_rightmost_untrusted_xff_hop():
    ip = resolve_client_ip(
        _request("127.0.0.1", "203.0.113.10, 10.0.0.2"),
        trusted_cidrs="127.0.0.1/32,10.0.0.0/8",
    )
    assert ip == "203.0.113.10"


def test_loopback_peer_without_xff_is_loopback():
    assert resolve_client_ip(_request("127.0.0.1"), trusted_cidrs="127.0.0.1/32") == "127.0.0.1"


# Addresses in /proc/net/route are little-endian hex: 010012AC is 172.18.0.1.
PROC_ROUTE_SAMPLE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT
eth0\t00000000\t010012AC\t0003\t0\t0\t0\t00000000\t0\t0\t0
eth0\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
lo\t00000000\t0100007F\t0003\t0\t0\t0\t00000000\t0\t0\t0
"""


def test_proc_route_parsing_finds_bridge_gateway():
    assert _parse_proc_route_gateways(PROC_ROUTE_SAMPLE) == [ipaddress.ip_address("172.18.0.1")]
    assert _parse_proc_route_gateways("") == []


@pytest.fixture
def gateway_peer(monkeypatch):
    """Pretend the container's default gateway is 172.18.0.1."""
    monkeypatch.setattr(
        client_ip_module,
        "local_gateway_networks",
        lambda: [ipaddress.ip_network("172.18.0.1/32")],
    )
    yield "172.18.0.1"
    client_ip_module.reset_gateway_cache()


def test_docker_gateway_peer_is_trusted_so_edge_xff_is_used(gateway_peer):
    # The host-network TLS edge reaches the app through the published port, so
    # Docker rewrites the source address to the bridge gateway.
    ip = resolve_client_ip(
        _request(gateway_peer, "198.51.100.7"),
        trusted_cidrs="127.0.0.1/32,::1/128",
    )
    assert ip == "198.51.100.7"


def test_gateway_trust_can_be_disabled(gateway_peer, monkeypatch):
    settings = client_ip_module.get_settings()
    monkeypatch.setattr(settings, "trust_local_gateway_proxy", False, raising=False)
    ip = resolve_client_ip(
        _request(gateway_peer, "198.51.100.7"),
        trusted_cidrs="127.0.0.1/32,::1/128",
    )
    assert ip == gateway_peer
