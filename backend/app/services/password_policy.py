"""Centralized password policy for local accounts.

One policy for every password a person or an administrator chooses: creating
a user, an administrator's reset, changing one's own password in Settings,
self sign-up by email and resetting a forgotten password by email. The rules:

- at least ``password_min_length`` characters (never fewer than 8);
- an uppercase letter, a lowercase letter, a digit and a symbol;
- not one of the most common passwords;
- not containing the account's username or the name part of its email.

A password set before a rule existed keeps working: the policy applies when a
password is chosen, not when one is used to sign in.

The bootstrap admin password (set from ``ADMIN_PASSWORD`` env at startup) is
intentionally NOT validated — it is an operational bootstrap secret, not a
user-chosen password, and the production guard already rejects the known
insecure default.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings

# A small, opinionated blocklist of the most common passwords. Not exhaustive
# (this is not a password strength meter) — just a cheap floor to reject the
# very worst choices. Length and the character classes are the primary controls.
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

#: A personal word shorter than this is not looked for (a two-letter username
#: would forbid half the dictionary).
_PERSONAL_MIN_CHARS = 3


class PasswordPolicyError(ValueError):
    """Raised when a password fails the policy. ``str(exc)`` is user-facing."""


@dataclass(frozen=True)
class PasswordRule:
    key: str
    label: str


def min_length() -> int:
    return max(8, int(getattr(get_settings(), "password_min_length", 8) or 8))


def password_rules() -> list[PasswordRule]:
    """The rules in the order the sign-up and reset forms show them."""
    return [
        PasswordRule("length", f"At least {min_length()} characters"),
        PasswordRule("upper", "An uppercase letter (A-Z)"),
        PasswordRule("lower", "A lowercase letter (a-z)"),
        PasswordRule("digit", "A digit (0-9)"),
        PasswordRule("symbol", "A symbol, such as ! @ # $ % - _"),
        PasswordRule("personal", "Not your username or the name in your email"),
    ]


def _is_symbol(ch: str) -> bool:
    return not ch.isalnum() and not ch.isspace()


def _personal_words(username: str | None, email: str | None) -> list[str]:
    words: list[str] = []
    for value in (username, (email or "").split("@", 1)[0] if email else None):
        word = (value or "").strip().casefold()
        if len(word) >= _PERSONAL_MIN_CHARS:
            words.append(word)
    return words


def unmet_rules(password: str | None, *, username: str | None = None, email: str | None = None) -> list[str]:
    """The keys of the rules ``password`` does not meet, in rule order (not the common-password check)."""
    pwd = (password or "").strip()
    unmet: list[str] = []
    if len(pwd) < min_length():
        unmet.append("length")
    if not any(ch.isupper() for ch in pwd):
        unmet.append("upper")
    if not any(ch.islower() for ch in pwd):
        unmet.append("lower")
    if not any(ch.isdigit() for ch in pwd):
        unmet.append("digit")
    if not any(_is_symbol(ch) for ch in pwd):
        unmet.append("symbol")
    folded = pwd.casefold()
    if any(word in folded for word in _personal_words(username, email)):
        unmet.append("personal")
    return unmet


_MISSING_WORDS = {
    "upper": "an uppercase letter",
    "lower": "a lowercase letter",
    "digit": "a digit",
    "symbol": "a symbol",
}


def _join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def validate_password(password: str | None, *, username: str | None = None, email: str | None = None) -> str:
    """Validate a password against the policy and return the trimmed password.

    ``username`` and ``email`` are the account's, when known: the password may
    not contain either. Raises ``PasswordPolicyError`` with a user-facing
    message on failure.
    """
    pwd = (password or "").strip()
    least = min_length()
    if len(pwd) < least:
        raise PasswordPolicyError(f"Password must be at least {least} characters")
    if pwd.lower() in _COMMON_PASSWORDS:
        raise PasswordPolicyError("Password is too common; choose a stronger password")
    unmet = unmet_rules(pwd, username=username, email=email)
    missing = [_MISSING_WORDS[key] for key in unmet if key in _MISSING_WORDS]
    if missing:
        raise PasswordPolicyError(f"Password must include {_join(missing)}")
    if "personal" in unmet:
        raise PasswordPolicyError("Password must not contain your username or the name part of your email")
    return pwd
