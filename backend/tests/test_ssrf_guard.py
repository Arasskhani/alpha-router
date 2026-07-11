"""Phase 5: SSRF guard must block internal/private/metadata targets.

The guard validates that a URL is http(s) and that its resolved IPs are not
loopback / private / link-local / multicast / reserved / unspecified. IP
literals are checked directly. The opt-in ``ALLOW_SSRF_PRIVATE_RANGES`` flag
disables the check for self-hosted internal deployments.
"""

import ipaddress
import socket
from unittest.mock import patch

import pytest

from app.services import ssrf_guard


def _patch_settings(allow_private: bool = False):
    class _S:
        allow_ssrf_private_ranges = allow_private
    return patch("app.services.ssrf_guard.get_settings", return_value=_S())


def test_assert_url_safe_rejects_non_http_scheme():
    with _patch_settings():
        with pytest.raises(ssrf_guard.SSRFBlockedError):
            ssrf_guard.assert_url_safe("file:///etc/passwd")
        with pytest.raises(ssrf_guard.SSRFBlockedError):
            ssrf_guard.assert_url_safe("ftp://example.com/x")


def test_assert_url_safe_rejects_empty_and_no_host():
    with _patch_settings():
        with pytest.raises(ssrf_guard.SSRFBlockedError):
            ssrf_guard.assert_url_safe("")
        with pytest.raises(ssrf_guard.SSRFBlockedError):
            ssrf_guard.assert_url_safe("http:///path")


def test_assert_url_safe_blocks_loopback_ip_literal():
    with _patch_settings():
        for u in ("http://127.0.0.1/", "http://localhost/x", "http://[::1]/"):
            with pytest.raises(ssrf_guard.SSRFBlockedError):
                ssrf_guard.assert_url_safe(u)


def test_assert_url_safe_blocks_private_ranges():
    with _patch_settings():
        for u in ("http://10.0.0.1/", "http://172.16.5.4/", "http://192.168.1.1/"):
            with pytest.raises(ssrf_guard.SSRFBlockedError):
                ssrf_guard.assert_url_safe(u)


def test_assert_url_safe_blocks_cloud_metadata():
    with _patch_settings():
        with pytest.raises(ssrf_guard.SSRFBlockedError):
            ssrf_guard.assert_url_safe("http://169.254.169.254/latest/meta-data/")


def test_assert_url_safe_blocks_hostname_resolving_to_internal():
    # Force getaddrinfo to return a loopback IP for an innocent-looking host.
    fake_info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
    with _patch_settings():
        with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=fake_info):
            with pytest.raises(ssrf_guard.SSRFBlockedError):
                ssrf_guard.assert_url_safe("http://innocent.example.com/")


def test_assert_url_safe_allows_public_ip_literal():
    with _patch_settings():
        # 8.8.8.8 is a public DNS IP — should pass.
        ssrf_guard.assert_url_safe("http://8.8.8.8/")
        ssrf_guard.assert_url_safe("https://1.1.1.1/")


def test_assert_url_safe_allows_public_hostname():
    fake_info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    with _patch_settings():
        with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=fake_info):
            ssrf_guard.assert_url_safe("http://example.com/")


def test_assert_url_safe_blocks_unresolvable_host():
    with _patch_settings():
        with patch("app.services.ssrf_guard.socket.getaddrinfo", side_effect=socket.gaierror):
            with pytest.raises(ssrf_guard.SSRFBlockedError):
                ssrf_guard.assert_url_safe("http://nonexistent.invalid/")


def test_allow_private_ranges_opt_in_allows_internal():
    with _patch_settings(allow_private=True):
        # Should NOT raise.
        ssrf_guard.assert_url_safe("http://127.0.0.1/")
        ssrf_guard.assert_url_safe("http://10.0.0.1/")


def test_is_forbidden_ip_covers_categories():
    with _patch_settings():
        forbidden = [
            ipaddress.ip_address("127.0.0.1"),  # loopback
            ipaddress.ip_address("10.1.2.3"),  # private
            ipaddress.ip_address("172.16.0.1"),  # private
            ipaddress.ip_address("192.168.0.1"),  # private
            ipaddress.ip_address("169.254.169.254"),  # link-local / metadata
            ipaddress.ip_address("::1"),  # loopback v6
            ipaddress.ip_address("224.0.0.1"),  # multicast
            ipaddress.ip_address("0.0.0.0"),  # unspecified
        ]
        for ip in forbidden:
            assert ssrf_guard._is_forbidden_ip(ip), f"{ip} should be forbidden"
        public = [
            ipaddress.ip_address("8.8.8.8"),
            ipaddress.ip_address("1.1.1.1"),
            ipaddress.ip_address("2606:4700:4700::1111"),
        ]
        for ip in public:
            assert not ssrf_guard._is_forbidden_ip(ip), f"{ip} should be allowed"
