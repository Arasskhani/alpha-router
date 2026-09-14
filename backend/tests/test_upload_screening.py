"""Every user upload is screened: archive structure, ClamAV, bounded extraction."""

from __future__ import annotations

import asyncio
import io
import time
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.archive_safety import ArchiveSafetyError, validate_ooxml_archive
from app.services import upload_screening
from app.services.malware_scan_service import MalwareScanResult, MalwareScannerUnavailable
from app.services.upload_screening import UploadRejected, screen_upload

EICAR_LIKE = MalwareScanResult(clean=False, signature="Win.Test.EICAR_HDB-1", raw_response="stream: FOUND")
CLEAN = MalwareScanResult(clean=True, signature=None, raw_response="stream: OK")


def _docx(members: dict[str, bytes], *, method=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _settings(**over):
    base = dict(
        knowledge_max_archive_entries=10_000,
        knowledge_max_archive_uncompressed_bytes=250 * 1024 * 1024,
        knowledge_max_archive_ratio=100,
        clamav_required=True,
        attachment_extract_timeout_seconds=30,
    )
    base.update(over)
    return SimpleNamespace(**base)


# ------------------------------------------------------------------ archive safety


def test_ooxml_bomb_ratio_is_refused(monkeypatch):
    monkeypatch.setattr("app.core.archive_safety.get_settings", lambda: _settings())
    bomb = _docx({"word/document.xml": b"\0" * (5 * 1024 * 1024)})  # ~1:5000 ratio
    with pytest.raises(ArchiveSafetyError, match="compression ratio"):
        validate_ooxml_archive(bomb, ".docx")


def test_ooxml_traversal_and_macros_are_refused(monkeypatch):
    monkeypatch.setattr("app.core.archive_safety.get_settings", lambda: _settings())
    with pytest.raises(ArchiveSafetyError, match="unsafe archive path"):
        validate_ooxml_archive(_docx({"../evil": b"x", "word/document.xml": b"<w/>"}), ".docx")
    with pytest.raises(ArchiveSafetyError, match="Active or embedded"):
        validate_ooxml_archive(_docx({"word/vbaProject.bin": b"x", "word/document.xml": b"<w/>"}), ".docx")
    with pytest.raises(ArchiveSafetyError, match="does not match its extension"):
        validate_ooxml_archive(_docx({"word/document.xml": b"<w/>"}), ".xlsx")
    # A benign document passes, .xlsm included.
    validate_ooxml_archive(_docx({"word/document.xml": b"<w:document/>"}), ".docx")
    validate_ooxml_archive(_docx({"xl/workbook.xml": b"<workbook/>"}), ".xlsm")


def test_knowledge_service_still_raises_its_own_error(monkeypatch):
    from app.services.knowledge_file_service import UnsafeDocumentError, _validate_ooxml_archive

    monkeypatch.setattr("app.core.archive_safety.get_settings", lambda: _settings())
    with pytest.raises(UnsafeDocumentError):
        _validate_ooxml_archive(b"not a zip", ".docx")


# ------------------------------------------------------------------ screening


def test_screen_upload_rejects_malware_with_422(monkeypatch):
    monkeypatch.setattr("app.core.archive_safety.get_settings", lambda: _settings())
    monkeypatch.setattr(upload_screening, "get_settings", lambda: _settings())

    async def run():
        with patch.object(upload_screening, "scan_bytes", new=AsyncMock(return_value=EICAR_LIKE)):
            with pytest.raises(UploadRejected) as exc:
                await screen_upload(b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR", "note.txt")
            assert exc.value.status_code == 422
        with patch.object(upload_screening, "scan_bytes", new=AsyncMock(return_value=CLEAN)):
            await screen_upload(b"hello", "note.txt")

    asyncio.run(run())


def test_screen_upload_fails_closed_when_scanner_is_down_and_required(monkeypatch):
    monkeypatch.setattr("app.core.archive_safety.get_settings", lambda: _settings())
    monkeypatch.setattr(upload_screening, "get_settings", lambda: _settings(clamav_required=True))

    async def run():
        with patch.object(upload_screening, "scan_bytes", new=AsyncMock(side_effect=MalwareScannerUnavailable("down"))):
            with pytest.raises(UploadRejected) as exc:
                await screen_upload(b"hello", "note.txt")
            assert exc.value.status_code == 503

    asyncio.run(run())


def test_screen_upload_checks_archive_before_scanning(monkeypatch):
    monkeypatch.setattr("app.core.archive_safety.get_settings", lambda: _settings())
    monkeypatch.setattr(upload_screening, "get_settings", lambda: _settings())
    scanner = AsyncMock(return_value=CLEAN)

    async def run():
        with patch.object(upload_screening, "scan_bytes", new=scanner):
            with pytest.raises(UploadRejected) as exc:
                await screen_upload(_docx({"word/document.xml": b"\0" * (5 * 1024 * 1024)}), "report.docx")
            assert exc.value.status_code == 422
            # The bomb never reached ClamAV.
            scanner.assert_not_awaited()
            # A non-Office file skips the archive check and is scanned.
            await screen_upload(b"%PDF-1.4", "x.pdf")
            scanner.assert_awaited_once()

    asyncio.run(run())


# ------------------------------------------------------------------ bounded extraction


def test_extraction_runs_off_loop_and_is_time_bounded(monkeypatch):
    from app.services import attachment_extract

    monkeypatch.setattr("app.config.get_settings", lambda: _settings(attachment_extract_timeout_seconds=1))

    def slow_extract(raw, filename):
        time.sleep(2.5)
        return "late"

    async def run():
        ticks = {"max_gap": 0.0}

        async def ticker():
            last = time.monotonic()
            for _ in range(40):
                await asyncio.sleep(0.02)
                now = time.monotonic()
                ticks["max_gap"] = max(ticks["max_gap"], now - last)
                last = now

        with patch.object(attachment_extract, "extract_document_text", slow_extract):
            t = asyncio.create_task(ticker())
            text = await attachment_extract.extract_document_text_bounded(b"x", "big.pdf")
            await t
        assert "exceeded 1s" in text
        # The parser ran in a thread: the loop kept ticking meanwhile.
        assert ticks["max_gap"] < 0.5, ticks

    asyncio.run(run())


def test_async_payload_uses_bounded_extraction(monkeypatch):
    from app.services import attachment_extract

    async def run():
        with patch.object(attachment_extract, "extract_document_text_bounded", new=AsyncMock(return_value="TEXT")):
            payload = await attachment_extract.processed_attachment_payload_async(
                filename="a.txt", kind="document", mime_type="text/plain", url="u", raw=b"abc"
            )
        assert payload["text"] == "TEXT"
        payload = await attachment_extract.processed_attachment_payload_async(
            filename="a.mp3", kind="audio", mime_type="audio/mpeg", url="u", raw=b"abc"
        )
        assert "text" not in payload

    asyncio.run(run())
