"""Normalization used for memory hashing, embedding, and lexical search."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

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


_SEARCH_FOLD = str.maketrans(
    {
        "ة": "ه",
        "ۀ": "ه",
        "أ": "ا",
        "إ": "ا",
        "ٱ": "ا",
        "آ": "ا",
        "ؤ": "و",
        "ئ": "ی",
        "ـ": None,
    }
)
_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670]")


def fold_for_search(text: str | None) -> str:
    """What lexical memory search compares: a text folded the same way however it was typed.

    On top of ``normalize_memory_text`` (Arabic ي/ك as Persian ی/ک, Persian and
    Arabic digits as 0-9): the zero-width non-joiner is dropped (می‌خواهم reads
    as میخواهم), and hamza forms, taa marbuta, diacritics, tatweel and case
    compare equal. A memory keeps its text folded this way beside it
    (``content_search``) and each term of a question is folded the same, so
    both sides read alike.
    """
    raw = ("" if text is None else str(text)).replace("\u200c", "")
    folded = _DIACRITICS_RE.sub("", normalize_memory_text(raw).translate(_SEARCH_FOLD))
    return _WHITESPACE_RE.sub(" ", folded).strip().casefold()


def searchable_memory_text(model: Any) -> Any:
    """The SQL a lexical term is matched against: a memory's folded text, or its text before it had one."""
    from sqlalchemy import func

    return func.coalesce(model.content_search, func.lower(model.content))
