"""Object storage cleanup when media database persistence fails."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services import storage_service as storage


class Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FailingDb:
    def add(self, row):
        self.row = row

    def begin_nested(self):
        return Nested()

    async def flush(self):
        raise RuntimeError("database write failed")


def test_new_object_is_removed_when_database_flush_fails() -> None:
    deleted = []

    async def run():
        with (
            patch.object(storage, "_resolve_username_raw", AsyncMock(return_value="tester")),
            patch.object(storage, "_find_user_asset_by_hash", AsyncMock(return_value=None)),
            patch.object(storage, "get_retention_days_cached", AsyncMock(return_value=30)),
            patch.object(storage, "_put_object_once", AsyncMock(return_value=True)),
            patch.object(storage, "_count_storage_path_refs", AsyncMock(return_value=0)),
            patch(
                "app.services.user_media_service.ensure_user_media_quota",
                AsyncMock(return_value=None),
            ),
            patch.object(storage.oss, "delete_object", side_effect=deleted.append),
        ):
            with pytest.raises(RuntimeError, match="database write failed"):
                await storage.store_media_from_blob(
                    FailingDb(),
                    user_id=1,
                    kind="document",
                    blob=b"safe",
                    mime="text/plain",
                    content_hash="a" * 64,
                    username="tester",
                )

    asyncio.run(run())
    assert len(deleted) == 1
