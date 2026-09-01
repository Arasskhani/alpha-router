"""Trusted-proxy-aware client IP resolution."""

from __future__ import annotations

import ipaddress
import socket
import struct
from pathlib import Path
from typing import Iterable

from fastapi import Request

from app.config import get_settings

DEFAULT_TRUSTED_PROXY_CIDRS = "127.0.0.1/32,::1/128"
PROC_NET_ROUTE = Path("/proc/net/route")

_gateway_networks: list[ipaddress._BaseNetwork] | None = None


def parse_cidrs(raw: str | None) -> list[ipaddress._BaseNetwork]:
    networks: list[ipaddress._BaseNetwork] = []
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            continue
    return networks


def canonical_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("[") and raw.endswith("]") and raw.count(":") >= 2:
        raw = raw[1:-1]
    if "%" in raw:
        raw = raw.split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def ip_in_networks(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: Iterable[ipaddress._BaseNetwork],
) -> bool:
    return any(addr in network for network in networks)


def _parse_proc_route_gateways(text: str) -> list[ipaddress.IPv4Address]:
    """Return default-route gateways from /proc/net/route content."""
    gateways: list[ipaddress.IPv4Address] = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 3 or fields[0] == "lo":
            continue
        if fields[1] != "00000000":
            continue
        try:
            packed = struct.pack("<L", int(fields[2], 16))
        except (ValueError, struct.error):
            continue
        addr = ipaddress.ip_address(socket.inet_ntoa(packed))
        if not addr.is_unspecified and addr not in gateways:
            gateways.append(addr)
    return gateways


def local_gateway_networks() -> list[ipaddress._BaseNetwork]:
    """Default-route gateway addresses of this container, cached per process.

    Docker SNATs traffic that reaches a published port from the host itself
    (which is how the host-network TLS edge reaches the app) to the bridge
    gateway address. Trusting that single address is what lets X-Forwarded-For
    from the edge be honoured, while traffic routed in from outside keeps its
    real source address and stays untrusted.
    """
    global _gateway_networks
    if _gateway_networks is not None:
        return _gateway_networks
    networks: list[ipaddress._BaseNetwork] = []
    try:
        text = PROC_NET_ROUTE.read_text(encoding="ascii", errors="ignore")
    except OSError:
        text = ""
    for addr in _parse_proc_route_gateways(text):
        networks.append(ipaddress.ip_network(f"{addr}/32"))
    _gateway_networks = networks
    return networks


def reset_gateway_cache() -> None:
    global _gateway_networks
    _gateway_networks = None


def trusted_proxy_networks(raw: str | None = None) -> list[ipaddress._BaseNetwork]:
    settings = get_settings()
    value = raw if raw is not None else getattr(settings, "trusted_proxy_cidrs", DEFAULT_TRUSTED_PROXY_CIDRS)
    networks = parse_cidrs(value)
    if not networks:
        networks = parse_cidrs(DEFAULT_TRUSTED_PROXY_CIDRS)
    if getattr(settings, "trust_local_gateway_proxy", True):
        for network in local_gateway_networks():
            if network not in networks:
                networks.append(network)
    return networks


def peer_ip(request: Request) -> str | None:
    if request.client and request.client.host:
        addr = canonical_ip(request.client.host)
        return str(addr) if addr else request.client.host[:64]
    return None


def resolve_client_ip(request: Request, *, trusted_cidrs: str | None = None) -> str | None:
    """Return the client IP, trusting X-Forwarded-For only from known proxies.

    Walks XFF right-to-left and skips hops that are themselves trusted proxies.
    When the direct peer is not trusted, forwarded headers are ignored.
    """
    peer = canonical_ip(request.client.host if request.client else None)
    if peer is None:
        return None
    trusted = trusted_proxy_networks(trusted_cidrs)
    if not ip_in_networks(peer, trusted):
        return str(peer)

    forwarded = request.headers.get("x-forwarded-for") or ""
    hops = [canonical_ip(part) for part in forwarded.split(",")]
    hops = [hop for hop in hops if hop is not None]
    for hop in reversed(hops):
        if not ip_in_networks(hop, trusted):
            return str(hop)
    return str(peer)


def ip_is_loopback(value: str | None) -> bool:
    addr = canonical_ip(value)
    return bool(addr and addr.is_loopback)
