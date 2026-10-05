"""Tests for the centralized password policy: length, character classes, common and personal words."""

import pytest

from app.services.password_policy import (
    PasswordPolicyError,
    password_rules,
    unmet_rules,
    validate_password,
)


def test_validate_password_accepts_a_complex_one():
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
    for bad in (
        "password",
        "Password123",
        "password123",
        "qwerty123",
        "admin123",
        "changeme",
        "alpha-router123",
        "00000000",
    ):
        with pytest.raises(PasswordPolicyError) as exc:
            validate_password(bad)
        assert "too common" in str(exc.value), f"{bad!r} did not trigger common-password rejection"


def test_validate_password_trims_whitespace():
    assert validate_password("  aStrong-1Pass!  ") == "aStrong-1Pass!"


@pytest.mark.parametrize(
    ("password", "missing"),
    [
        ("alllowercase1!", "an uppercase letter"),
        ("ALLUPPERCASE1!", "a lowercase letter"),
        ("NoDigitsHere!!", "a digit"),
        ("NoSymbols1234", "a symbol"),
        ("onlyletterslong", "an uppercase letter, a digit and a symbol"),
    ],
)
def test_each_character_class_is_required_and_named(password, missing):
    with pytest.raises(PasswordPolicyError) as exc:
        validate_password(password)
    assert str(exc.value) == f"Password must include {missing}"


def test_a_space_is_not_a_symbol():
    with pytest.raises(PasswordPolicyError):
        validate_password("Has Spaces 123")


def test_the_username_or_email_name_may_not_be_in_it():
    with pytest.raises(PasswordPolicyError) as exc:
        validate_password("Sara.Ahmadi-2026!", username="sara.ahmadi")
    assert "username" in str(exc.value)
    with pytest.raises(PasswordPolicyError):
        validate_password("Xmajid!2026Q", email="Majid@example.com")
    # A short username is not looked for: it would forbid too much.
    assert validate_password("Abc-def-123!", username="ab") == "Abc-def-123!"


def test_unmet_rules_lists_what_is_missing_in_order():
    assert unmet_rules("abc") == ["length", "upper", "digit", "symbol"]
    assert unmet_rules("aStrong-1Pass!") == []
    assert unmet_rules("Sara-Pass-123!", username="sara") == ["personal"]


def test_the_rules_the_forms_show():
    assert [rule.key for rule in password_rules()] == ["length", "upper", "lower", "digit", "symbol", "personal"]
    assert password_rules()[0].label == "At least 8 characters"
