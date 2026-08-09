"""Filename policy shared by the sandbox broker and the code interpreter.

Workspace and artifact names are written by users and models, so any script
(Persian, Arabic, Cyrillic, CJK) is allowed. What guards the sandbox boundary is
the extension allowlist plus the per-artifact content validation, not the
alphabet of the name, so the policy only rejects names that can escape a
directory or misrepresent what the file is:

* path separators, NUL, and the reserved ``.`` / ``..`` names
* control, surrogate, private-use, and unassigned code points
* BiDi and other formatting characters that make a name render differently than
  it is stored (``report<U+202E>fdp.exe``); ZWNJ and ZWJ stay allowed because
  Persian and Arabic names use them as ordinary spelling
* a leading ``-`` (argument-looking), a leading ``.`` (hidden file), and
  surrounding or trailing whitespace
* names over the character or UTF-8 byte budget

``sandbox/runner.py`` repeats these rules on purpose: the sandbox image ships no
application code and cannot import this module. Keep the two in sync.
"""

from __future__ import annotations

import unicodedata

MAX_FILENAME_CHARS = 128
# Most Linux filesystems cap a single path component at 255 bytes.
MAX_FILENAME_BYTES = 255

ZERO_WIDTH_NON_JOINER = "\u200c"
ZERO_WIDTH_JOINER = "\u200d"

_ALLOWED_FORMAT_CHARS = frozenset({ZERO_WIDTH_NON_JOINER, ZERO_WIDTH_JOINER})
_ALLOWED_PUNCTUATION = frozenset("._- ()")
_RESERVED_NAMES = frozenset({".", ".."})
# Combining marks carry Arabic/Persian vowel signs and Indic matras.
_ALLOWED_CATEGORIES = frozenset({"Mn", "Mc"})


def normalize_filename(name: str) -> str:
    """NFC-fold and trim a filename so equivalent spellings collapse into one."""
    return unicodedata.normalize("NFC", name).strip()


def is_allowed_filename_char(ch: str) -> bool:
    """True when a single character may appear in a sandbox filename."""
    if ch in _ALLOWED_PUNCTUATION or ch in _ALLOWED_FORMAT_CHARS:
        return True
    if ch.isalnum():
        return True
    return unicodedata.category(ch) in _ALLOWED_CATEGORIES


def is_safe_filename(name: object) -> bool:
    """True when ``name`` is a single, non-deceptive path component."""
    if not isinstance(name, str) or not name:
        return False
    if name != normalize_filename(name):
        return False
    if name in _RESERVED_NAMES:
        return False
    if "/" in name or "\\" in name:
        return False
    if name[0] in "-." or name[-1] in " .":
        return False
    if len(name) > MAX_FILENAME_CHARS:
        return False
    if len(name.encode("utf-8")) > MAX_FILENAME_BYTES:
        return False
    return all(is_allowed_filename_char(ch) for ch in name)


def scrub_filename_chars(value: str, *, replacement: str = "_") -> str:
    """Fold every character the policy rejects into ``replacement``."""
    normalized = unicodedata.normalize("NFC", value)
    return "".join(
        ch if is_allowed_filename_char(ch) else replacement for ch in normalized
    )
