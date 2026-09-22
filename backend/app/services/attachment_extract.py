"""Extract text from uploaded documents for chat analysis."""

from __future__ import annotations

import asyncio
import codecs
import io
from typing import Any

import pandas as pd

from app.core.text_safety import clean_extracted_text
from app.services.attachment_policy import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    _extension,
)

_MAX_EXTRACT_CHARS = 120_000

#: Share of decoded characters that must be printable (or whitespace) for a
#: file of unknown type to be read as text. See ``is_probably_text``.
_MIN_PRINTABLE_RATIO = 0.9


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


def is_probably_text(raw: bytes, *, sample: int = 65536) -> bool:
    """True when the first ``sample`` bytes look like a text file a person wrote.

    Used for attachments whose extension the platform has no parser for (kind
    ``file``: ``.psd``, ``.parquet``, ``.sqlite``, ``.py`` if unblocked, ...).
    Declared text documents (``.txt``, ``.md``, ``.json``) never come here;
    they are decoded with replacement regardless, because the name already
    promised text. This check exists so a binary file is *not* decoded into
    thousands of tokens of replacement characters for the model.

    Rules, and why each one:

    * **Empty is not text.** There is nothing to show, and the caller has a
      better message for a file with no content than an empty string.
    * **Only the head is read.** Text files are text from the first byte; a
      binary container that happens to start with an ASCII header (``8BPS``,
      ``SQLite format 3``) is caught within the same head. Reading the whole
      of a multi-megabyte upload would cost time for no better answer.
    * **A UTF-16 BOM is honoured before anything else.** UTF-16 text is full
      of NUL bytes, so it must be recognised by its BOM before the NUL rule
      runs, and decoded as UTF-16 rather than UTF-8.
    * **A NUL byte means binary.** No text encoding this product accepts
      (UTF-8, or UTF-16 with a BOM, handled above) puts a NUL in text a person
      wrote; nearly every binary format has them in its first few hundred
      bytes. This alone rejects most executables, archives and media.
    * **The bytes must be valid UTF-8** (a UTF-8 BOM is allowed). Random bytes
      are almost never valid UTF-8 past a handful of characters. The decoder
      is incremental so a multi-byte sequence cut at the sample boundary does
      not count as invalid.
    * **At least 90% of characters must be printable or whitespace.** Some
      binary formats are pure ASCII by accident (short headers, base64
      blobs) and a few text files carry stray control bytes (ANSI colour
      codes in a log, form feeds). The ratio separates the two without
      demanding perfection from either.
    """

    if not raw:
        return False
    head = bytes(raw[:sample])
    truncated = len(raw) > len(head)

    if head[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        encoding = "utf-16"
        if truncated and len(head) % 2:
            # Keep whole code units so a split unit is not read as garbage.
            head = head[:-1]
    else:
        if b"\x00" in head:
            return False
        encoding = "utf-8-sig"

    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    try:
        text = decoder.decode(head, final=not truncated)
    except UnicodeDecodeError:
        return False
    if not text:
        # A lone BOM, or a head shorter than one multi-byte sequence. Nothing
        # decoded means nothing to judge — and nothing worth showing.
        return False

    printable = sum(1 for ch in text if ch.isprintable() or ch.isspace())
    return printable / len(text) >= _MIN_PRINTABLE_RATIO


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


def extract_document_text(raw: bytes, filename: str) -> str | None:
    """Text of a document attachment, or ``None`` when the file is binary.

    Known document formats go to their parser. Declared text extensions
    (``ALLOWED_DOCUMENT_EXTENSIONS``: txt, md, json, ...) are decoded with
    replacement whatever their bytes look like — the name promised text.
    Anything else (kind ``file``) is decoded only when ``is_probably_text``
    agrees; otherwise ``None`` tells the caller to hand the file to the model
    by name and size instead of as replacement-character noise.
    """

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
        if ext not in ALLOWED_DOCUMENT_EXTENSIONS and not is_probably_text(raw):
            return None
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


async def extract_document_text_bounded(raw: bytes, filename: str) -> str | None:
    """``extract_document_text`` off the event loop with a wall-clock ceiling.

    The parsers (pypdf, openpyxl, python-docx) are synchronous and CPU-bound;
    a crafted file can keep them busy for minutes. Running them inline would
    stall every other request on this worker, so they go to a thread and the
    caller gets a placeholder if the ceiling is hit. ``None`` (binary file)
    is passed through as is, never turned into the string ``"None"``.
    """
    from app.config import get_settings

    timeout = max(1, int(getattr(get_settings(), "attachment_extract_timeout_seconds", 30) or 30))
    try:
        return await asyncio.wait_for(asyncio.to_thread(extract_document_text, raw, filename), timeout=timeout)
    except TimeoutError:
        return f"(Text extraction from {filename} exceeded {timeout}s and was skipped.)"


#: Kinds served as media: referenced by URL (and data URL for images), never
#: text-extracted. Every other kind — ``document`` and ``file`` alike — has
#: its text extracted when the bytes allow it.
_MEDIA_KINDS: frozenset[str] = frozenset({"image", "video", "audio"})


def _base_payload(*, filename: str, kind: str, mime_type: str, url: str, raw: bytes) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": filename,
        "kind": kind,
        "mime_type": mime_type,
        "url": url,
        # Set for every kind: the UI shows it, and for a binary ``file`` it is
        # all the model gets to know about the content besides the name.
        "size_bytes": len(raw),
    }
    if kind == "image":
        payload["data_url"] = build_image_data_url(raw, mime_type, filename)
    return payload


def _attach_text(payload: dict[str, Any], text: str | None) -> None:
    """Record the extraction result: text, or the fact that there was none.

    ``binary`` is set only when extraction found no text to show, so a
    consumer that reads ``text`` alone still behaves; one that looks for
    ``binary`` can describe the file by name and size instead.
    """

    payload["text"] = text
    if text is None:
        payload["binary"] = True


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
    if kind not in _MEDIA_KINDS:
        _attach_text(payload, extract_document_text(raw, filename))
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
    if kind not in _MEDIA_KINDS:
        # Binary media is referenced by URL only (no text extraction).
        _attach_text(payload, await extract_document_text_bounded(raw, filename))
    return payload
