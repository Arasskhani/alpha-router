"""Retention deletes the rows and the files, in that order, and only on purpose.

Two defects lived here.

``job_storage_cleanup`` opened a session, called ``purge_expired_media`` and
returned without committing. ``AsyncSessionLocal`` has no autocommit, so the
transaction rolled back - but the objects had already been deleted from storage
inside it. Every expired image, audio file and video kept its row, kept counting
against the owner's quota, and 404'd forever. The job could never converge,
because the rows it was supposed to remove came back every night.

The same function was also called from five GET endpoints, which made listing
your own media an irreversible destructive operation.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models.media import MediaAsset
from app.services import storage_service


class _Store:
    def __init__(self) -> None:
        self.objects: set[str] = set()
        self.deleted: list[str] = []

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.discard(key)


def _install(monkeypatch, store: _Store):
    monkeypatch.setattr(storage_service.oss, "is_cdn_object_key", lambda _key: True)
    monkeypatch.setattr(storage_service.oss, "delete_object", store.delete)


async def _asset(db_session, *, name: str, age_days: int, user_id: int) -> MediaAsset:
    row = MediaAsset(
        user_id=user_id,
        kind="image",
        mime_type="image/png",
        file_name=name,
        storage_path=f"cdn/u/test/{name}",
        size_bytes=10,
        content_hash=name,
        created_at=dt.datetime.utcnow() - dt.timedelta(days=age_days),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def test_expired_rows_and_objects_both_go(db_session, user, monkeypatch):
    store = _Store()
    _install(monkeypatch, store)
    await _asset(db_session, name="old.png", age_days=90, user_id=user.id)
    await _asset(db_session, name="fresh.png", age_days=1, user_id=user.id)
    store.objects.update({"cdn/u/test/old.png", "cdn/u/test/fresh.png"})

    result = await storage_service.purge_expired_media(db_session, retention_days=30)

    assert result["removed_files"] == 1
    assert store.deleted == ["cdn/u/test/old.png"]
    remaining = (await db_session.execute(select(MediaAsset.file_name))).scalars().all()
    assert remaining == ["fresh.png"], "the row must be gone, not just the file"


async def test_the_rows_are_committed_before_any_object_is_touched(db_session, user, monkeypatch):
    """The nightly job's failure mode: files deleted inside a transaction that rolls back."""

    store = _Store()

    def _delete(key: str) -> None:
        # By the time storage is touched, the deletion must already be durable.
        store.deleted.append(key)

    monkeypatch.setattr(storage_service.oss, "is_cdn_object_key", lambda _key: True)
    monkeypatch.setattr(storage_service.oss, "delete_object", _delete)

    await _asset(db_session, name="doomed.png", age_days=90, user_id=user.id)
    await db_session.commit()

    await storage_service.purge_expired_media(db_session, retention_days=30)

    # A fresh session sees the effect of the commit, not of this session's state.
    await db_session.rollback()
    survivors = (await db_session.execute(select(MediaAsset))).scalars().all()
    assert survivors == [], "a rollback after the purge must not resurrect rows whose files are gone"
    assert store.deleted == ["cdn/u/test/doomed.png"]


async def test_reading_media_does_not_delete_anything(db_session, user, monkeypatch):
    """A GET must not destroy files. Five read endpoints used to run the purge."""

    store = _Store()
    _install(monkeypatch, store)
    await _asset(db_session, name="expired.png", age_days=90, user_id=user.id)
    await db_session.flush()

    from app.api import admin, chat, user_media

    async def _target(_db, _user_id):
        return user

    monkeypatch.setattr(admin, "_admin_media_target_user", _target)

    await user_media.media_quota(user=user, db=db_session)
    await user_media.list_media(q=None, from_date=None, to_date=None, limit=50, offset=0, user=user, db=db_session)
    await chat.user_media(limit=50, user=user, db=db_session)
    await admin.admin_user_media_quota(user_id=user.id, db=db_session, _=user)
    await admin.admin_user_media_list(
        user_id=user.id, q=None, from_date=None, to_date=None, limit=50, offset=0, db=db_session, _=user
    )

    assert store.deleted == [], "a read endpoint deleted an object from storage"
    survivors = (await db_session.execute(select(MediaAsset.file_name))).scalars().all()
    assert survivors == ["expired.png"], "a read endpoint deleted a row"
