"""Document boundary, malware protocol, encryption, and chunking tests."""

from __future__ import annotations

import asyncio
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidTag

from app.services import malware_scan_service
from app.services.knowledge_chunking_service import chunk_segments
from app.services.knowledge_crypto_service import (
    decrypt_bytes,
    encrypt_bytes,
)
from app.services.knowledge_file_service import (
    ParsedSegment,
    UnsafeDocumentError,
    parse_document,
    validate_document,
)


def test_ooxml_active_content_and_archive_paths_are_rejected():
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(UnsafeDocumentError, match="Active or embedded"):
        validate_document(
            file_name="policy.docx",
            data=output.getvalue(),
            claimed_mime_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        )

    traversal = BytesIO()
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("../outside", "unsafe")
    with pytest.raises(UnsafeDocumentError, match="unsafe archive path"):
        validate_document(
            file_name="policy.docx",
            data=traversal.getvalue(),
            claimed_mime_type="application/octet-stream",
        )


def test_chunking_is_deterministic_and_hierarchical():
    text = "\n\n".join(f"Section {index}. " + ("Policy language. " * 35) for index in range(30))
    segments = (ParsedSegment(text=text, page_number=7, section="Policy"),)
    first = chunk_segments(segments)
    second = chunk_segments(segments)
    assert first == second
    parents = [chunk for chunk in first if chunk.kind == "parent"]
    children = [chunk for chunk in first if chunk.kind == "child"]
    assert parents
    assert children
    assert {chunk.parent_local_key for chunk in children} <= {chunk.local_key for chunk in parents}
    assert all(chunk.page_number == 7 for chunk in first)


def test_knowledge_encryption_authenticates_context_and_ciphertext():
    envelope = encrypt_bytes(b"sensitive policy", associated_data="version:1")
    assert b"sensitive policy" not in envelope
    assert decrypt_bytes(envelope, associated_data="version:1") == b"sensitive policy"
    with pytest.raises(InvalidTag):
        decrypt_bytes(envelope, associated_data="version:2")
    tampered = envelope[:-1] + bytes([envelope[-1] ^ 1])
    with pytest.raises(InvalidTag):
        decrypt_bytes(tampered, associated_data="version:1")


def _blank_scan_pdf() -> bytes:
    """A one-page PDF with no text layer - what a scanner produces."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_scanned_pdf_uses_bounded_ocr(monkeypatch):
    import pytesseract

    data = _blank_scan_pdf()
    monkeypatch.setattr(
        pytesseract,
        "image_to_string",
        lambda *_args, **_kwargs: (
            "این متن فارسی توسط OCR از صفحه اسکن‌شده استخراج شده است و برای بازیابی سازمانی استفاده می‌شود."
        ),
    )
    validated = validate_document(
        file_name="scan.pdf",
        data=data,
        claimed_mime_type="application/pdf",
    )
    parsed = parse_document(data, validated)
    assert parsed.metadata["ocr_pages"] == [1]
    assert parsed.segments[0].page_number == 1
    assert "OCR" in parsed.segments[0].text


def test_pdf_ocr_retries_after_transient_render_failure(monkeypatch):
    import pypdfium2 as pdfium
    import pytesseract

    data = _blank_scan_pdf()

    original_render = pdfium.PdfPage.render
    calls = {"count": 0}

    def flaky_render(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise MemoryError("bitmap allocation failed")
        return original_render(self, *args, **kwargs)

    monkeypatch.setattr(pdfium.PdfPage, "render", flaky_render)
    monkeypatch.setattr(
        pytesseract,
        "image_to_string",
        lambda *_args, **_kwargs: "Recovered OCR text after a transient renderer allocation failure.",
    )
    validated = validate_document(
        file_name="scan-retry.pdf",
        data=data,
        claimed_mime_type="application/pdf",
    )
    parsed = parse_document(data, validated)
    assert calls["count"] >= 2
    assert parsed.metadata["ocr_pages"] == [1]
    assert "Recovered OCR" in parsed.segments[0].text


async def _test_clamav_instream_protocol(monkeypatch) -> None:
    received = bytearray()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        assert await reader.readexactly(len(b"zINSTREAM\0")) == b"zINSTREAM\0"
        while True:
            length = int.from_bytes(await reader.readexactly(4), "big")
            if length == 0:
                break
            received.extend(await reader.readexactly(length))
        writer.write(b"stream: Eicar-Test-Signature FOUND\0")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(
        malware_scan_service,
        "get_settings",
        lambda: SimpleNamespace(
            clamav_host="127.0.0.1",
            clamav_port=port,
            clamav_required=True,
            clamav_scan_timeout_seconds=5,
        ),
    )
    async with server:
        result = await malware_scan_service.scan_bytes(b"test-payload")
    assert bytes(received) == b"test-payload"
    assert not result.clean
    assert result.signature == "Eicar-Test-Signature"


async def test_clamav_instream_protocol(monkeypatch):
    await _test_clamav_instream_protocol(monkeypatch)
