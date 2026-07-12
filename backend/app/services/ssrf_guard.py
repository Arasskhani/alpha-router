"""SSRF guard for user-supplied outbound HTTP(S) fetches.

Several user-reachable features cause the NITRO backend to fetch arbitrary
URLs supplied by an authenticated user (web-fetch chat tool, image-generation
reference image, media import via ``source_url``). Without validation, an
attacker can make the server fetch internal resources — cloud metadata
endpoints (``169.254.169.254``), loopback services, RFC1918 private ranges,
etc. — and exfiltrate the response body back through chat / image results.

This module centralizes target validation:

* Reject non-http(s) schemes.
* Resolve the hostname to IP address(es) and reject any that are loopback,
  private, link-local, multicast, reserved, or unspecified.
* Provide a post-redirect re-validation helper so a public URL that 302s to an
  internal address is still blocked (``follow_redirects`` alone is unsafe).

The check is IP-based because regex/hostname checks alone cannot defeat DNS
resolution to internal IPs, redirects, or DNS rebinding.

Set ``ALLOW_SSRF_PRIVATE_RANGES=true`` to opt out (e.g. self-hosted internal
deployments where users fetch from private documentation servers). Default is
to block.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from typing import Iterable
from urllib.parse import urlparse

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

from app.config import get_settings

logger = logging.getLogger(__name__)


class SSRFBlockedError(ValueError):
    """Raised when a URL resolves to a forbidden (internal) target."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("URL target is not allowed")


def _private_ranges_allowed() -> bool:
    return bool(getattr(get_settings(), "allow_ssrf_private_ranges", False))


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for loopback / private / link-local / multicast / reserved / unspecified IPs."""
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True
    # Cloud metadata endpoints (AWS/Azure/GCP) live in 169.254.0.0/16 (link-local)
    # which is already caught by is_link_local, but be explicit for clarity:
    # 169.254.169.254 is the canonical metadata IP.
    return False


def _resolve_hosts(hostname: str) -> list[str]:
    """Resolve a hostname to a list of IP address strings (A/AAAA)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return []
    seen: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.append(addr)
    return seen


def _check_resolved_ips(ips: Iterable[str]) -> None:
    if _private_ranges_allowed():
        return
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            # If it's not a parseable IP, treat it as suspicious and block.
            logger.warning("Blocked SSRF target with unparseable resolved IP")
            raise SSRFBlockedError(f"Unparseable resolved IP: {ip_str}")
        if _is_forbidden_ip(ip):
            logger.warning("Blocked SSRF connection to forbidden IP %s", ip_str)
            raise SSRFBlockedError(f"URL resolves to forbidden IP {ip_str}")


def assert_url_safe(url: str) -> None:
    """Validate that a URL is http(s) and does not resolve to an internal IP.

    Raises ``SSRFBlockedError`` if the target is forbidden. Does not fetch.
    """
    if not url:
        raise SSRFBlockedError("Empty URL")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFBlockedError(f"Disallowed scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise SSRFBlockedError("No hostname in URL")
    if parsed.username is not None or parsed.password is not None:
        raise SSRFBlockedError("URL userinfo is not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SSRFBlockedError("Invalid URL port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise SSRFBlockedError("Invalid URL port")
    _resolve_and_validate(parsed.hostname)


def _resolve_and_validate(hostname: str) -> list[str]:
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        ips = _resolve_hosts(hostname)
    else:
        ips = [str(literal)]
    if not ips:
        logger.warning("Blocked SSRF target with unresolvable hostname %s", hostname)
        raise SSRFBlockedError(f"Could not resolve hostname: {hostname}")
    _check_resolved_ips(ips)
    return ips


class PinnedNetworkBackend:
    """Resolve, validate, then connect to the exact approved IP."""

    def __init__(self, backend=None):
        self._backend = backend or AutoBackend()

    async def connect_tcp(
        self,
        host: str | bytes,
        port: int,
        timeout: float | None = None,
        local_address: bytes | None = None,
        socket_options=None,
    ):
        hostname = host.decode("ascii") if isinstance(host, bytes) else host
        ips = await asyncio.to_thread(_resolve_and_validate, hostname)
        if not bool(getattr(get_settings(), "enable_ssrf_dns_pinning", True)):
            return await self._backend.connect_tcp(
                host,
                port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )
        last_error: Exception | None = None
        for ip in ips:
            try:
                dial_host = ip.encode("ascii") if isinstance(host, bytes) else ip
                return await self._backend.connect_tcp(
                    dial_host,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (OSError, httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise httpcore.ConnectError(f"Unable to connect to {hostname}")

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.UnsupportedProtocol("Unix sockets are not allowed for SSRF-safe HTTP")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """httpx transport whose TCP dial target is the validated DNS result."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pool._network_backend = PinnedNetworkBackend()  # noqa: SLF001


def assert_response_target_safe(response: httpx.Response) -> None:
    """Re-validate the final (post-redirect) request target of a response.

    Call this after a fetch with ``follow_redirects=True`` so a public URL that
    redirects to an internal address is still rejected before the response body
    is consumed by the caller.
    """
    if _private_ranges_allowed():
        return
    req = response.request
    final_url = str(req.url)
    # Re-run the full check against the final URL (resolves the final host).
    assert_url_safe(final_url)


def safe_client(**kwargs) -> httpx.AsyncClient:
    """Build an httpx AsyncClient with sane SSRF-aware defaults.

    Redirects are followed (callers must call ``assert_response_target_safe``
    on the response) with a bounded redirect limit and default timeouts.
    """
    kwargs.setdefault("follow_redirects", False)
    kwargs.setdefault("timeout", httpx.Timeout(20.0, connect=10.0))
    kwargs.setdefault("trust_env", False)
    kwargs.setdefault("transport", PinnedAsyncHTTPTransport())
    return httpx.AsyncClient(**kwargs)
