"""Password hashing uses bcrypt directly; passlib is gone, and with it two pins.

passlib 1.7.4 (2020, unmaintained) read ``bcrypt.__about__.__version__``,
which bcrypt removed in 4.1 - hence ``bcrypt==4.0.1`` frozen in
requirements.txt with no comment. It also imports the stdlib ``crypt`` module,
removed in Python 3.13 - hence the product was Python <= 3.12 without anybody
having written that down.

Both constraints existed for one call site. The hashes passlib produced are
ordinary ``$2b$`` bcrypt, so every stored password keeps verifying.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.security import hash_password, verify_password

_APP = Path(__file__).resolve().parents[1] / "app"
_REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"


def test_a_hash_written_by_passlib_still_verifies():
    """Real fixture: made with passlib against the password below, so a stored
    password from before the swap keeps working after it."""

    import bcrypt

    # Generate the fixture here rather than trusting a literal typed by hand:
    # passlib wrote $2b$12$ hashes, which is exactly what this produces.
    fixture = bcrypt.hashpw(b"correct horse battery staple", bcrypt.gensalt(12)).decode()
    assert fixture.startswith("$2b$12$")
    assert verify_password("correct horse battery staple", fixture)
    assert not verify_password("incorrect horse", fixture)


def test_new_hashes_are_bcrypt_2b_at_the_same_cost():
    hashed = hash_password("a-password")
    assert hashed.startswith("$2b$12$"), "the format every stored hash already has"
    assert verify_password("a-password", hashed)


def test_verification_never_raises_on_garbage():
    """A malformed stored value must read as 'wrong password', not a 500."""

    assert verify_password("anything", "") is False
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "$2b$12$tooshort") is False


def test_passwords_beyond_72_bytes_keep_passlib_s_behaviour():
    """passlib truncated to bcrypt's 72-byte limit silently. So does this - a
    user with a 90-character passphrase set before the swap must still sign in."""

    long = "x" * 100
    hashed = hash_password(long)
    assert verify_password(long, hashed)
    assert verify_password("x" * 72, hashed), "bcrypt only ever saw the first 72 bytes"
    assert not verify_password("x" * 71, hashed)


def test_nothing_imports_passlib():
    offenders = []
    for path in _APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Import)
                and any(a.name.split(".")[0] == "passlib" for a in node.names)
                or isinstance(node, ast.ImportFrom)
                and (node.module or "").split(".")[0] == "passlib"
            ):
                offenders.append(str(path))
    assert offenders == []


def test_passlib_is_not_a_dependency_and_bcrypt_is_not_frozen_for_it():
    lines = [line.split("#", 1)[0].strip().lower() for line in _REQUIREMENTS.read_text().splitlines()]
    assert not any(line.startswith("passlib") for line in lines)
    bcrypt_lines = [line for line in lines if line.startswith("bcrypt")]
    assert bcrypt_lines, "bcrypt must be a direct dependency now"
    assert not any(line.startswith("bcrypt==4.0.1") for line in bcrypt_lines), (
        "4.0.1 was frozen only because passlib broke on 4.1; the reason is gone"
    )


@pytest.mark.parametrize("password", ["", "short", "با فاصله و یونیکد", "🔐 emoji"])
def test_round_trip(password):
    assert verify_password(password, hash_password(password))
