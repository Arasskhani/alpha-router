"""Unit tests for global transfer size limits."""

from __future__ import annotations

from types import SimpleNamespace

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


async def test_set_rejects_chat_total_below_upload() -> None:
    db = FakeDb()
    await tls.set_transfer_limits(db, max_upload_file_mb=40, max_chat_attachments_total_mb=40)
    with pytest.raises(ValueError, match="must be >="):
        await tls.set_transfer_limits(db, max_chat_attachments_total_mb=10)


async def test_set_and_get_roundtrip_updates_cache() -> None:
    db = FakeDb()
    saved = await tls.set_transfer_limits(
        db,
        max_upload_file_mb=30,
        max_chat_attachments_total_mb=60,
        max_media_zip_download_mb=512,
        max_chat_attachments_count=12,
    )
    assert saved["max_upload_file_mb"] == 30
    assert saved["max_chat_attachments_total_mb"] == 60
    assert saved["max_media_zip_download_mb"] == 512
    assert saved["max_chat_attachments_count"] == 12
    # Workspace files inherit upload count when not explicitly stored.
    assert saved["max_code_interpreter_workspace_files"] == 12
    assert saved["max_code_interpreter_workspace_total_mb"] == tls.DEFAULT_CI_WORKSPACE_TOTAL_MB
    assert tls.cached_upload_limit_bytes() == 30 * 1024 * 1024
    assert tls.cached_zip_aggregate_limit_bytes() == 512 * 1024 * 1024
    assert tls.cached_chat_attachments_count() == 12
    loaded = await tls.get_transfer_limits(db)
    assert loaded["max_upload_file_mb"] == 30
    assert loaded["max_chat_attachments_count"] == 12
    assert loaded["max_code_interpreter_workspace_files"] == 12
    assert loaded["max_code_interpreter_workspace_total_mb"] == tls.DEFAULT_CI_WORKSPACE_TOTAL_MB
    assert "max_code_interpreter_workspace_files" not in db.store
    assert "max_code_interpreter_workspace_total_mb" not in db.store


def test_attachment_count_is_clamped() -> None:
    data = tls._normalize_limits(25, 36, 256, 999)
    assert data["max_chat_attachments_count"] == tls.MAX_CHAT_ATTACHMENTS_COUNT
    assert tls.MAX_CHAT_ATTACHMENTS_COUNT == 500
    data = tls._normalize_limits(25, 36, 256, 0)
    assert data["max_chat_attachments_count"] == tls.MIN_CHAT_ATTACHMENTS_COUNT


def test_workspace_defaults_inherit_attachment_count() -> None:
    data = tls._normalize_limits(25, 36, 256, 100)
    assert data["max_code_interpreter_workspace_files"] == 100
    assert data["max_code_interpreter_workspace_total_mb"] == tls.DEFAULT_CI_WORKSPACE_TOTAL_MB
    assert data["max_code_interpreter_workspace_total_bytes"] == 16 * 1024 * 1024


def test_workspace_limits_are_clamped() -> None:
    data = tls._normalize_limits(25, 36, 256, 5, workspace_files=999, workspace_total_mb=999)
    assert data["max_code_interpreter_workspace_files"] == tls.MAX_CI_WORKSPACE_FILES
    assert data["max_code_interpreter_workspace_total_mb"] == tls.MAX_CI_WORKSPACE_TOTAL_MB
    data = tls._normalize_limits(25, 36, 256, 5, workspace_files=0, workspace_total_mb=0)
    assert data["max_code_interpreter_workspace_files"] == tls.MIN_CI_WORKSPACE_FILES
    assert data["max_code_interpreter_workspace_total_mb"] == tls.MIN_CI_WORKSPACE_TOTAL_MB


async def test_workspace_files_inherit_until_explicitly_stored() -> None:
    db = FakeDb()
    await tls.set_transfer_limits(db, max_chat_attachments_count=40)
    loaded = await tls.get_transfer_limits(db)
    assert loaded["max_chat_attachments_count"] == 40
    assert loaded["max_code_interpreter_workspace_files"] == 40
    assert "max_code_interpreter_workspace_files" not in db.store

    await tls.set_transfer_limits(db, max_chat_attachments_count=80)
    loaded = await tls.get_transfer_limits(db)
    assert loaded["max_code_interpreter_workspace_files"] == 80

    saved = await tls.set_transfer_limits(db, max_code_interpreter_workspace_files=100)
    assert saved["max_code_interpreter_workspace_files"] == 100
    assert db.store["max_code_interpreter_workspace_files"].value == "100"

    await tls.set_transfer_limits(db, max_chat_attachments_count=20)
    loaded = await tls.get_transfer_limits(db)
    assert loaded["max_chat_attachments_count"] == 20
    assert loaded["max_code_interpreter_workspace_files"] == 100


async def test_workspace_total_mb_persists_when_set() -> None:
    db = FakeDb()
    saved = await tls.set_transfer_limits(db, max_code_interpreter_workspace_total_mb=32)
    assert saved["max_code_interpreter_workspace_total_mb"] == 32
    assert saved["max_code_interpreter_workspace_total_bytes"] == 32 * 1024 * 1024
    assert db.store["max_code_interpreter_workspace_total_mb"].value == "32"
    loaded = await tls.get_transfer_limits(db)
    assert loaded["max_code_interpreter_workspace_total_mb"] == 32


def test_public_view_includes_workspace_fields() -> None:
    data = tls._normalize_limits(25, 36, 256, 12, workspace_files=100, workspace_total_mb=24)
    view = tls.transfer_limits_public_view(data)
    assert view["max_chat_attachments_count"] == 12
    assert view["max_code_interpreter_workspace_files"] == 100
    assert view["max_code_interpreter_workspace_total_mb"] == 24
    assert view["max_code_interpreter_workspace_total_bytes"] == 24 * 1024 * 1024


def test_media_input_limit_uses_transfer_cache(monkeypatch) -> None:
    from app.services import storage_service as storage

    tls._store_cache(tls._normalize_limits(40, 80, 200))
    assert storage.media_input_limit() == 40 * 1024 * 1024
    tls.invalidate_transfer_limits_cache()
