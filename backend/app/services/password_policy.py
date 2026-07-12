"""Centralized password policy for local accounts.

Applied on admin user-creation and password-reset. The bootstrap admin
password (set from ``ADMIN_PASSWORD`` env at startup) is intentionally NOT
validated — it is an operational bootstrap secret, not a user-chosen password,
and the production guard already rejects the known insecure default.
"""

from __future__ import annotations

from app.config import get_settings

# A small, opinionated blocklist of the most common passwords. Not exhaustive
# (this is not a password strength meter) — just a cheap floor to reject the
# very worst choices. The minimum length is the primary control.
_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password123",
        "123456",
        "12345678",
        "123456789",
        "qwerty",
        "qwerty123",
        "admin",
        "admin123",
        "letmein",
        "welcome",
        "welcome123",
        "changeme",
        "changeme123",
        "alpha-router",
        "alpha-router123",
        "iloveyou",
        "abc123",
        "00000000",
        "11111111",
    }
)


class PasswordPolicyError(ValueError):
    """Raised when a password fails the policy. ``str(exc)`` is user-facing."""


def validate_password(password: str | None) -> str:
    """Validate a password against the policy and return the trimmed password.

    Raises ``PasswordPolicyError`` with a user-facing message on failure.
    """
    pwd = (password or "").strip()
    min_len = max(8, int(getattr(get_settings(), "password_min_length", 8) or 8))
    if len(pwd) < min_len:
        raise PasswordPolicyError(f"Password must be at least {min_len} characters")
    if pwd.lower() in _COMMON_PASSWORDS:
        raise PasswordPolicyError("Password is too common; choose a stronger password")
    return pwd
