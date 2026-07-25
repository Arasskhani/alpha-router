"""Unit tests for global transfer size limits."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import transfer_limits_service as tls


class FakeDb:
    def __init__(self) -> None:
        self.store: dict[str, SimpleNamespace] = {}

    async def execute(self, statement):
        del statement

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return self._rows

        return _Result(list(self.store.values()))

    async def get(self, model, key):
        del model
        return self.store.get(key)

    def add(self, row):
        self.store[row.key] = row

    async def flush(self):
        return None


def setup_function() -> None:
    tls.invalidate_transfer_limits_cache()


def test_normalize_enforces_chat_total_gte_upload() -> None:
    data = tls._normalize_limits(50, 10, 100)
    assert data["max_upload_file_mb"] == 50
    assert data["max_chat_attachments_total_mb"] == 50


def test_set_rejects_chat_total_below_upload() -> None:
    db = FakeDb()

    async def run():
        await tls.set_transfer_limits(db, max_upload_file_mb=40, max_chat_attachments_total_mb=40)
        with pytest.raises(ValueError, match="must be >="):
            await tls.set_transfer_limits(db, max_chat_attachments_total_mb=10)

    asyncio.run(run())


def test_set_and_get_roundtrip_updates_cache() -> None:
    db = FakeDb()

    async def run():
        saved = await tls.set_transfer_limits(
            db,
            max_upload_file_mb=30,
            max_chat_attachments_total_mb=60,
            max_media_zip_download_mb=512,
        )
        assert saved["max_upload_file_mb"] == 30
        assert saved["max_chat_attachments_total_mb"] == 60
        assert saved["max_media_zip_download_mb"] == 512
        assert tls.cached_upload_limit_bytes() == 30 * 1024 * 1024
        assert tls.cached_zip_aggregate_limit_bytes() == 512 * 1024 * 1024
        loaded = await tls.get_transfer_limits(db)
        assert loaded["max_upload_file_mb"] == 30

    asyncio.run(run())


def test_media_input_limit_uses_transfer_cache(monkeypatch) -> None:
    from app.services import storage_service as storage

    tls._store_cache(
        tls._normalize_limits(40, 80, 200)
    )
    assert storage.media_input_limit() == 40 * 1024 * 1024
    tls.invalidate_transfer_limits_cache()
