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


_STOPWORDS_TEXT = """
the and for with that this what was were are you your have has had not but from they them their there
will would can could should about which when where how who whom why into than then also just like some
any all more most other such only very does did done been being our out get got its please tell know
want need make let yes okay thanks thank hello
برای این اون آن است بود هست هستم هستید نیست شد شود کرد کنم کنی کنید کنیم کردم میکنم میخواهم میخوام
من تو ما شما او اونها آنها هم یا اما ولی چه چی چرا کجا چطور چگونه یک هر همه بعد قبل اگر خیلی دیگه
دیگر باید نه بله آره روی زیر بین پیش پس حالا فقط هنوز های ها رو را که از به با در تا
میشه بشه دارم داری داره دارید داشتم بگو بگید لطفا ممنون سلام الان چیه کدوم کدام
"""
#: Words too common to find a memory by (English and Persian, folded as ``fold_for_search`` folds them).
SEARCH_STOPWORDS = frozenset(fold_for_search(word) for word in _STOPWORDS_TEXT.split())


def search_terms(query: str | None, *, limit: int = 12) -> list[str]:
    """The words a lexical memory search looks for: folded, three letters or more, not stop words.

    ``query`` is read line by line from the last: its newest question comes
    first, so it is not crowded out by the older ones or the chat's title.
    """
    terms: list[str] = []
    for line in reversed((query or "").splitlines()):
        # Letters and digits only: Persian punctuation (؟ ، ؛) sits in the Arabic block but is not a word.
        for token in re.findall(r"\w{3,}", fold_for_search(line)):
            if token in SEARCH_STOPWORDS or token in terms:
                continue
            terms.append(token)
            if len(terms) >= limit:
                return terms
    return terms
