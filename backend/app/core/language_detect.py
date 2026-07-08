"""Lightweight prompt language detection for logging."""

import re

_PERSIAN_RE = re.compile(r"[\u0600-\u06FF]")


def detect_prompt_language(text: str) -> str:
    if not text:
        return "unknown"
    if _PERSIAN_RE.search(text):
        return "fa"
    return "en"
