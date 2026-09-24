"""The installation's browser extension signing key.

The key decides the extension's ID, and the ID is what the connect flow, Group
Policy and every installed copy recognise. So: made once, kept encrypted, and
never replaced behind anybody's back.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization

from app.models.system import SystemSetting
from app.services import extension_keys
from app.services.extension_keys import (
    KEY_SETTING,
    ExtensionKeyUnavailable,
    extension_id_from_public_key,
    get_signing_key,
    load_or_create_signing_key,
)
from app.services.secret_crypto import decrypt_secret


@pytest.fixture(autouse=True)
def _own_session_on_the_test_engine(monkeypatch, session_factory):
    monkeypatch.setattr(extension_keys, "AsyncSessionLocal", session_factory)


async def _stored(session_factory) -> str | None:
    async with session_factory() as session:
        row = await session.get(SystemSetting, KEY_SETTING)
        return None if row is None else row.value


def _nibble_letters(public_der: bytes) -> str:
    """The same ID computed another way: byte by byte, high nibble first."""
    out = []
    for byte in hashlib.sha256(public_der).digest()[:16]:
        out.append("abcdefghijklmnop"[byte >> 4])
        out.append("abcdefghijklmnop"[byte & 0x0F])
    return "".join(out)


class TestTheFirstUse:
    async def test_there_is_no_key_before_it_is_needed(self, db_session):
        assert await get_signing_key(db_session) is None

    async def test_it_is_created_once_and_reused(self, db_session, session_factory):
        first = await load_or_create_signing_key(db_session)
        second = await load_or_create_signing_key(db_session)
        assert first.extension_id == second.extension_id
        assert (await get_signing_key(db_session)).extension_id == first.extension_id

    async def test_it_is_stored_encrypted(self, db_session, session_factory):
        key = await load_or_create_signing_key(db_session)
        stored = await _stored(session_factory)
        assert stored and stored.startswith("gAAAAAB")
        assert "PRIVATE KEY" not in stored
        pem = decrypt_secret(stored)
        assert pem.startswith("-----BEGIN PRIVATE KEY-----")
        loaded = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
        assert loaded.key_size == 2048
        assert (
            loaded.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            == key.public_der
        )


class TestTheId:
    async def test_it_is_what_chromium_derives_from_the_public_key(self, db_session):
        key = await load_or_create_signing_key(db_session)
        assert len(key.extension_id) == 32
        assert set(key.extension_id) <= set("abcdefghijklmnop")
        assert key.extension_id == _nibble_letters(key.public_der)

    def test_a_known_digest_maps_to_known_letters(self):
        # SHA-256(b"") starts e3b0c44298fc1c149afbf4c8996fb924: e->o, 3->d, b->l, 0->a, c->m, ...
        assert extension_id_from_public_key(b"") == "odlameecjipmbmbejkplpemijjgpljce"

    async def test_the_manifest_key_is_the_public_key_in_base64(self, db_session):
        key = await load_or_create_signing_key(db_session)
        assert base64.b64decode(key.public_key_b64) == key.public_der


class TestAKeyThatCannotBeRead:
    async def _put(self, session_factory, value: str) -> None:
        async with session_factory() as session:
            session.add(SystemSetting(key=KEY_SETTING, value=value))
            await session.commit()

    async def test_one_encrypted_with_another_key_is_an_error_and_is_kept(self, db_session, session_factory):
        foreign = Fernet(Fernet.generate_key()).encrypt(b"-----BEGIN PRIVATE KEY-----").decode("ascii")
        await self._put(session_factory, foreign)
        with pytest.raises(ExtensionKeyUnavailable, match="DATA_ENCRYPTION_KEY"):
            await load_or_create_signing_key(db_session)
        assert await _stored(session_factory) == foreign

    async def test_an_emptied_row_is_an_error_and_is_kept(self, db_session, session_factory):
        await self._put(session_factory, "")
        with pytest.raises(ExtensionKeyUnavailable):
            await load_or_create_signing_key(db_session)
        with pytest.raises(ExtensionKeyUnavailable):
            await get_signing_key(db_session)
        assert await _stored(session_factory) == ""


class TestTwoFirstRequestsAtOnce:
    async def test_the_loser_uses_the_winners_key(self, db_session, session_factory, monkeypatch):
        winner = await load_or_create_signing_key(db_session)

        async def _looks_absent(_db):
            # What the second request saw before the first one committed.
            return False, None

        monkeypatch.setattr(extension_keys, "_stored_value", _looks_absent)
        loser = await load_or_create_signing_key(db_session)
        assert loser.extension_id == winner.extension_id
