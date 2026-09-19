"""The file upload must not happen while the ingestion lock is held.

``submit_document_bytes`` took a PostgreSQL advisory transaction lock keyed on
(knowledge base, canonical key), then - still inside that transaction -
encrypted the whole file and pushed it to object storage, then returned and let
the caller commit. The lock, the row lock on the document, and the database
connection were all held for the length of an upload that can be hundreds of
megabytes over a network that can stall.

The lock exists to serialise *version numbering*, which is three quick
statements. It was being held for the one part of the operation that is slow
and not a database operation at all.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.knowledge import IngestionJob, KnowledgeBase, KnowledgeDocumentVersion
from app.services.knowledge_ingestion_service import OBJECT_PURGE_JOB, submit_document_bytes

DOC_BYTES = b"Company handbook.\n\nSection 1. Working hours.\n"


class _ObservingStore:
    """Records what the database looked like at the moment of the upload."""

    def __init__(self, db) -> None:
        self._db = db
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.versions_at_put: list[int] = []
        self.on_put = None

    async def put(self, key: str, body: bytes) -> None:
        rows = (await self._db.execute(select(KnowledgeDocumentVersion))).scalars().all()
        self.versions_at_put.append(len(rows))
        self.objects[key] = bytes(body)
        if self.on_put is not None:
            await self.on_put(key)

    async def get(self, key: str, *, max_bytes: int) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.deleted.append(key)


async def _base(db_session) -> KnowledgeBase:
    row = KnowledgeBase(
        id=str(uuid.uuid4()),
        slug=f"policies-{uuid.uuid4().hex[:8]}",
        name="Policies",
        sensitivity="internal",
        status="active",
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def test_the_upload_happens_before_the_row_is_written(db_session, user):
    """The version row is written under the lock; the upload is not."""

    base = await _base(db_session)
    store = _ObservingStore(db_session)

    submission = await submit_document_bytes(
        db_session,
        knowledge_base_id=base.id,
        file_name="handbook.txt",
        declared_mime="text/plain",
        data=DOC_BYTES,
        uploaded_by_user_id=user.id,
        object_store=store,
    )
    await db_session.flush()

    assert store.versions_at_put == [0], (
        "the version row already existed when the upload started, so the upload ran inside the locked window"
    )
    assert submission.version.storage_key in store.objects


async def test_the_bytes_land_under_the_key_the_row_records(db_session, user):
    base = await _base(db_session)
    store = _ObservingStore(db_session)

    submission = await submit_document_bytes(
        db_session,
        knowledge_base_id=base.id,
        file_name="handbook.txt",
        declared_mime="text/plain",
        data=DOC_BYTES,
        uploaded_by_user_id=user.id,
        object_store=store,
    )

    assert set(store.objects) == {submission.version.storage_key}
    assert store.objects[submission.version.storage_key] != DOC_BYTES, "stored bytes are encrypted at rest"


async def test_an_unchanged_file_is_not_uploaded_again(db_session, user):
    base = await _base(db_session)
    store = _ObservingStore(db_session)
    kwargs = dict(
        knowledge_base_id=base.id,
        file_name="handbook.txt",
        declared_mime="text/plain",
        data=DOC_BYTES,
        uploaded_by_user_id=user.id,
        object_store=store,
    )

    first = await submit_document_bytes(db_session, **kwargs)
    await db_session.flush()
    second = await submit_document_bytes(db_session, **kwargs)
    await db_session.flush()

    assert second.duplicate
    assert second.version.id == first.version.id
    assert len(store.objects) == 1, "the same bytes were uploaded twice"


async def test_an_upload_overtaken_by_a_duplicate_is_purged(db_session, user):
    """Uploading first means a lost race leaves an object behind. Collect it.

    The second submitter's optimistic check finds nothing, uploads, and only
    then takes the lock - by which time the winner's version row is there and
    the submission deduplicates. The bytes it pushed belong to no row, so an
    object.purge job is enqueued for them.
    """

    base = await _base(db_session)
    store = _ObservingStore(db_session)
    kwargs = dict(
        knowledge_base_id=base.id,
        file_name="handbook.txt",
        declared_mime="text/plain",
        data=DOC_BYTES,
        uploaded_by_user_id=user.id,
    )

    winner_store = _ObservingStore(db_session)
    first = await submit_document_bytes(db_session, object_store=winner_store, **kwargs)
    await db_session.flush()

    # Force the slow path: pretend the optimistic check ran before the winner
    # committed, so this submission uploads and only then discovers the clash.
    from app.services import knowledge_ingestion_service as ingestion

    original = ingestion._existing_version_for_digest

    calls = {"n": 0}

    async def blind_first_look(db, *, knowledge_base_id, canonical, digest):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await original(db, knowledge_base_id=knowledge_base_id, canonical=canonical, digest=digest)

    ingestion._existing_version_for_digest = blind_first_look
    try:
        second = await submit_document_bytes(db_session, object_store=store, **kwargs)
    finally:
        ingestion._existing_version_for_digest = original
    await db_session.flush()

    assert second.duplicate
    assert second.version.id == first.version.id

    orphan = next(iter(store.objects))
    purges = (
        (await db_session.execute(select(IngestionJob).where(IngestionJob.job_type == OBJECT_PURGE_JOB)))
        .scalars()
        .all()
    )
    assert [job.payload_json["storage_key"] for job in purges] == [orphan], (
        "the object nobody references was left in storage forever"
    )
    assert purges[0].document_version_id is None
