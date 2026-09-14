"""Symmetric encryption for secrets stored at rest.

All persisted provider credentials, SMTP passwords, and TOTP secrets use one
Fernet key derived from ``DATA_ENCRYPTION_KEY``.  Greenfield
deployments intentionally have no plaintext reader, alternate salt, or
historical-key fallback: undecryptable stored values fail closed.
"""

from __future__ import annotations

import base64
import re

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import get_settings

_FERNET_SALT = b"alpha-router-at-rest-encryption-v1"
_KDF_ITERATIONS = 480_000
_FERNET_PREFIX = "gAAAAAB"
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def _derive_key(secret: str) -> bytes:
    if not secret:
        raise RuntimeError("DATA_ENCRYPTION_KEY is not configured; cannot encrypt stored secrets.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_FERNET_SALT,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        secret = (get_settings().data_encryption_key or "").strip()
        _fernet = Fernet(_derive_key(secret))
    return _fernet


def is_encrypted(value: str | None) -> bool:
    """Return whether a value has the structural shape of a Fernet token."""
    if not value:
        return False
    candidate = value.strip()
    return (
        candidate.startswith(_FERNET_PREFIX)
        and len(candidate) >= 80
        and " " not in candidate
        and _BASE64URL_RE.match(candidate) is not None
    )


def _decrypt_token(value: str) -> str:
    try:
        return _get_fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ValueError("Stored secret cannot be decrypted with DATA_ENCRYPTION_KEY.") from exc


def encrypt_secret(plaintext: str | None) -> str:
    """Encrypt plaintext, validating current ciphertext before preserving it."""
    if not plaintext:
        return plaintext or ""
    if is_encrypted(plaintext):
        _decrypt_token(plaintext)
        return plaintext
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt current ciphertext and reject plaintext or malformed stored data."""
    if not value:
        return value
    if not is_encrypted(value):
        raise ValueError("Stored secret is not encrypted.")
    return _decrypt_token(value)


def mask_secret(value: str | None, visible_tail: int = 4) -> str:
    """Decrypt and mask a stored secret for admin display."""
    plain = decrypt_secret(value)
    if not plain:
        return ""
    if len(plain) <= visible_tail:
        return "*" * len(plain)
    return "*" * visible_tail + plain[-visible_tail:]


def reset_fernet_cache() -> None:
    """Clear the cached Fernet instance after test configuration changes."""
    global _fernet
    _fernet = None
