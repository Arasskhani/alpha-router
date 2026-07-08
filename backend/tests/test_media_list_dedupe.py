"""Media library list deduplicates rows with the same content hash."""

import datetime as dt

from app.models.media import MediaAsset
from app.services.user_media_service import dedupe_media_rows_by_hash


def _row(*, row_id: int, user_id: int, content_hash: str | None, size: int = 100) -> MediaAsset:
    return MediaAsset(
        id=row_id,
        user_id=user_id,
        kind="image",
        mime_type="image/png",
        file_name=f"image-{row_id}.png",
        storage_path=f"cdn/u/{user_id}/{content_hash or row_id}.png",
        content_hash=content_hash,
        size_bytes=size,
        created_at=dt.datetime(2026, 1, 1, 12, 0, row_id),
    )


def test_dedupe_media_rows_by_hash_keeps_newest_id():
    rows = [
        _row(row_id=1, user_id=7, content_hash="abc"),
        _row(row_id=2, user_id=7, content_hash="abc"),
        _row(row_id=3, user_id=7, content_hash="def"),
    ]
    deduped = dedupe_media_rows_by_hash(rows)
    assert [r.id for r in deduped] == [3, 2]
