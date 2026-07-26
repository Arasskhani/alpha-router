"""TOTP (authenticator) helpers for local-account 2FA."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import secrets
from typing import Any

from app.core.security import verify_password
from app.services.secret_crypto import decrypt_secret, encrypt_secret

logger = logging.getLogger("alpha_router.security.settings")

_ISSUER = "Alpha Router"
_BACKUP_COUNT = 8


def is_local_user(user: Any) -> bool:
    return (getattr(user, "auth_provider", None) or "local") == "local"


def generate_totp_secret() -> str:
    import pyotp

    return pyotp.random_base32()


def encrypt_totp_secret(secret: str) -> str:
    return encrypt_secret(secret)


def decrypt_totp_secret(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    return decrypt_secret(ciphertext)


def provisioning_uri(secret: str, username: str) -> str:
    import pyotp

    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=_ISSUER)


def verify_totp_code(secret: str, code: str, *, valid_window: int = 1) -> bool:
    import pyotp

    cleaned = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(cleaned) < 6:
        return False
    totp = pyotp.TOTP(secret)
    return bool(totp.verify(cleaned, valid_window=valid_window))


def qr_png_base64(otpauth_uri: str) -> str | None:
    """Return a base64 PNG QR for the otpauth URI, or None if qrcode is unavailable."""
    try:
        import qrcode
    except Exception:
        logger.warning("qrcode package unavailable; returning secret URI only")
        return None
    try:
        img = qrcode.make(otpauth_uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        logger.exception("Failed to render TOTP QR code")
        return None


def generate_backup_codes() -> list[str]:
    codes: list[str] = []
    for _ in range(_BACKUP_COUNT):
        codes.append(secrets.token_hex(4))
    return codes


def hash_backup_codes(codes: list[str]) -> list[str]:
    """Hash backup codes for storage. Uses SHA-256 of normalized code (fast + one-time)."""
    out: list[str] = []
    for code in codes:
        normalized = str(code).strip().lower().replace(" ", "")
        out.append(hashlib.sha256(normalized.encode("utf-8")).hexdigest())
    return out


def consume_backup_code(stored_hashes: list[str] | None, code: str) -> list[str] | None:
    """Return remaining hashes if ``code`` matches one entry; else None."""
    if not stored_hashes:
        return None
    normalized = str(code or "").strip().lower().replace(" ", "")
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    remaining = list(stored_hashes)
    try:
        remaining.remove(digest)
    except ValueError:
        return None
    return remaining


def verify_password_for_user(user: Any, password: str) -> bool:
    hashed = getattr(user, "hashed_password", None)
    if not hashed:
        return False
    return verify_password(password, hashed)


def audit(event: str, *, username: str, detail: str = "") -> None:
    logger.info("settings_audit event=%s user=%s %s", event, username, detail)
