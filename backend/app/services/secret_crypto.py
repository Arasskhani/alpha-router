"""Symmetric encryption for secrets stored at rest (Phase 3).

The application stores upstream provider API keys, SMTP passwords, and LDAP /
Keycloak bind credentials in the database. Previously these were saved as
plaintext despite the ``*_encrypted`` column names. This module provides the
single encryption/decryption primitive used by every read/write site.

Threat model
------------
Anyone with read access to the database (SQL injection, a leaked ``pg_dump``,
an over-permissive read replica) must NOT be able to recover the raw secrets.
The Fernet key is derived from ``SECRET_KEY`` via PBKDF2-HMAC-SHA256, so an
attacker also needs ``SECRET_KEY`` to decrypt. That is the same trust root
already used for JWT signing — if ``SECRET_KEY`` is compromised the attacker
can forge tokens anyway, so no new trust root is introduced.

Backward compatibility
----------------``decrypt_secret`` accepts both ciphertext (new) and plaintext (legacy rows
written before Phase 3). It returns plaintext values unchanged, which lets the
startup migration encrypt existing rows incrementally and re-run safely. The
same fallback means a value that cannot be decrypted (e.g. after a
``SECRET_KEY`` rotation that did not re-encrypt) is returned as-is rather than
raising — the caller will then fail at the upstream provider with a clear
auth error instead of crashing the request path.
"""

from __future__ import annotations

import base64
import re

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import get_settings

# Fixed salt. A random salt would be more ideal, but a fixed salt is safe here
# because the input (SECRET_KEY) is already a high-entropy secret, and a fixed
# salt lets us derive the same Fernet key on every boot without persisting it.
_SALT = b"nitro-at-rest-secret-encryption-v1"
_KDF_ITERATIONS = 480_000  # OWASP 2023 guidance for PBKDF2-HMAC-SHA256

# Fernet tokens are base64url and begin with the version byte 0x80, which
# base64-encodes to "gAAAAAB". We use this as a cheap, robust detector.
_FERNET_PREFIX = "gAAAAAB"
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def _derive_fernet_key() -> bytes:
    secret = (get_settings().secret_key or "").encode("utf-8")
    if not secret:
        raise RuntimeError("SECRET_KEY is not configured; cannot derive data encryption key.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=_KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret))


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_derive_fernet_key())
    return _fernet


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
    """Encrypt a secret. Empty/None input is returned unchanged.

    Idempotent: if the value already looks like ciphertext it is returned as-is,
    so calling this on a row that is already encrypted (e.g. during a re-run of
    the startup migration) does not double-encrypt.
    """
    if not plaintext:
        return plaintext or ""
    if is_encrypted(plaintext):
        return plaintext
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a secret, returning plaintext for any value that is not ciphertext.

    This fallback is intentional and load-bearing:

    * During the migration window, rows that have not yet been encrypted are
      still plaintext and must keep working.
    * If ``SECRET_KEY`` is rotated without re-encrypting, the value cannot be
      decrypted; returning it as-is lets the upstream provider reject it with a
      clear auth error rather than crashing the request.

    ``None``/empty are returned as-is so callers that store optional secrets
    keep seeing ``None`` (e.g. SMTP when not configured).
    """
    if not value:
        return value
    if not is_encrypted(value):
        return value
    try:
        return _get_fernet().decrypt(value.encode("ascii")).decode("utf-8")
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
    """Test hook: clear the cached Fernet instance after changing SECRET_KEY."""
    global _fernet
    _fernet = None
