"""Normalization for text that must survive a PostgreSQL text column.

PostgreSQL rejects U+0000 in text values with ``invalid byte sequence for
encoding "UTF8": 0x00``. Extracted document text carries NUL routinely: pypdf
emits it for some PDFs, and the latin-1 decode fallback maps every 0x00 byte to
U+0000, so user-derived text is scrubbed before it can reach the database.
"""

from __future__ import annotations

# C0 controls other than tab/newline/carriage return carry no meaning in
# extracted text and corrupt both rendering and downstream diffing.
_STRIPPED_CONTROLS = {code: None for code in range(0x20) if code not in (0x09, 0x0A, 0x0D)}
_STRIPPED_CONTROLS[0x7F] = None

_NUL_ONLY = {0x00: None}


def strip_nul(value: str | None) -> str | None:
    """Remove U+0000 so the value can be stored in a text column."""
    if not value:
        return value
    return value.translate(_NUL_ONLY)


def clean_extracted_text(value: str | None) -> str:
    """Drop NUL and other C0 controls from text extracted out of documents."""
    if not value:
        return ""
    return value.translate(_STRIPPED_CONTROLS)
