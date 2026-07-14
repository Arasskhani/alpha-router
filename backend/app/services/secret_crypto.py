"""Symmetric encryption for secrets stored at rest (Phase 3, Phase 9 rotation).

The application stores upstream provider API keys, SMTP passwords, and LDAP /
Keycloak bind credentials in the database. Previously these were saved as
plaintext despite the ``*_encrypted`` column names. This module provides the
single encryption/decryption primitive used by every read/write site.

Threat model
------------
Anyone with read access to the database (SQL injection, a leaked ``pg_dump``,
an over-permissive read replica) must NOT be able to recover the raw secrets.
The Fernet key is derived via PBKDF2-HMAC-SHA256 from a high-entropy secret, so
an attacker also needs that secret to decrypt.

Key split (Phase 9)
-------------------
The primary key is derived from ``DATA_ENCRYPTION_KEY`` when set. When it is
empty, the primary key falls back to the legacy key derived from ``SECRET_KEY``
— preserving backward compatibility for existing deployments. ``decrypt_secret``
tries the primary key first, then the legacy key, so ciphertext written before
rotation keeps working until the re-encryption migration rewrites it with the
primary key.

Backward compatibility
----------------------
``decrypt_secret`` accepts both ciphertext (new) and plaintext (legacy rows
written before Phase 3). It returns plaintext values unchanged, which lets the
startup migration encrypt existing rows incrementally and re-run safely. The
same fallback means a value that cannot be decrypted (e.g. after a key rotation
that did not re-encrypt) is returned as-is rather than raising — the caller will
then fail at the upstream provider with a clear auth error instead of crashing
the request path.
"""

from __future__ import annotations

import base64
import re

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import get_settings

# Fixed salts. A random salt would be more ideal, but a fixed salt is safe here
# because the inputs (SECRET_KEY / DATA_ENCRYPTION_KEY) are already high-entropy
# secrets, and a fixed salt lets us derive the same Fernet key on every boot
# without persisting it. The data key uses a distinct salt so that even if an
# operator reuses the same value for both settings the derived keys differ.
_LEGACY_SALT = b"alpha-router-at-rest-secret-encryption-v1"
_DATA_SALT = b"alpha-router-at-rest-data-encryption-v2"
_KDF_ITERATIONS = 480_000  # OWASP 2023 guidance for PBKDF2-HMAC-SHA256

# Fernet tokens are base64url and begin with the version byte 0x80, which
# base64-encodes to "gAAAAAB". We use this as a cheap, robust detector.
_FERNET_PREFIX = "gAAAAAB"
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def _derive_key(secret: str, salt: bytes) -> bytes:
    if not secret:
        raise RuntimeError("Encryption secret is not configured; cannot derive key.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


def _legacy_fernet_key() -> bytes:
    secret = get_settings().secret_key or ""
    if not secret:
        raise RuntimeError("SECRET_KEY is not configured; cannot derive legacy data encryption key.")
    return _derive_key(secret, _LEGACY_SALT)


def _primary_fernet_key() -> bytes:
    data_key = (get_settings().data_encryption_key or "").strip()
    if data_key:
        return _derive_key(data_key, _DATA_SALT)
    # No dedicated data key: preserve the pre-Phase-9 behavior exactly.
    return _legacy_fernet_key()


_primary_fernet: Fernet | None = None
_legacy_fernet: Fernet | None = None


def _get_primary_fernet() -> Fernet:
    global _primary_fernet
    if _primary_fernet is None:
        _primary_fernet = Fernet(_primary_fernet_key())
    return _primary_fernet


def _get_legacy_fernet() -> Fernet:
    global _legacy_fernet
    if _legacy_fernet is None:
        _legacy_fernet = Fernet(_legacy_fernet_key())
    return _legacy_fernet


def is_encrypted(value: str | None) -> bool:
    """Heuristic: True if ``value`` looks like a Fernet ciphertext token."""
    if not value:
        return False
    v = value.strip()
    return (
        v.startswith(_FERNET_PREFIX)
        and len(v) >= 80
        and " " not in v
        and _BASE64URL_RE.match(v) is not None
    )


def encrypt_secret(plaintext: str | None) -> str:
    """Encrypt a secret with the primary key. Empty/None input is returned unchanged.

    Idempotent: if the value already looks like ciphertext it is returned as-is,
    so calling this on a row that is already encrypted (e.g. during a re-run of
    the startup migration) does not double-encrypt.
    """
    if not plaintext:
        return plaintext or ""
    if is_encrypted(plaintext):
        return plaintext
    return _get_primary_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a secret, returning plaintext for any value that is not ciphertext.

    Tries the primary key first, then the legacy key (so pre-rotation ciphertext
    keeps working during the Phase 9 migration window). This fallback is
    intentional and load-bearing:

    * During the migration window, rows that have not yet been re-encrypted are
      still ciphertext under the legacy key and must keep working.
    * If the key is rotated without re-encrypting, the value cannot be
      decrypted; returning it as-is lets the upstream provider reject it with a
      clear auth error rather than crashing the request.

    ``None``/empty are returned as-is so callers that store optional secrets
    keep seeing ``None`` (e.g. SMTP when not configured).
    """
    if not value:
        return value
    if not is_encrypted(value):
        return value
    token = value.encode("ascii")
    try:
        return _get_primary_fernet().decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError):
        pass
    # Legacy key fallback (no-op when primary == legacy, i.e. no DATA_ENCRYPTION_KEY).
    try:
        return _get_legacy_fernet().decrypt(token).decode("utf-8")
    except (InvalidToken, ValueError):
        return value


def mask_secret(value: str | None, visible_tail: int = 4) -> str:
    """Decrypt-then-mask, for display in admin UIs. Returns ``""`` if empty."""
    plain = decrypt_secret(value)
    if not plain:
        return ""
    if len(plain) <= visible_tail:
        return "*" * len(plain)
    return "*" * visible_tail + plain[-visible_tail:]


def reset_fernet_cache() -> None:
    """Test hook: clear cached Fernet instances after changing key settings."""
    global _primary_fernet, _legacy_fernet
    _primary_fernet = None
    _legacy_fernet = None
