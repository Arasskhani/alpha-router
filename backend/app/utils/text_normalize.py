"""Normalization used for memory hashing, embedding, and lexical search."""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ARABIC_INDIC_TRANS = str.maketrans(
    {
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "ي": "ی",
        "ك": "ک",
        "ى": "ی",
    }
)


def normalize_memory_text(text: str | None) -> str:
    """NFC + Persian letter/digit folding + ZWNJ/whitespace collapse.

    Used for hashes and embeddings. Stored content stays as the original cleaned
    display string from ``normalize_memory_content``.
    """
    raw = "" if text is None else str(text)
    cleaned = unicodedata.normalize("NFC", raw)
    cleaned = _CONTROL_RE.sub("", cleaned)
    cleaned = cleaned.translate(_ARABIC_INDIC_TRANS)
    cleaned = cleaned.replace("\u200c", " ").replace("\u200d", "")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned
