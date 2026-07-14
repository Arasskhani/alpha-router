"""Phase 9 — DATA_ENCRYPTION_KEY split with legacy fallback.

Verifies the multi-key reader: new ciphertext is encrypted with the dedicated
data key, legacy ciphertext (encrypted under SECRET_KEY) still decrypts via the
fallback, and a value that cannot be decrypted under either key is returned
as-is rather than raising.
"""

import pytest

from app.config import get_settings
from app.services.secret_crypto import (
    decrypt_secret,
    encrypt_secret,
    is_encrypted,
    reset_fernet_cache,
)


@pytest.fixture(autouse=True)
def _reset_caches():
    reset_fernet_cache()
    yield
    reset_fernet_cache()


def _set_keys(monkeypatch, *, secret_key: str, data_key: str = ""):
    settings = get_settings()
    monkeypatch.setattr(settings, "secret_key", secret_key)
    monkeypatch.setattr(settings, "data_encryption_key", data_key)
    reset_fernet_cache()


def test_encrypt_uses_data_key_when_set(monkeypatch):
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="dedicated-data-key")
    cipher = encrypt_secret("sk-or-v1-12345")
    assert is_encrypted(cipher)
    assert decrypt_secret(cipher) == "sk-or-v1-12345"


def test_legacy_ciphertext_decrypts_via_fallback(monkeypatch):
    # Encrypt under the legacy key (no DATA_ENCRYPTION_KEY).
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="")
    legacy_cipher = encrypt_secret("sk-or-v1-legacy-value")

    # Now rotate to a dedicated data key. The legacy ciphertext must still
    # decrypt via the fallback key (derived from SECRET_KEY).
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="new-data-key")
    assert decrypt_secret(legacy_cipher) == "sk-or-v1-legacy-value"


def test_new_ciphertext_not_decryptable_with_only_legacy_key(monkeypatch):
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="dedicated-data-key")
    cipher = encrypt_secret("sk-or-v1-rotated-value")

    # Simulate removing the data key (e.g. rollback to legacy-only). The primary
    # key is now the legacy key; the data-key ciphertext cannot be decrypted and
    # is returned as-is so the caller fails clearly instead of crashing.
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="")
    assert decrypt_secret(cipher) == cipher


def test_no_data_key_preserves_pre_phase9_behavior(monkeypatch):
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="")
    cipher = encrypt_secret("sk-or-v1-same-as-before")
    assert decrypt_secret(cipher) == "sk-or-v1-same-as-before"


def test_distinct_keys_produce_distinct_ciphertext(monkeypatch):
    plain = "sk-or-v1-same-plaintext"
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="")
    legacy_cipher = encrypt_secret(plain)
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="dedicated-data-key")
    data_cipher = encrypt_secret(plain)
    assert legacy_cipher != data_cipher
    assert decrypt_secret(legacy_cipher) == plain
    assert decrypt_secret(data_cipher) == plain


def test_invalid_ciphertext_returned_as_is(monkeypatch):
    _set_keys(monkeypatch, secret_key="legacy-secret", data_key="dedicated-data-key")
    bogus = "gAAAAABm" + "A" * 90  # looks like a token but won't decrypt under any key
    assert decrypt_secret(bogus) == bogus
