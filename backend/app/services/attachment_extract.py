"""Extract text from uploaded documents for chat analysis."""

from __future__ import annotations

import asyncio

import io
from typing import Any

import pandas as pd

from app.core.text_safety import clean_extracted_text
from app.services.attachment_policy import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    _extension,
)

_MAX_EXTRACT_CHARS = 120_000


def _truncate(text: str) -> str:
    text = clean_extracted_text(text).strip()
    if len(text) <= _MAX_EXTRACT_CHARS:
        return text
    return text[:_MAX_EXTRACT_CHARS] + "\n\n[…truncated…]"


def _decode_text(raw: bytes) -> str:
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_pdf(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return _truncate("\n".join(parts))


def _extract_docx(raw: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(raw))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return _truncate("\n".join(parts))


def _extract_pptx(raw: bytes) -> str:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(raw))
    parts: list[str] = []
    for i, slide in enumerate(prs.slides, 1):
        slide_parts: list[str] = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                slide_parts.append(shape.text.strip())
        if slide_parts:
            parts.append(f"Slide {i}:\n" + "\n".join(slide_parts))
    return _truncate("\n\n".join(parts))


def _extract_tabular(raw: bytes, ext: str) -> str:
    buf = io.BytesIO(raw)
    if ext == "csv":
        df = pd.read_csv(buf)
    elif ext == "tsv":
        df = pd.read_csv(buf, sep="\t")
    elif ext in ("xls", "xlsx", "xlsm"):
        df = pd.read_excel(buf)
    else:
        df = pd.read_csv(buf)
    return _truncate(df.to_csv(index=False))


def extract_document_text(raw: bytes, filename: str) -> str:
    ext = _extension(filename)
    if ext in ALLOWED_IMAGE_EXTENSIONS or ext in ALLOWED_VIDEO_EXTENSIONS or ext in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError("Not a document file.")

    try:
        if ext == "pdf":
            return _extract_pdf(raw) or "(No extractable text in PDF.)"
        if ext == "docx":
            return _extract_docx(raw) or "(No extractable text in document.)"
        if ext in ("ppt", "pptx"):
            if ext == "ppt":
                return "(Legacy .ppt files are not supported. Save as .pptx and retry.)"
            return _extract_pptx(raw) or "(No extractable text in presentation.)"
        if ext in ("csv", "tsv", "xls", "xlsx", "xlsm"):
            return _extract_tabular(raw, ext)
        if ext == "doc":
            return "(Legacy .doc files are not supported. Save as .docx and retry.)"
        return _truncate(_decode_text(raw)) or "(Empty file.)"
    except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
        return f"(Could not extract text from {filename}: {exc})"


def _detect_image_mime(raw: bytes) -> str | None:
    """Return MIME when raw bytes match a known binary image signature."""
    if len(raw) >= 8 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(raw) >= 3 and raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(raw) >= 6 and raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if len(raw) >= 2 and raw[:2] == b"BM":
        return "image/bmp"
    if len(raw) >= 4 and raw[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        brand = raw[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"avif", b"avis"):
            return "image/heic" if b"avif" not in brand else "image/avif"
    return None


def _looks_like_svg(raw: bytes) -> bool:
    """True only for text/XML SVG payloads — not binary images with incidental '<svg' bytes."""
    if _detect_image_mime(raw):
        return False
    head = raw[:4096].lstrip()
    low = head.lower()
    if low.startswith(b"<svg"):
        return True
    return bool(low.startswith(b"<?xml") and b"<svg" in low)


def build_image_data_url(raw: bytes, mime_type: str, filename: str) -> str:
    import base64
    import mimetypes

    from app.services.attachment_policy import AttachmentPolicyError

    if _looks_like_svg(raw):
        raise AttachmentPolicyError("SVG is not allowed.")

    magic_mime = _detect_image_mime(raw)
    guessed = mimetypes.guess_type(filename)[0]
    mime = (mime_type or magic_mime or guessed or "image/png").split(";")[0].strip()
    if magic_mime:
        mime = magic_mime
    if "svg" in mime.lower():
        raise AttachmentPolicyError("SVG is not allowed.")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def extract_document_text_bounded(raw: bytes, filename: str) -> str:
    """``extract_document_text`` off the event loop with a wall-clock ceiling.

    The parsers (pypdf, openpyxl, python-docx) are synchronous and CPU-bound;
    a crafted file can keep them busy for minutes. Running them inline would
    stall every other request on this worker, so they go to a thread and the
    caller gets a placeholder if the ceiling is hit.
    """
    from app.config import get_settings

    timeout = max(1, int(getattr(get_settings(), "attachment_extract_timeout_seconds", 30) or 30))
    try:
        return await asyncio.wait_for(asyncio.to_thread(extract_document_text, raw, filename), timeout=timeout)
    except TimeoutError:
        return f"(Text extraction from {filename} exceeded {timeout}s and was skipped.)"


def _base_payload(*, filename: str, kind: str, mime_type: str, url: str, raw: bytes) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": filename,
        "kind": kind,
        "mime_type": mime_type,
        "url": url,
    }
    if kind == "image":
        payload["data_url"] = build_image_data_url(raw, mime_type, filename)
    return payload


def processed_attachment_payload(
    *,
    filename: str,
    kind: str,
    mime_type: str,
    url: str,
    raw: bytes,
) -> dict[str, Any]:
    """Synchronous variant (tests, tools). Request handlers use the async one."""
    payload = _base_payload(filename=filename, kind=kind, mime_type=mime_type, url=url, raw=raw)
    if kind not in {"image", "video", "audio"}:
        payload["text"] = extract_document_text(raw, filename)
    return payload


async def processed_attachment_payload_async(
    *,
    filename: str,
    kind: str,
    mime_type: str,
    url: str,
    raw: bytes,
) -> dict[str, Any]:
    payload = _base_payload(filename=filename, kind=kind, mime_type=mime_type, url=url, raw=raw)
    if kind not in {"image", "video", "audio"}:
        # Binary media is referenced by URL only (no text extraction).
        payload["text"] = await extract_document_text_bounded(raw, filename)
    return payload
