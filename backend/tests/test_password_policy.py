"""Tests for the centralized password policy."""

import pytest

from app.services.password_policy import (
    PasswordPolicyError,
    validate_password,
)


def test_validate_password_accepts_long_enough():
    assert validate_password("aStrong-1Pass!") == "aStrong-1Pass!"


def test_validate_password_rejects_short():
    with pytest.raises(PasswordPolicyError) as exc:
        validate_password("abc123")
    assert "at least" in str(exc.value)


def test_validate_password_rejects_empty():
    with pytest.raises(PasswordPolicyError):
        validate_password("")
    with pytest.raises(PasswordPolicyError):
        validate_password(None)
    with pytest.raises(PasswordPolicyError):
        validate_password("   ")


def test_validate_password_rejects_common():
    # All entries here are >= PASSWORD_MIN_LENGTH so the length check passes
    # and the common-password check is what actually fires.
    for bad in ("password", "Password123", "password123", "qwerty123", "admin123", "changeme", "nitro123", "00000000"):
        with pytest.raises(PasswordPolicyError) as exc:
            validate_password(bad)
        assert "too common" in str(exc.value), f"{bad!r} did not trigger common-password rejection"


def test_validate_password_trims_whitespace():
    assert validate_password("  aStrong-1Pass!  ") == "aStrong-1Pass!"
