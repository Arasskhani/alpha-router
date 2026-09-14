"""NUL bytes from extracted documents must never reach a PostgreSQL text column."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.core.text_safety import clean_extracted_text, strip_nul
from app.services import attachment_extract
from app.services import storage_service as storage


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _CapturingDb:
    def __init__(self):
        self.row = None

    def add(self, row):
        self.row = row

    def begin_nested(self):
        return _Nested()

    async def flush(self):
        return None


def test_strip_nul_keeps_other_characters() -> None:
    assert strip_nul("in\x00voice") == "invoice"
    assert strip_nul("clean") == "clean"
    assert strip_nul(None) is None


def test_clean_extracted_text_drops_control_characters_but_keeps_layout() -> None:
    assert clean_extracted_text("a\x00b\x07c\td\ne\r\nf") == "abc\td\ne\r\nf"
    assert clean_extracted_text(None) == ""


def test_extracted_document_text_has_no_nul() -> None:
    raw = b"Invoice\x00Total: 120\x00"
    text = attachment_extract.extract_document_text(raw, "invoice.txt")
    assert "\x00" not in text
    assert "Invoice" in text and "Total: 120" in text


def test_media_prompt_with_nul_is_scrubbed_before_insert() -> None:
    db = _CapturingDb()

    async def run():
        with (
            patch.object(storage, "_resolve_username_raw", AsyncMock(return_value="tester")),
            patch.object(storage, "_find_user_asset_by_hash", AsyncMock(return_value=None)),
            patch.object(storage, "get_retention_days_cached", AsyncMock(return_value=30)),
            patch.object(storage, "_put_object_once", AsyncMock(return_value=True)),
            patch(
                "app.services.user_media_service.ensure_user_media_quota",
                AsyncMock(return_value=None),
            ),
        ):
            await storage.store_media_from_blob(
                db,
                user_id=1,
                kind="document",
                blob=b"%PDF-1.4",
                mime="application/pdf",
                content_hash="b" * 64,
                source_model="openrouter/auto\x00",
                source_prompt="Summarize\x00 the invoices",
                username="tester",
            )

    asyncio.run(run())
    assert db.row is not None
    assert db.row.source_prompt == "Summarize the invoices"
    assert db.row.source_model == "openrouter/auto"
