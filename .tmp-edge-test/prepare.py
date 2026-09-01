"""Generate a self-signed cert + rendered nginx.conf for the edge container test."""

from __future__ import annotations

import datetime
import json
import pathlib
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app.services.tls_edge_service import render_nginx_config  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent


def main() -> int:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    (OUT / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (OUT / "key.pem").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    config = render_nginx_config(
        https_port=443,
        http_mode="loopback_only",
        hsts_enabled=True,
        has_chain=False,
        upstream="edge_test_app:8080",
    )
    (OUT / "nginx.conf").write_text(config, encoding="utf-8", newline="\n")
    (OUT / "desired-state.json").write_text(
        json.dumps({"enabled": True, "generation": 1, "https_port": 443}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("prepared cert.pem, key.pem, nginx.conf, desired-state.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
