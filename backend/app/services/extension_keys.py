"""The key this installation signs its browser extension with.

Chrome and Edge derive an extension's ID from the public key it is signed with
(or, for an unpacked copy, from the ``key`` field of its manifest). Everything
that has to recognise *this server's* extension hangs off that ID: the connect
flow only hands an authorization code to ``chrome-extension://<id>/``, Group
Policy force-installs ``<id>;<update url>``, and a copy installed from the ZIP
and a copy installed by policy are the same extension only if they share it.

So each installation creates one RSA key the first time it is needed and keeps
it for good, encrypted with ``DATA_ENCRYPTION_KEY`` in ``system_settings``
(database backups carry it). A stored key that cannot be read - the encryption
key changed, or the row was edited - is an error, never a reason to make a new
one: a new key is a new ID, and every copy already installed would stop being
this server's extension.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.system import SystemSetting
from app.services.secret_crypto import decrypt_secret, encrypt_typed_secret

KEY_SETTING = "extension.signing_key"
_KEY_BITS = 2048


class ExtensionKeyUnavailable(RuntimeError):
    """The stored signing key exists but cannot be used."""


def extension_id_from_public_key(public_der: bytes) -> str:
    """Chromium's extension ID: the first 128 bits of SHA-256(SPKI), one letter a-p per nibble."""
    digest = hashlib.sha256(public_der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(nibble, 16)) for nibble in digest)


@dataclass(frozen=True)
class ExtensionKey:
    private_key: rsa.RSAPrivateKey
    #: DER-encoded SubjectPublicKeyInfo: what a CRX header carries and what
    #: the manifest ``key`` field holds (base64).
    public_der: bytes

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_der).decode("ascii")

    @property
    def extension_id(self) -> str:
        return extension_id_from_public_key(self.public_der)


#: Parsed keys by their stored ciphertext. Keyed by the value rather than held
#: as one global, so a different database (a test, a restore) is never served
#: a key it does not hold.
_parsed: dict[str, ExtensionKey] = {}


def _from_private_key(private_key: rsa.RSAPrivateKey) -> ExtensionKey:
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return ExtensionKey(private_key=private_key, public_der=public_der)


def _parse(stored: str | None) -> ExtensionKey:
    if not stored:
        raise ExtensionKeyUnavailable("The browser extension signing key is empty.")
    cached = _parsed.get(stored)
    if cached is not None:
        return cached
    try:
        pem = decrypt_secret(stored)
        private_key = serialization.load_pem_private_key((pem or "").encode("ascii"), password=None)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ExtensionKeyUnavailable(
            "The browser extension signing key cannot be read. DATA_ENCRYPTION_KEY may have changed; "
            "restore the key it was encrypted with."
        ) from exc
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ExtensionKeyUnavailable("The browser extension signing key is not an RSA key.")
    key = _from_private_key(private_key)
    _parsed[stored] = key
    return key


async def _stored_value(db: AsyncSession) -> tuple[bool, str | None]:
    """(whether the row exists, its value)."""
    row = await db.get(SystemSetting, KEY_SETTING)
    if row is None:
        return False, None
    return True, cast("str | None", row.value)


async def get_signing_key(db: AsyncSession) -> ExtensionKey | None:
    """The key if one has been created; None before the first use."""
    exists, value = await _stored_value(db)
    if not exists:
        return None
    return _parse(value)


async def _create() -> ExtensionKey:
    """Create and commit a key in a session of its own.

    Committed on its own because the key may be handed out (a download, a
    CRX) before the request's own transaction ends, and a rollback must not
    take away a key a browser already holds. Two first requests at once both
    try the insert; the loser reads the winner's key instead.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_BITS)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    stored = encrypt_typed_secret(pem)
    async with AsyncSessionLocal() as session:
        session.add(SystemSetting(key=KEY_SETTING, value=stored))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = await session.get(SystemSetting, KEY_SETTING)
            return _parse(cast("str | None", existing.value) if existing is not None else None)
    key = _from_private_key(private_key)
    _parsed[stored] = key
    return key


async def load_or_create_signing_key(db: AsyncSession) -> ExtensionKey:
    """This installation's key, created on first use; raises if the stored one is unreadable."""
    exists, value = await _stored_value(db)
    if exists:
        return _parse(value)
    return await _create()
