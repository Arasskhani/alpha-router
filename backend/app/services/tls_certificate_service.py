"""Parse, validate, and persist TLS certificates without exposing private keys."""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.security import TlsCertificate
from app.services.secret_crypto import decrypt_secret, encrypt_secret

MAX_CERT_UPLOAD_BYTES = 256 * 1024
MIN_RSA_BITS = 2048
MIN_EC_BITS = 256


class TlsCertificateError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCertificate:
    cert_pem: str
    key_pem: str
    chain_pem: str
    subject: str
    issuer: str
    serial: str
    sans: list[str]
    not_before: datetime.datetime
    not_after: datetime.datetime
    fingerprint: str
    key_algorithm: str
    key_bits: int
    warnings: list[str]


def _pem_blocks(raw: str) -> list[bytes]:
    blocks: list[bytes] = []
    current: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line.startswith("-----BEGIN "):
            current = [line]
            continue
        if current:
            current.append(line)
            if line.startswith("-----END "):
                blocks.append("\n".join(current).encode("ascii") + b"\n")
                current = []
    return blocks


def _load_certificates(pem: str) -> list[x509.Certificate]:
    certs: list[x509.Certificate] = []
    for block in _pem_blocks(pem):
        if b"BEGIN CERTIFICATE" not in block:
            continue
        certs.append(x509.load_pem_x509_certificate(block))
    if not certs:
        raise TlsCertificateError("No certificate was found in the uploaded file.")
    return certs


def _load_private_key(pem: str, password: str | None):
    blocks = [block for block in _pem_blocks(pem) if b"PRIVATE KEY" in block]
    if not blocks:
        raise TlsCertificateError("No private key was found in the uploaded file.")
    pwd = password.encode("utf-8") if password else None
    try:
        return serialization.load_pem_private_key(blocks[0], password=pwd)
    except TypeError as exc:
        # cryptography raises TypeError both for a missing passphrase and for a
        # passphrase supplied for an unencrypted key.
        if pwd is None:
            raise TlsCertificateError("The private key is encrypted. Provide the passphrase.") from exc
        raise TlsCertificateError(
            "This private key is not encrypted. Leave the passphrase empty."
        ) from exc
    except ValueError as exc:
        raise TlsCertificateError("The private key could not be parsed. Check the file and passphrase.") from exc


def _public_key_bytes(public_key) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _key_info(private_key) -> tuple[str, int]:
    if isinstance(private_key, rsa.RSAPrivateKey):
        bits = private_key.key_size
        if bits < MIN_RSA_BITS:
            raise TlsCertificateError(f"RSA keys must be at least {MIN_RSA_BITS} bits.")
        return "RSA", bits
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        bits = private_key.curve.key_size
        if bits < MIN_EC_BITS:
            raise TlsCertificateError(f"EC keys must be at least {MIN_EC_BITS} bits.")
        return "EC", bits
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        return "Ed25519", 256
    if isinstance(private_key, dsa.DSAPrivateKey):
        raise TlsCertificateError("DSA keys are not supported.")
    return type(private_key).__name__, 0


def _names_from_cert(cert: x509.Certificate) -> list[str]:
    names = [cert.subject.rfc4514_string()]
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return names
    names.extend(ext.value.get_values_for_type(x509.DNSName))
    names.extend(str(item) for item in ext.value.get_values_for_type(x509.IPAddress))
    return names


def _frontend_host() -> str:
    url = (get_settings().frontend_url or "").strip()
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def parse_pem_bundle(
    *,
    cert_pem: str,
    key_pem: str,
    chain_pem: str = "",
    password: str | None = None,
) -> ParsedCertificate:
    certs = _load_certificates(cert_pem + ("\n" + chain_pem if chain_pem else ""))
    leaf = certs[0]
    chain = certs[1:]
    private_key = _load_private_key(key_pem, password)
    if _public_key_bytes(private_key.public_key()) != _public_key_bytes(leaf.public_key()):
        raise TlsCertificateError("The private key does not match the certificate.")
    now = datetime.datetime.now(datetime.timezone.utc)
    not_before = getattr(leaf, "not_valid_before_utc", None) or leaf.not_valid_before.replace(
        tzinfo=datetime.timezone.utc
    )
    not_after = getattr(leaf, "not_valid_after_utc", None) or leaf.not_valid_after.replace(
        tzinfo=datetime.timezone.utc
    )
    if now < not_before:
        raise TlsCertificateError("This certificate is not valid yet.")
    if now > not_after:
        raise TlsCertificateError("This certificate has expired.")
    algorithm, bits = _key_info(private_key)
    warnings: list[str] = []
    if chain:
        issuer = chain[0].subject.rfc4514_string()
        if leaf.issuer.rfc4514_string() != issuer:
            warnings.append("The certificate chain does not start with the leaf issuer.")
    else:
        warnings.append("No intermediate chain was provided. Some clients may not trust this certificate.")
    host = _frontend_host()
    sans = []
    try:
        ext = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        sans = [str(name) for name in ext.value]
    except x509.ExtensionNotFound:
        sans = []
    if host and host not in {item.lower() for item in sans} and host not in leaf.subject.rfc4514_string().lower():
        warnings.append(f"FRONTEND_URL host {host} is not listed in the certificate SAN.")
    fingerprint = hashlib.sha256(leaf.public_bytes(serialization.Encoding.DER)).hexdigest()
    key_pem_out = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    cert_pem_out = leaf.public_bytes(serialization.Encoding.PEM).decode("ascii")
    chain_out = "".join(item.public_bytes(serialization.Encoding.PEM).decode("ascii") for item in chain)
    return ParsedCertificate(
        cert_pem=cert_pem_out,
        key_pem=key_pem_out,
        chain_pem=chain_out,
        subject=leaf.subject.rfc4514_string(),
        issuer=leaf.issuer.rfc4514_string(),
        serial=format(leaf.serial_number, "x"),
        sans=sans,
        not_before=not_before.replace(tzinfo=None),
        not_after=not_after.replace(tzinfo=None),
        fingerprint=fingerprint,
        key_algorithm=algorithm,
        key_bits=bits,
        warnings=warnings,
    )


def parse_pkcs12(data: bytes, password: str | None) -> ParsedCertificate:
    pwd = password.encode("utf-8") if password else None
    try:
        key, cert, extra = pkcs12.load_key_and_certificates(data, pwd)
    except ValueError as exc:
        raise TlsCertificateError("The PKCS#12 file could not be opened. Check the password.") from exc
    if key is None or cert is None:
        raise TlsCertificateError("The PKCS#12 file must contain a certificate and private key.")
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    chain_pem = "".join(
        item.public_bytes(serialization.Encoding.PEM).decode("ascii") for item in (extra or [])
    )
    return parse_pem_bundle(cert_pem=cert_pem, key_pem=key_pem, chain_pem=chain_pem)


def _serialize(row: TlsCertificate, *, warnings: list[str] | None = None) -> dict[str, Any]:
    try:
        sans = json.loads(row.sans_json or "[]")
    except json.JSONDecodeError:
        sans = []
    now = datetime.datetime.utcnow()
    days = None
    if row.not_after:
        days = int((row.not_after - now).total_seconds() // 86400)
    payload = {
        "id": row.id,
        "label": row.label,
        "subject": row.subject,
        "issuer": row.issuer,
        "serial": row.serial,
        "sans": sans,
        "not_before": row.not_before.isoformat() + "Z" if row.not_before else None,
        "not_after": row.not_after.isoformat() + "Z" if row.not_after else None,
        "days_remaining": days,
        "sha256_fingerprint": row.sha256_fingerprint,
        "key_algorithm": row.key_algorithm,
        "key_bits": row.key_bits,
        "is_active": bool(row.is_active),
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }
    if warnings is not None:
        payload["warnings"] = warnings
    return payload


async def list_certificates(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(TlsCertificate).order_by(TlsCertificate.id.desc()))).scalars().all()
    return [_serialize(row) for row in rows]


async def get_certificate(db: AsyncSession, cert_id: int) -> TlsCertificate:
    row = await db.get(TlsCertificate, cert_id)
    if row is None:
        raise TlsCertificateError("Certificate not found.")
    return row


async def store_certificate(
    db: AsyncSession,
    parsed: ParsedCertificate,
    *,
    label: str,
    uploaded_by_user_id: int | None,
) -> dict[str, Any]:
    name = (label or "").strip() or parsed.subject or "TLS certificate"
    row = TlsCertificate(
        label=name[:128],
        cert_pem=parsed.cert_pem,
        key_pem_encrypted=encrypt_secret(parsed.key_pem),
        chain_pem=parsed.chain_pem or None,
        subject=parsed.subject[:512],
        sans_json=json.dumps(parsed.sans),
        issuer=parsed.issuer[:512],
        serial=parsed.serial[:128],
        not_before=parsed.not_before,
        not_after=parsed.not_after,
        sha256_fingerprint=parsed.fingerprint,
        key_algorithm=parsed.key_algorithm,
        key_bits=parsed.key_bits,
        is_active=False,
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.add(row)
    await db.flush()
    return _serialize(row, warnings=parsed.warnings)


async def delete_certificate(db: AsyncSession, cert_id: int) -> None:
    row = await get_certificate(db, cert_id)
    if row.is_active:
        raise TlsCertificateError("Deactivate HTTPS before deleting the active certificate.")
    await db.delete(row)
    await db.flush()


def decrypt_private_key(row: TlsCertificate) -> str:
    return decrypt_secret(row.key_pem_encrypted) or ""


def certificate_public_view(row: TlsCertificate, *, warnings: list[str] | None = None) -> dict[str, Any]:
    return _serialize(row, warnings=warnings)
