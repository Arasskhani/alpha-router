"""Lightweight prompt language detection for logging and translate helpers."""

from __future__ import annotations

import re

_RTL_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")


def _letter_counts(sample: str) -> tuple[int, int]:
    latin = 0
    other = 0
    for ch in sample:
        if not ch.isalpha():
            continue
        if _LATIN_LETTER_RE.match(ch):
            latin += 1
        else:
            other += 1
    return latin, other


def detect_prompt_language(text: str) -> str:
    """Return a coarse language tag for logging.

    - ``fa`` when Arabic/Persian script is present
    - ``en`` when the text is predominantly Latin letters
    - ``other`` for other non-Latin scripts (Chinese, Cyrillic, …)
    - ``unknown`` for empty / non-letter content
    """
    sample = (text or "").strip()
    if not sample:
        return "unknown"
    if _RTL_RE.search(sample):
        return "fa"
    latin, other = _letter_counts(sample)
    if latin == 0 and other == 0:
        return "unknown"
    if other > 0 and latin / (latin + other) < 0.85:
        return "other"
    return "en"


def needs_english_translation(text: str) -> bool:
    """True when the draft likely needs translation to English.

    Mirrors the frontend ``textNeedsEnglishTranslation`` heuristic so the
    translate short-circuit does not skip Chinese/Russian/etc. as "already English".
    """
    sample = (text or "").strip()
    if not sample:
        return False
    if _RTL_RE.search(sample):
        return True
    latin, other = _letter_counts(sample)
    if latin == 0 and other == 0:
        return False
    return other > 0 and latin / (latin + other) < 0.85
