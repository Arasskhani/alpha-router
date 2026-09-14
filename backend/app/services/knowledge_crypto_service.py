"""Application-layer encryption for Knowledge source bytes and chunk text."""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import get_settings

_BINARY_MAGIC = b"AKN1"
_TEXT_PREFIX = "enc:v1:"
_NONCE_BYTES = 12


@lru_cache(maxsize=1)
def _key() -> bytes:
    secret = get_settings().data_encryption_key
    if not secret:
        raise RuntimeError("DATA_ENCRYPTION_KEY is required for Knowledge encryption")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"Alpharouter Knowledge",
        info=b"knowledge-envelope-v1",
    ).derive(secret.encode("utf-8"))


def encrypt_bytes(plaintext: bytes, *, associated_data: str) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(
        nonce,
        plaintext,
        associated_data.encode("utf-8"),
    )
    return _BINARY_MAGIC + nonce + ciphertext


def decrypt_bytes(envelope: bytes, *, associated_data: str) -> bytes:
    minimum = len(_BINARY_MAGIC) + _NONCE_BYTES + 16
    if len(envelope) < minimum or not envelope.startswith(_BINARY_MAGIC):
        raise ValueError("Invalid Knowledge encryption envelope")
    nonce_start = len(_BINARY_MAGIC)
    nonce = envelope[nonce_start : nonce_start + _NONCE_BYTES]
    ciphertext = envelope[nonce_start + _NONCE_BYTES :]
    return AESGCM(_key()).decrypt(
        nonce,
        ciphertext,
        associated_data.encode("utf-8"),
    )


def encrypt_text(plaintext: str, *, associated_data: str) -> str:
    envelope = encrypt_bytes(
        plaintext.encode("utf-8"),
        associated_data=associated_data,
    )
    return _TEXT_PREFIX + base64.urlsafe_b64encode(envelope).decode("ascii")


def decrypt_text(envelope: str, *, associated_data: str) -> str:
    if not envelope.startswith(_TEXT_PREFIX):
        raise ValueError("Unencrypted Knowledge chunk content is not accepted")
    raw = base64.b64decode(
        envelope[len(_TEXT_PREFIX) :].encode("ascii"),
        altchars=b"-_",
        validate=True,
    )
    return decrypt_bytes(raw, associated_data=associated_data).decode("utf-8")


def plaintext_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk_plaintext_hash(chunk_index: int, text: str) -> str:
    """Stable integrity digest for a Knowledge chunk.

    Includes ``chunk_index`` so duplicate texts in one document remain unique
    under ``uq_knowledge_chunks_hash`` while still binding the stored ciphertext
    to its plaintext.
    """
    return hashlib.sha256(f"{int(chunk_index)}\0{text}".encode()).hexdigest()
