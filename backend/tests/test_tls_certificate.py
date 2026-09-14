"""TLS certificate validation and nginx config rendering."""

import datetime
import os
import stat
from ipaddress import IPv4Address

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.services.tls_certificate_service import TlsCertificateError, parse_pem_bundle
from app.services.tls_edge_service import (
    atomic_write,
    edge_listener_applied,
    materialize_certificate_files,
    render_nginx_config,
    tls_health_url,
    validate_https_port,
    wipe_materialized_certificate_files,
)


def _self_signed(days: int = 30, key_size: int = 2048) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(IPv4Address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return cert_pem, key_pem


def test_parse_matching_pem_bundle():
    cert_pem, key_pem = _self_signed()
    parsed = parse_pem_bundle(cert_pem=cert_pem, key_pem=key_pem)
    assert parsed.key_algorithm == "RSA"
    assert parsed.key_bits == 2048
    assert parsed.fingerprint
    assert "PRIVATE KEY" not in parsed.cert_pem


def test_parse_rejects_mismatched_key():
    cert_pem, _ = _self_signed()
    _, other_key = _self_signed()
    with pytest.raises(TlsCertificateError, match="does not match"):
        parse_pem_bundle(cert_pem=cert_pem, key_pem=other_key)


def test_parse_rejects_weak_rsa():
    try:
        cert_pem, key_pem = _self_signed(key_size=1024)
    except ValueError:
        pytest.skip("this OpenSSL build cannot generate 1024-bit RSA keys")
    with pytest.raises(TlsCertificateError, match="2048"):
        parse_pem_bundle(cert_pem=cert_pem, key_pem=key_pem)


def test_reserved_https_ports():
    with pytest.raises(TlsCertificateError):
        validate_https_port(8080)
    assert validate_https_port(443) == 443
    assert validate_https_port(8443) == 8443


def test_nginx_config_snapshot():
    config = render_nginx_config(
        https_port=443,
        http_mode="redirect",
        hsts_enabled=True,
        has_chain=True,
    )
    assert "listen 443 ssl;" in config
    assert "ssl_certificate /etc/alpha-router/tls/fullchain.pem;" in config
    assert "ssl_certificate /etc/alpha-router/tls/cert.pem;" not in config
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in config
    assert "proxy_set_header X-Forwarded-Proto https;" in config
    assert "proxy_buffering off;" in config
    assert "listen 80 default_server;" in config
    assert "Strict-Transport-Security" in config
    assert "ssl_stapling on;" in config
    assert "proxy_pass http://127.0.0.1:8080;" in config
    assert "client_max_body_size 1024m;" in config


def test_parse_rejects_passphrase_for_unencrypted_key():
    cert_pem, key_pem = _self_signed()
    with pytest.raises(TlsCertificateError, match="not encrypted"):
        parse_pem_bundle(cert_pem=cert_pem, key_pem=key_pem, password="unexpected")


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not enforced on Windows")
def test_atomic_write_never_widens_private_key_mode(tmp_path):
    target = tmp_path / "key.pem"
    atomic_write(target, "secret-key-material", mode=0o600)
    assert target.read_text(encoding="utf-8") == "secret-key-material"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    # Rewriting an existing key keeps the restrictive mode.
    atomic_write(target, "rotated", mode=0o600)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not (tmp_path / "key.pem.tmp").exists()


def test_materialize_writes_fullchain_and_wipe_removes_key(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.tls_edge_service.tls_state_dir", lambda: tmp_path)
    leaf = "-----BEGIN CERTIFICATE-----\nLEAF\n-----END CERTIFICATE-----\n"
    chain = "-----BEGIN CERTIFICATE-----\nCHAIN\n-----END CERTIFICATE-----\n"
    materialize_certificate_files(leaf, "PRIVATE", chain)
    assert "LEAF" in (tmp_path / "fullchain.pem").read_text(encoding="utf-8")
    assert "CHAIN" in (tmp_path / "fullchain.pem").read_text(encoding="utf-8")
    assert (tmp_path / "key.pem").read_text(encoding="utf-8") == "PRIVATE"
    wipe_materialized_certificate_files()
    assert not (tmp_path / "key.pem").exists()
    assert not (tmp_path / "fullchain.pem").exists()
    assert not (tmp_path / "cert.pem").exists()
    assert not (tmp_path / "chain.pem").exists()


def test_tls_health_url_brackets_ipv6():
    assert tls_health_url("127.0.0.1", 443) == "https://127.0.0.1:443/health"
    assert tls_health_url("::1", 8443) == "https://[::1]:8443/health"


def test_edge_listener_applied_requires_matching_generation(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.tls_edge_service.tls_state_dir", lambda: tmp_path)
    assert edge_listener_applied() is False
    (tmp_path / "desired-state.json").write_text(
        '{"enabled": true, "generation": 3}\n', encoding="utf-8"
    )
    (tmp_path / "apply-status.json").write_text(
        '{"generation": 2, "ok": true}\n', encoding="utf-8"
    )
    assert edge_listener_applied() is False
    (tmp_path / "apply-status.json").write_text(
        '{"generation": 3, "ok": true}\n', encoding="utf-8"
    )
    assert edge_listener_applied() is True


def test_nginx_config_is_hardened():
    from app.services.tls_edge_service import render_nginx_config

    conf = render_nginx_config(https_port=443, http_mode="redirect", hsts_enabled=True, has_chain=False, max_body_mb=100)
    assert "server_tokens off;" in conf
    assert "access_log off;" in conf
    assert "ssl_session_tickets off;" in conf
    assert "ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256" in conf
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in conf
