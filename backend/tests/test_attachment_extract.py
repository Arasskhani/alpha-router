"""Tests for attachment image handling and text-vs-binary extraction."""

import base64
import random

import pytest

from app.services.attachment_extract import (
    build_image_data_url,
    extract_document_text,
    extract_document_text_bounded,
    is_probably_text,
    processed_attachment_payload,
    processed_attachment_payload_async,
)
from app.services.attachment_policy import AttachmentPolicyError

# Minimal valid PNG (1x1 red pixel)
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_png_with_embedded_svg_string_in_metadata_is_allowed():
    """PNG text chunks may contain '<svg' — must not be rejected as SVG."""
    raw = _PNG_1X1 + b"\x00" + b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    url = build_image_data_url(raw, "image/png", "photo.png")
    assert url.startswith("data:image/png;base64,")


def test_real_svg_is_rejected():
    raw = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'
    with pytest.raises(AttachmentPolicyError, match="SVG"):
        build_image_data_url(raw, "image/svg+xml", "icon.svg")


def test_processed_attachment_payload_png():
    payload = processed_attachment_payload(
        filename="test.png",
        kind="image",
        mime_type="image/png",
        url="blob:test",
        raw=_PNG_1X1,
    )
    assert payload["data_url"].startswith("data:image/png;base64,")


# --------------------------------------------------------------------------- #
# is_probably_text
# --------------------------------------------------------------------------- #

_UTF16_LE_BOM = b"\xff\xfe"
_UTF8_BOM = b"\xef\xbb\xbf"


def _random_bytes(n: int, seed: int = 1234) -> bytes:
    """Deterministic 'binary' bytes so a failure reproduces."""
    return random.Random(seed).randbytes(n)


def test_is_probably_text_accepts_plain_utf8():
    """WHY: the common case — a source file or notes with a non-ASCII character
    must be read as text, not refused for containing a multi-byte sequence."""
    assert is_probably_text("def main():\n    return 'héllo wörld'\n".encode()) is True


def test_is_probably_text_accepts_utf8_with_bom():
    """WHY: Windows editors prepend a UTF-8 BOM; U+FEFF is not 'printable' by
    Python's definition and must not be counted against the file."""
    assert is_probably_text(_UTF8_BOM + b"key=value\r\n") is True


def test_is_probably_text_accepts_utf16_le_with_bom():
    """WHY: UTF-16 text has a NUL in every ASCII code unit. It must be recognised
    by its BOM before the NUL rule runs, or every Windows UTF-16 export is 'binary'."""
    raw = _UTF16_LE_BOM + "Hello, world\nSecond line\n".encode("utf-16-le")
    assert b"\x00" in raw  # the rule under test really is exercised
    assert is_probably_text(raw) is True


def test_is_probably_text_rejects_single_nul_in_otherwise_valid_text():
    """WHY: one NUL is enough — no accepted text encoding puts one in prose, and
    binary formats with ASCII headers are caught by exactly this byte."""
    assert is_probably_text(b"Looks like text until\x00here") is False


def test_is_probably_text_rejects_random_bytes():
    """WHY: the whole point of the check — random bytes must never be decoded
    into replacement-character noise for the model."""
    assert is_probably_text(_random_bytes(4096)) is False


def test_is_probably_text_rejects_valid_utf8_that_is_mostly_control_characters():
    """WHY: exercises the printable-ratio rule on its own. These bytes have no
    NUL and are valid UTF-8, so only the ratio can refuse them."""
    controls = bytes(range(0x01, 0x09)) * 64  # SOH..BS: valid UTF-8, no NUL, not printable
    assert controls.decode("utf-8")  # precondition: decodes fine
    assert is_probably_text(controls) is False


def test_is_probably_text_tolerates_a_few_control_characters():
    """WHY: the ratio is 90%, not 100%: a log with ANSI colour codes is still a
    text file a person wants read."""
    line = b"\x1b[32mINFO\x1b[0m request served in 12ms\n"  # 4 ESC bytes in ~40 chars
    assert is_probably_text(line * 20) is True


def test_is_probably_text_rejects_png_header():
    """WHY: PNG starts with a high byte and a NUL-free-looking signature; it must
    be refused by the UTF-8 rule even before the IHDR chunk's NULs."""
    assert is_probably_text(_PNG_1X1) is False
    assert is_probably_text(_PNG_1X1[:8]) is False  # signature alone: \x89 is invalid UTF-8


def test_is_probably_text_rejects_empty():
    """WHY: nothing to judge and nothing to show; the caller has a better message
    for an empty file than an empty string."""
    assert is_probably_text(b"") is False


def test_is_probably_text_samples_only_the_head():
    """WHY: the check must stay cheap on large uploads, so only the first
    ``sample`` bytes are read. Text followed by binary past the boundary is text;
    move the boundary and the same bytes are refused — proving the sample is honoured."""
    text_head = b"line of text\n" * 8000  # ~104 KB > 64 KB default sample
    raw = text_head + _random_bytes(4096) + b"\x00" * 16
    assert is_probably_text(raw) is True
    assert is_probably_text(raw, sample=len(raw)) is False


def test_is_probably_text_does_not_fail_on_multibyte_sequence_cut_at_sample_boundary():
    """WHY: a multi-byte character split by the sample window is not invalid
    UTF-8; the incremental decoder must hold the partial sequence instead of
    raising and calling a perfectly good text file binary."""
    raw = ("é" * 100).encode()  # 2 bytes each
    assert is_probably_text(raw, sample=99) is True  # 99 cuts the 50th 'é' in half


# --------------------------------------------------------------------------- #
# extract_document_text fall-through
# --------------------------------------------------------------------------- #


def test_unknown_extension_with_text_bytes_is_decoded():
    """WHY: kind 'file' covers extensions with no parser; when the bytes are text
    the person still gets their content read."""
    text = extract_document_text(b"meeting notes\n- item one\n", "notes.xyz")
    assert text is not None
    assert "item one" in text


def test_unknown_extension_with_binary_bytes_returns_none():
    """WHY: a Photoshop file decoded with replacement is thousands of tokens of
    garbage. None tells the caller to describe it by name and size instead."""
    assert extract_document_text(b"8BPS" + _random_bytes(2048), "design.psd") is None


def test_python_source_is_text_when_operator_unblocks_it():
    """WHY: '.py' is blocked by default but an operator may allow it; the
    extractor must read it as text rather than needing the extension listed."""
    text = extract_document_text(b"import os\n\nprint(os.getcwd())\n", "script.py")
    assert text is not None
    assert "getcwd" in text


def test_sqlite_header_returns_none():
    """WHY: the SQLite magic is ASCII followed by a NUL — the NUL rule, not the
    UTF-8 rule, is what catches it. Regression guard for that specific path."""
    assert extract_document_text(b"SQLite format 3\x00" + _random_bytes(512), "data.sqlite") is None


def test_declared_text_extension_still_decodes_with_replacement():
    """WHY: '.txt' promised text. Its behaviour must not change with the binary
    check: even mostly-binary bytes decode with replacement as before."""
    raw = b"header" + _random_bytes(2048) + b"\x00\x00"
    assert is_probably_text(raw) is False  # the new check would refuse it...
    text = extract_document_text(raw, "dump.txt")
    assert isinstance(text, str)  # ...yet the declared extension still gets a string
    assert text != "(Empty file.)"


def test_media_extensions_still_raise():
    """WHY: unchanged contract — image/video/audio names are never text-extracted."""
    with pytest.raises(ValueError, match="Not a document file"):
        extract_document_text(b"plain text", "photo.jpg")


# --------------------------------------------------------------------------- #
# payload shape
# --------------------------------------------------------------------------- #


def test_file_kind_binary_payload_marks_binary_and_size():
    """WHY: the UI and the model prompt need to know there is no text to show and
    how large the file is; that is all they get about a .psd."""
    raw = b"8BPS" + _random_bytes(1000)
    payload = processed_attachment_payload(
        filename="design.psd", kind="file", mime_type="application/octet-stream", url="blob:x", raw=raw
    )
    assert payload["kind"] == "file"
    assert payload["text"] is None
    assert payload["binary"] is True
    assert payload["size_bytes"] == 1004
    assert "data_url" not in payload


def test_file_kind_text_payload_has_text_and_no_binary_flag():
    """WHY: the 'binary' key is a signal, not a boolean column — it is present
    only when there is no text, so consumers keying on its presence stay simple."""
    payload = processed_attachment_payload(
        filename="notes.xyz", kind="file", mime_type="application/octet-stream", url="blob:x", raw=b"hello there\n"
    )
    assert payload["text"] == "hello there"
    assert "binary" not in payload
    assert payload["size_bytes"] == len(b"hello there\n")


def test_document_kind_payload_shape_unchanged_plus_size():
    """WHY: existing consumers read name/kind/mime_type/url/text; they must find
    exactly those, plus the new size_bytes."""
    payload = processed_attachment_payload(
        filename="notes.txt", kind="document", mime_type="text/plain", url="blob:x", raw=b"some text"
    )
    assert set(payload) == {"name", "kind", "mime_type", "url", "text", "size_bytes"}
    assert payload["text"] == "some text"
    assert payload["size_bytes"] == 9


def test_image_kind_payload_has_size_but_no_text():
    """WHY: images are never text-extracted; size_bytes is set for every kind."""
    payload = processed_attachment_payload(
        filename="test.png", kind="image", mime_type="image/png", url="blob:x", raw=_PNG_1X1
    )
    assert "text" not in payload
    assert "binary" not in payload
    assert payload["size_bytes"] == len(_PNG_1X1)


async def test_async_payload_mirrors_sync_for_binary_file():
    """WHY: request handlers use the async path; None must survive the thread
    hop and timeout wrapper rather than becoming the string 'None'."""
    raw = b"8BPS" + _random_bytes(1000)
    payload = await processed_attachment_payload_async(
        filename="design.psd", kind="file", mime_type="application/octet-stream", url="blob:x", raw=raw
    )
    assert payload["text"] is None
    assert payload["binary"] is True
    assert payload["size_bytes"] == 1004


async def test_async_payload_mirrors_sync_for_text_file():
    """WHY: same contract as the sync variant for the text case."""
    payload = await processed_attachment_payload_async(
        filename="notes.xyz", kind="file", mime_type="application/octet-stream", url="blob:x", raw=b"hello there\n"
    )
    assert payload["text"] == "hello there"
    assert "binary" not in payload
    assert payload["size_bytes"] == 12


async def test_bounded_extraction_propagates_none():
    """WHY: the bounded wrapper must not coerce the binary marker to a string."""
    assert await extract_document_text_bounded(b"SQLite format 3\x00" + _random_bytes(64), "db.sqlite") is None
