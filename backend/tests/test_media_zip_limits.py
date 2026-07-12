"""Bounded temp-file ZIP generation and cleanup tests."""

import asyncio
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings
from app.services import user_media_service as media


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, statement):
        del statement
        return ScalarRows(self.rows)


def _row(row_id: int, size: int = 4):
    return SimpleNamespace(id=row_id, file_name=f"f{row_id}.txt", size_bytes=size)


def test_zip_rejects_count_and_declared_size_before_reads(monkeypatch) -> None:
    monkeypatch.setenv("MAX_ZIP_ITEMS", "2")
    monkeypatch.setenv("MAX_ZIP_SINGLE_FILE_BYTES", str(1024 * 1024))
    get_settings.cache_clear()
    with pytest.raises(media.MediaZipLimitError, match="Too many"):
        asyncio.run(media.build_media_zip_file(FakeDb([]), 1, [1, 2, 3]))
    with pytest.raises(media.MediaZipLimitError, match="single-file"):
        asyncio.run(
            media.build_media_zip_file(
                FakeDb([_row(1, 1024 * 1024 + 1)]),
                1,
                [1],
            )
        )
    get_settings.cache_clear()


def test_zip_streams_valid_temp_file_and_removes_it() -> None:
    get_settings.cache_clear()

    async def run():
        with patch.object(media, "read_media_bytes", AsyncMock(side_effect=[b"one", b"two"])):
            path, packed = await media.build_media_zip_file(
                FakeDb([_row(1, 3), _row(2, 3)]),
                1,
                [1, 2],
            )
        assert packed == 2
        with zipfile.ZipFile(path) as archive:
            assert len(archive.namelist()) == 2
        chunks = [chunk async for chunk in media.stream_media_zip(path)]
        assert chunks
        assert not path.exists()

    asyncio.run(run())


def test_zip_temp_file_is_removed_on_cancellation(tmp_path: Path) -> None:
    get_settings.cache_clear()
    target = tmp_path / "cancelled.zip"

    def fake_mkstemp(**kwargs):
        del kwargs
        fd = os.open(target, os.O_CREAT | os.O_RDWR)
        return fd, str(target)

    async def cancelled(_row):
        raise asyncio.CancelledError()

    async def run():
        with (
            patch.object(media.tempfile, "mkstemp", fake_mkstemp),
            patch.object(media, "read_media_bytes", cancelled),
            pytest.raises(asyncio.CancelledError),
        ):
            await media.build_media_zip_file(FakeDb([_row(1)]), 1, [1])

    asyncio.run(run())
    assert not target.exists()
