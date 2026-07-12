"""SSRF guard for user-supplied outbound HTTP(S) fetches.

Several user-reachable features cause the Alpha Router backend to fetch arbitrary
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

import ipaddress
import socket
from typing import Iterable
from urllib.parse import urlparse

import httpx

from app.config import get_settings


class SSRFBlockedError(ValueError):
    """Raised when a URL resolves to a forbidden (internal) target."""


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
            raise SSRFBlockedError(f"Unparseable resolved IP: {ip_str}")
        if _is_forbidden_ip(ip):
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
    # If hostname is already an IP literal, check it directly.
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        _check_resolved_ips([str(ip)])
        return
    except ValueError:
        pass
    ips = _resolve_hosts(parsed.hostname)
    if not ips:
        # Could be a relative/invalid host; block rather than risk a fallback.
        raise SSRFBlockedError(f"Could not resolve hostname: {parsed.hostname}")
    _check_resolved_ips(ips)


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
    kwargs.setdefault("follow_redirects", True)
    kwargs.setdefault("max_redirects", 4)
    kwargs.setdefault("timeout", httpx.Timeout(20.0, connect=10.0))
    return httpx.AsyncClient(**kwargs)
