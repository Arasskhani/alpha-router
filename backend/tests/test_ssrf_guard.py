"""Phase 5: SSRF guard must block internal/private/metadata targets.

The guard validates that a URL is http(s) and that its resolved IPs are not
loopback / private / link-local / multicast / reserved / unspecified. IP
literals are checked directly. The opt-in ``ALLOW_SSRF_PRIVATE_RANGES`` flag
disables the check for self-hosted internal deployments.
"""

import ipaddress
import asyncio
import socket
import ssl
from datetime import datetime, timedelta, timezone
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
        with pytest.raises(ssrf_guard.SSRFBlockedError) as exc:
            ssrf_guard.assert_url_safe("http://169.254.169.254/latest/meta-data/")
        assert str(exc.value) == "URL target is not allowed"
        assert "169.254.169.254" not in str(exc.value)
        assert "169.254.169.254" in exc.value.reason


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


def test_url_userinfo_and_encoded_loopback_are_blocked():
    fake_info = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
    with _patch_settings():
        with pytest.raises(ssrf_guard.SSRFBlockedError):
            ssrf_guard.assert_url_safe("http://user:pass@example.com/")
        with patch("app.services.ssrf_guard.socket.getaddrinfo", return_value=fake_info):
            with pytest.raises(ssrf_guard.SSRFBlockedError):
                ssrf_guard.assert_url_safe("http://2130706433/")


class FakeNetworkBackend:
    def __init__(self, failing: set[bytes] | None = None):
        self.calls = []
        self.failing = failing or set()

    async def connect_tcp(self, host, port, **kwargs):
        self.calls.append((host, port, kwargs))
        if host in self.failing:
            raise ssrf_guard.httpcore.ConnectError("failed")
        return object()

    async def sleep(self, seconds):
        del seconds


def test_pinned_backend_connects_to_validated_ip_not_hostname():
    backend = FakeNetworkBackend()
    pinned = ssrf_guard.PinnedNetworkBackend(backend)
    with (
        _patch_settings(),
        patch.object(ssrf_guard, "_resolve_hosts", return_value=["93.184.216.34"]),
    ):
        asyncio.run(pinned.connect_tcp(b"example.com", 443))
    assert backend.calls[0][0] == b"93.184.216.34"


def test_pinned_backend_blocks_dns_rebinding_at_connect_time():
    backend = FakeNetworkBackend()
    pinned = ssrf_guard.PinnedNetworkBackend(backend)
    with _patch_settings():
        with patch.object(
            ssrf_guard,
            "_resolve_hosts",
            side_effect=[["93.184.216.34"], ["127.0.0.1"]],
        ):
            ssrf_guard.assert_url_safe("https://example.com/image.png")
            with pytest.raises(ssrf_guard.SSRFBlockedError):
                asyncio.run(pinned.connect_tcp(b"example.com", 443))
    assert backend.calls == []


def test_pinned_backend_tries_multiple_approved_addresses():
    backend = FakeNetworkBackend(failing={b"93.184.216.34"})
    pinned = ssrf_guard.PinnedNetworkBackend(backend)
    with (
        _patch_settings(),
        patch.object(
            ssrf_guard,
            "_resolve_hosts",
            return_value=["93.184.216.34", "1.1.1.1"],
        ),
    ):
        asyncio.run(pinned.connect_tcp(b"example.com", 443))
    assert [call[0] for call in backend.calls] == [b"93.184.216.34", b"1.1.1.1"]


def test_safe_client_uses_pinned_transport_and_manual_redirects():
    client = ssrf_guard.safe_client()
    try:
        assert isinstance(client._transport, ssrf_guard.PinnedAsyncHTTPTransport)
        assert client.follow_redirects is False
    finally:
        asyncio.run(client.aclose())


def test_pinned_https_preserves_host_header_and_tls_sni(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "public.test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("public.test")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    async def run():
        sni_names = []
        request_headers = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        context.set_servername_callback(lambda _sock, name, _ctx: sni_names.append(name))

        async def handler(reader, writer):
            request_headers.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handler, "127.0.0.1", 0, ssl=context)
        port = server.sockets[0].getsockname()[1]
        try:
            transport = ssrf_guard.PinnedAsyncHTTPTransport(verify=False)
            async with ssrf_guard.httpx.AsyncClient(transport=transport) as client:
                response = await client.get(f"https://public.test:{port}/")
                assert response.text == "ok"
        finally:
            server.close()
            await server.wait_closed()
        return sni_names, request_headers

    with (
        _patch_settings(allow_private=True),
        patch.object(ssrf_guard, "_resolve_hosts", return_value=["127.0.0.1"]),
    ):
        sni_names, request_headers = asyncio.run(run())
    assert sni_names == ["public.test"]
    assert f"host: public.test:".encode() in request_headers[0].lower()
