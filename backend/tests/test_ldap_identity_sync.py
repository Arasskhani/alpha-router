"""Directory identity, email-collision safety, and partial-failure isolation.

Regression cover for the sync that inserted a duplicate row whenever a user's
DN and sAMAccountName both changed in AD, hit ``ix_users_email``, and rolled
back the entire run.
"""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User, UserGroup
from app.services import ldap_auth, ldap_sync
from app.services.ldap_auth import _entry_to_profile, _normalize_guid, _stable_entry_id

GUID = "6b1f2d9c-9f5a-4a1e-9c3a-2b7d4e5f6a7b"
DN_OLD = "CN=Faegh Pouladian,OU=Staff,DC=corp,DC=local"
DN_NEW = "CN=Faegh Pouladian,OU=Users,OU=CentralOffice,DC=corp,DC=local"
EMAIL = "f.pouladian@corp.local"

CFG = {
    "enabled": True,
    "server": "ldaps://dc.corp.local:636",
    "base_dn": "DC=corp,DC=local",
}


class _Entry:
    """Minimal stand-in for an ldap3 / WinLdap entry."""

    def __init__(self, dn: str, attrs: dict):
        self.entry_dn = dn
        self._attrs = attrs

    @property
    def entry_attributes(self):
        return list(self._attrs.keys())

    def __getitem__(self, name: str):
        return self._attrs[name]


def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _prepare(rows: list[User]):
    engine, factory = _make_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        for row in rows:
            db.add(row)
        await db.commit()
    return engine, factory


def _patch_directory(monkeypatch, users: list[dict], groups: list[dict] | None = None):
    monkeypatch.setattr(ldap_sync, "fetch_ldap_users", lambda cfg: list(users))
    monkeypatch.setattr(ldap_sync, "fetch_ldap_groups", lambda cfg: list(groups or []))


def _profile(**over) -> dict:
    base = {
        "username": "f.pouladian1",
        "email": EMAIL,
        "display_name": "Faegh Pouladian",
        "external_id": GUID,
        "dn": DN_NEW,
        "identity_source": "guid",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------
# Identity extraction
# --------------------------------------------------------------------------


def test_normalize_guid_accepts_braced_string_and_ad_byte_order():
    assert _normalize_guid("{%s}" % GUID.upper()) == GUID
    packed = uuid.UUID(GUID).bytes_le
    assert _normalize_guid(packed) == GUID
    assert _normalize_guid("CN=Someone,DC=corp,DC=local") is None
    assert _normalize_guid(None) is None


def test_stable_entry_id_prefers_objectguid_then_entryuuid():
    ad = _Entry(DN_NEW, {"objectGUID": "{%s}" % GUID, "entryUUID": str(uuid.uuid4())})
    assert _stable_entry_id(ad) == GUID

    other = str(uuid.uuid4())
    openldap = _Entry(DN_NEW, {"entryUUID": other})
    assert _stable_entry_id(openldap) == other

    assert _stable_entry_id(_Entry(DN_NEW, {"cn": "x"})) is None


def test_entry_to_profile_uses_guid_as_identity_and_keeps_dn_separate():
    entry = _Entry(
        DN_NEW,
        {"sAMAccountName": "f.pouladian1", "mail": EMAIL, "objectGUID": "{%s}" % GUID},
    )
    profile = _entry_to_profile(entry, "fallback")
    assert profile["external_id"] == GUID
    assert profile["dn"] == DN_NEW
    assert profile["identity_source"] == "guid"


def test_entry_to_profile_falls_back_to_dn_without_a_guid():
    entry = _Entry(DN_NEW, {"sAMAccountName": "jdoe", "mail": "jdoe@corp.local"})
    profile = _entry_to_profile(entry, "fallback")
    assert profile["external_id"] == DN_NEW
    assert profile["identity_source"] == "dn"


def test_login_fallback_never_writes_a_bind_string_as_identity(monkeypatch):
    """A bind string like CORP\\jdoe is not a directory identity.

    Storing it used to overwrite the real DN, so the next sync no longer
    recognised the user -- and with prune on, soft-deleted them.
    """

    class _Conn:
        entries: list = []

        def search(self, *a, **k):
            return None

        def unbind(self):
            return None

    monkeypatch.setattr(ldap_auth, "_bind_login_connection", lambda *a, **k: _Conn())
    profile = ldap_auth.authenticate_ldap_sync(
        "jdoe", "pw", {**CFG, "domain": "corp.local"}
    )
    assert profile is not None
    assert profile["external_id"] is None
    assert profile["username"]


# --------------------------------------------------------------------------
# Sync: identity matching
# --------------------------------------------------------------------------


async def _renamed_and_moved_user_is_updated_not_duplicated(monkeypatch):
    engine, factory = await _prepare(
        [
            User(
                username="f.pouladian",
                email=EMAIL,
                auth_provider="ldap",
                external_id=DN_OLD,
            )
        ]
    )
    _patch_directory(monkeypatch, [_profile()])
    async with factory() as db:
        result = await ldap_sync.sync_ldap_directory(db, CFG)
    assert result["users_synced"] == 1
    assert result["users_skipped"] == 0
    assert result["conflicts"] == []
    async with factory() as db:
        rows = (await db.execute(select(User))).scalars().all()
        assert len(rows) == 1, "a moved user must not be inserted a second time"
        assert rows[0].external_id == GUID, "identity must be rewritten to the GUID"
        assert rows[0].username == "f.pouladian1"
        assert rows[0].email == EMAIL
    await engine.dispose()


async def _legacy_dn_row_is_backfilled_to_guid(monkeypatch):
    engine, factory = await _prepare(
        [User(username="jdoe", auth_provider="ldap", external_id=DN_NEW)]
    )
    _patch_directory(
        monkeypatch,
        [_profile(username="jdoe", email="jdoe@corp.local", display_name="J Doe")],
    )
    async with factory() as db:
        await ldap_sync.sync_ldap_directory(db, CFG)
    async with factory() as db:
        rows = (await db.execute(select(User))).scalars().all()
        assert len(rows) == 1
        assert rows[0].external_id == GUID
    await engine.dispose()


async def _soft_deleted_row_holding_the_address_is_restored(monkeypatch):
    import datetime

    engine, factory = await _prepare(
        [
            User(
                username="f.pouladian",
                email=EMAIL,
                auth_provider="ldap",
                external_id=DN_OLD,
                is_active=False,
                deleted_at=datetime.datetime.utcnow(),
            )
        ]
    )
    _patch_directory(monkeypatch, [_profile()])
    async with factory() as db:
        await ldap_sync.sync_ldap_directory(db, CFG)
    async with factory() as db:
        rows = (await db.execute(select(User))).scalars().all()
        assert len(rows) == 1
        assert rows[0].deleted_at is None
        assert rows[0].is_active is True
    await engine.dispose()


# --------------------------------------------------------------------------
# Sync: email collisions never abort the run
# --------------------------------------------------------------------------


async def _two_directory_entries_sharing_one_address(monkeypatch):
    engine, factory = await _prepare([])
    second = str(uuid.uuid4())
    _patch_directory(
        monkeypatch,
        [
            _profile(username="first", external_id=GUID, dn="CN=A,DC=corp,DC=local"),
            _profile(username="second", external_id=second, dn="CN=B,DC=corp,DC=local"),
        ],
    )
    async with factory() as db:
        result = await ldap_sync.sync_ldap_directory(db, CFG)
    # Both accounts exist; exactly one holds the contested address.
    assert result["users_synced"] == 2
    assert any(c["reason"] == "email_in_use" for c in result["conflicts"])
    async with factory() as db:
        rows = (await db.execute(select(User))).scalars().all()
        assert len(rows) == 2
        assert sum(1 for r in rows if (r.email or "") == EMAIL) == 1
    await engine.dispose()


async def _address_moved_between_directory_users_is_not_stolen(monkeypatch):
    engine, factory = await _prepare(
        [
            User(username="olduser", email=EMAIL, auth_provider="ldap", external_id="guid-old"),
            User(username="newuser", auth_provider="ldap", external_id=GUID),
        ]
    )
    _patch_directory(monkeypatch, [_profile(username="newuser")])
    async with factory() as db:
        result = await ldap_sync.sync_ldap_directory(db, CFG)
    assert result["users_skipped"] == 0
    assert any(c["reason"] == "email_in_use" for c in result["conflicts"])
    async with factory() as db:
        rows = {r.username: r for r in (await db.execute(select(User))).scalars().all()}
        assert rows["olduser"].email == EMAIL
        assert rows["newuser"].email is None
    await engine.dispose()


async def _local_password_account_is_linked_and_keeps_its_hash(monkeypatch):
    engine, factory = await _prepare(
        [
            User(
                username="f.pouladian",
                email=EMAIL,
                auth_provider="local",
                hashed_password="argon2-hash",
            )
        ]
    )
    _patch_directory(monkeypatch, [_profile()])
    async with factory() as db:
        result = await ldap_sync.sync_ldap_directory(db, CFG)
    assert result["local_accounts_linked"] == 1
    async with factory() as db:
        rows = (await db.execute(select(User))).scalars().all()
        assert len(rows) == 1
        assert rows[0].auth_provider == "ldap"
        assert rows[0].external_id == GUID
        # The hash stays so the account is not locked out if the directory is
        # unreachable and this is the last administrator.
        assert rows[0].hashed_password == "argon2-hash"
    await engine.dispose()


# --------------------------------------------------------------------------
# Sync: one bad record must not end the run, and must block pruning
# --------------------------------------------------------------------------


async def _one_failing_record_does_not_abort_the_run(monkeypatch):
    engine, factory = await _prepare([])
    real = ldap_sync._sync_one_user

    async def _flaky(db, item, conflicts, claimed_ids=None):
        if item.get("username") == "boom":
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        return await real(db, item, conflicts, claimed_ids)

    monkeypatch.setattr(ldap_sync, "_sync_one_user", _flaky)
    _patch_directory(
        monkeypatch,
        [
            _profile(username="good1", email="g1@corp.local", external_id=str(uuid.uuid4())),
            _profile(username="boom", email="boom@corp.local", external_id=str(uuid.uuid4())),
            _profile(username="good2", email="g2@corp.local", external_id=str(uuid.uuid4())),
        ],
    )
    async with factory() as db:
        result = await ldap_sync.sync_ldap_directory(db, CFG)
    assert result["users_synced"] == 2
    assert result["users_skipped"] == 1
    assert result["conflicts"][0]["username"] == "boom"
    async with factory() as db:
        names = {r.username for r in (await db.execute(select(User))).scalars().all()}
        assert names == {"good1", "good2"}
    await engine.dispose()


async def _prune_is_suppressed_after_a_skipped_record(monkeypatch):
    engine, factory = await _prepare(
        [User(username="stale", auth_provider="ldap", external_id="guid-stale")]
    )
    real = ldap_sync._sync_one_user

    async def _flaky(db, item, conflicts, claimed_ids=None):
        if item.get("username") == "boom":
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))
        return await real(db, item, conflicts, claimed_ids)

    monkeypatch.setattr(ldap_sync, "_sync_one_user", _flaky)
    _patch_directory(monkeypatch, [_profile(username="boom")])
    async with factory() as db:
        result = await ldap_sync.sync_ldap_directory(db, {**CFG, "sync_ous_prune": True})
    assert result["prune_skipped"] is True
    assert result["users_pruned"] == 0
    async with factory() as db:
        stale = (
            await db.execute(select(User).where(User.username == "stale"))
        ).scalars().first()
        assert stale.deleted_at is None, "a partial snapshot must never prune"
    await engine.dispose()


async def _prune_runs_on_a_clean_snapshot(monkeypatch):
    engine, factory = await _prepare(
        [
            User(username="stale", auth_provider="ldap", external_id="guid-stale"),
            User(username="f.pouladian", auth_provider="ldap", external_id=DN_OLD, email=EMAIL),
        ]
    )
    _patch_directory(monkeypatch, [_profile()])
    async with factory() as db:
        result = await ldap_sync.sync_ldap_directory(db, {**CFG, "sync_ous_prune": True})
    assert result["prune_skipped"] is False
    assert result["users_soft_deleted"] == 1
    async with factory() as db:
        rows = {r.username: r for r in (await db.execute(select(User))).scalars().all()}
        assert rows["stale"].deleted_at is not None
        # The moved user was matched, not pruned.
        assert rows["f.pouladian1"].deleted_at is None
    await engine.dispose()


# --------------------------------------------------------------------------
# Groups: membership is DN-valued and must survive the GUID switch
# --------------------------------------------------------------------------


async def _group_membership_resolves_by_dn_not_identity(monkeypatch):
    engine, factory = await _prepare([])
    group_guid = str(uuid.uuid4())
    _patch_directory(
        monkeypatch,
        [_profile()],
        [
            {
                "name": "Central Office",
                "external_id": group_guid,
                "dn": "CN=Central Office,OU=Groups,DC=corp,DC=local",
                "description": None,
                "members": [DN_NEW],
            }
        ],
    )
    async with factory() as db:
        result = await ldap_sync.sync_ldap_directory(db, CFG)
    assert result["members_linked"] == 1
    async with factory() as db:
        group = (await db.execute(select(UserGroup))).scalars().first()
        assert group.external_id == group_guid
    await engine.dispose()


async def _legacy_group_keyed_by_dn_is_backfilled(monkeypatch):
    group_dn = "CN=Central Office,OU=Groups,DC=corp,DC=local"
    group_guid = str(uuid.uuid4())
    engine, factory = await _prepare(
        [UserGroup(name="Central Office", source="ldap", external_id=group_dn)]
    )
    _patch_directory(
        monkeypatch,
        [],
        [
            {
                "name": "Central Office",
                "external_id": group_guid,
                "dn": group_dn,
                "description": None,
                "members": [],
            }
        ],
    )
    async with factory() as db:
        await ldap_sync.sync_ldap_directory(db, CFG)
    async with factory() as db:
        groups = (await db.execute(select(UserGroup))).scalars().all()
        assert len(groups) == 1, "the group must not be duplicated under its GUID"
        assert groups[0].external_id == group_guid
    await engine.dispose()


# --------------------------------------------------------------------------
# Login: the same collision used to surface as a 500
# --------------------------------------------------------------------------


async def _login_with_a_taken_address_does_not_fail():
    from app.api.auth import _upsert_directory_user

    engine, factory = await _prepare(
        [User(username="someoneelse", email=EMAIL, auth_provider="ldap", external_id="guid-x")]
    )
    async with factory() as db:
        user = await _upsert_directory_user(
            db,
            {"username": "f.pouladian1", "email": EMAIL, "external_id": GUID, "dn": DN_NEW},
            "ldap",
        )
        assert user.username == "f.pouladian1"
        assert user.email is None, "the address stays with the row that holds it"
    async with factory() as db:
        rows = (await db.execute(select(User))).scalars().all()
        assert len(rows) == 2
        assert sum(1 for r in rows if (r.email or "") == EMAIL) == 1
    await engine.dispose()


async def _login_matches_ldap_user_by_guid_after_a_rename():
    from app.api.auth import _upsert_directory_user

    engine, factory = await _prepare(
        [User(username="f.pouladian", auth_provider="ldap", external_id=GUID)]
    )
    async with factory() as db:
        user = await _upsert_directory_user(
            db,
            {"username": "f.pouladian1", "email": EMAIL, "external_id": GUID, "dn": DN_NEW},
            "ldap",
        )
        assert user.email == EMAIL
    async with factory() as db:
        rows = (await db.execute(select(User))).scalars().all()
        assert len(rows) == 1, "a renamed user must not get a second account at login"
    await engine.dispose()


def test_login_with_a_taken_address_does_not_fail():
    asyncio.run(_login_with_a_taken_address_does_not_fail())


def test_login_matches_ldap_user_by_guid_after_a_rename():
    asyncio.run(_login_matches_ldap_user_by_guid_after_a_rename())


def test_renamed_and_moved_user_is_updated_not_duplicated(monkeypatch):
    asyncio.run(_renamed_and_moved_user_is_updated_not_duplicated(monkeypatch))


def test_legacy_dn_row_is_backfilled_to_guid(monkeypatch):
    asyncio.run(_legacy_dn_row_is_backfilled_to_guid(monkeypatch))


def test_soft_deleted_row_holding_the_address_is_restored(monkeypatch):
    asyncio.run(_soft_deleted_row_holding_the_address_is_restored(monkeypatch))


def test_two_directory_entries_sharing_one_address(monkeypatch):
    asyncio.run(_two_directory_entries_sharing_one_address(monkeypatch))


def test_address_moved_between_directory_users_is_not_stolen(monkeypatch):
    asyncio.run(_address_moved_between_directory_users_is_not_stolen(monkeypatch))


def test_local_password_account_is_linked_and_keeps_its_hash(monkeypatch):
    asyncio.run(_local_password_account_is_linked_and_keeps_its_hash(monkeypatch))


def test_one_failing_record_does_not_abort_the_run(monkeypatch):
    asyncio.run(_one_failing_record_does_not_abort_the_run(monkeypatch))


def test_prune_is_suppressed_after_a_skipped_record(monkeypatch):
    asyncio.run(_prune_is_suppressed_after_a_skipped_record(monkeypatch))


def test_prune_runs_on_a_clean_snapshot(monkeypatch):
    asyncio.run(_prune_runs_on_a_clean_snapshot(monkeypatch))


def test_group_membership_resolves_by_dn_not_identity(monkeypatch):
    asyncio.run(_group_membership_resolves_by_dn_not_identity(monkeypatch))


def test_legacy_group_keyed_by_dn_is_backfilled(monkeypatch):
    asyncio.run(_legacy_group_keyed_by_dn_is_backfilled(monkeypatch))
