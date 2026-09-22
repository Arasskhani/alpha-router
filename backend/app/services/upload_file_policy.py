"""Which files a person may attach, decided in one place, by the operator.

Until now a chat attachment had to pass two lists: a blocklist of executable,
script, web and archive extensions, and an allowlist of four kinds (image,
video, audio, document). Anything outside the allowlist was refused with
"not supported", and both lists were baked into the code — and copied into
the frontend. That made the product refuse a ``.psd`` or a ``.parquet``
that a person had every reason to share, and made a policy change a release.

This module replaces both with one policy the operator owns:

* **blocklist mode** (default): a file is refused when *any* of its suffixes
  is on the blocked list. Everything else is accepted. The default blocked
  list is exactly the one the code used to hard-code.
* **allowlist mode**: on top of the blocklist, the file's final suffix must be
  on the allowed list. For installations that want to name what comes in.

Both lists are editable in full — there is no locked core. Two protections
therefore sit *outside* the lists and do not move:

1. **A file must be what its name says.** The first bytes are read for the
   signatures of executables (PE, ELF, Mach-O, Java class) — those are refused
   under any name — and a file whose extension claims a kind the platform
   serves inline (image, video, audio) is refused when its bytes are HTML or
   SVG, because an ``<svg onload>`` served as ``image/png`` is the cross-site
   scripting vector this product must never offer. Documents and other files
   are always served as downloads, so their bytes need no such check.
2. **Serving is decided elsewhere** (``attachment_policy``): documents and
   unknown files are ``Content-Disposition: attachment`` with a type derived
   from the extension, never from the client, and HTML/SVG are never inline.
   Unblocking ``.svg`` lets a person *store* one; it never lets the platform
   *render* one.

Everything that passes here still goes through ``upload_screening`` (archive
structure, ClamAV) before it is stored.

Files with no recognised kind get the kind ``file``: stored and downloadable,
text extracted when the bytes are text, otherwise handed to the model by name
and size only (and to the Code Interpreter workspace as bytes).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import PurePath

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SystemSetting
from app.services import attachment_policy as legacy

logger = logging.getLogger(__name__)

KEY_MODE = "upload_file_policy_mode"
KEY_BLOCKED = "upload_blocked_extensions"
KEY_ALLOWED = "upload_allowed_extensions"

MODE_BLOCKLIST = "blocklist"
MODE_ALLOWLIST = "allowlist"
MODES: tuple[str, ...] = (MODE_BLOCKLIST, MODE_ALLOWLIST)

#: The lists the product shipped with. The operator may edit them freely;
#: "Restore defaults" brings these back.
DEFAULT_BLOCKED: frozenset[str] = legacy.BLOCKED_EXTENSIONS
DEFAULT_ALLOWED: frozenset[str] = legacy.ALLOWED_EXTENSIONS

KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_AUDIO = "audio"
KIND_DOCUMENT = "document"
#: Anything the platform has no parser or player for. Stored, downloadable,
#: text-extracted when the bytes are text.
KIND_FILE = "file"
KINDS: tuple[str, ...] = (KIND_IMAGE, KIND_VIDEO, KIND_AUDIO, KIND_DOCUMENT, KIND_FILE)

#: Kinds the platform may serve with ``Content-Disposition: inline``. Only
#: these need their bytes checked against HTML/SVG.
INLINE_KINDS: frozenset[str] = frozenset({KIND_IMAGE, KIND_VIDEO, KIND_AUDIO})

EXTENSION_PATTERN = re.compile(r"^[a-z0-9]{1,16}$")
MAX_LIST_ENTRIES = 500
CACHE_TTL_SECONDS = 60.0

#: How much of a file the content check reads. Every signature this looks for
#: is in the first few hundred bytes; HTML/SVG markers are looked for a little
#: deeper because of leading whitespace, BOMs and XML prologues.
_SNIFF_BYTES = 4096


class UploadPolicyError(legacy.AttachmentPolicyError):
    """The file is refused. The message is safe to show to the person."""


@dataclass(frozen=True)
class Policy:
    mode: str = MODE_BLOCKLIST
    blocked: frozenset[str] = field(default_factory=lambda: DEFAULT_BLOCKED)
    allowed: frozenset[str] = field(default_factory=lambda: DEFAULT_ALLOWED)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "blocked": sorted(self.blocked),
            "allowed": sorted(self.allowed),
            "default_blocked": sorted(DEFAULT_BLOCKED),
            "default_allowed": sorted(DEFAULT_ALLOWED),
        }


DEFAULT_POLICY = Policy()


# --------------------------------------------------------------------------- #
# Normalisation of what an operator types
# --------------------------------------------------------------------------- #


def normalize_extension(value: str) -> str | None:
    """``".PDF "`` → ``"pdf"``; anything that is not a plain extension → None."""

    text = (value or "").strip().lower().lstrip(".").strip()
    return text if EXTENSION_PATTERN.match(text) else None


def normalize_extension_list(values: list[str] | tuple[str, ...] | frozenset[str]) -> tuple[list[str], list[str]]:
    """(accepted, rejected) — accepted is sorted and de-duplicated."""

    accepted: set[str] = set()
    rejected: list[str] = []
    for raw in values:
        ext = normalize_extension(str(raw))
        if ext is None:
            rejected.append(str(raw))
        else:
            accepted.add(ext)
    return sorted(accepted), rejected


def normalize_mode(value: str | None) -> str:
    text = (value or "").strip().lower()
    return text if text in MODES else MODE_BLOCKLIST


# --------------------------------------------------------------------------- #
# Loading and saving
# --------------------------------------------------------------------------- #

_cache: tuple[float, Policy] | None = None


def invalidate_policy_cache() -> None:
    global _cache
    _cache = None


def _parse_list(raw: str | None, default: frozenset[str]) -> frozenset[str]:
    if raw is None:
        return default
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("upload file policy: unreadable list in settings, using defaults")
        return default
    if not isinstance(parsed, list):
        return default
    # Only strings can be extensions; a hand-edited row with a number or a
    # null in it should lose that entry, not gain a nonsense one.
    accepted, _ = normalize_extension_list([v for v in parsed if isinstance(v, str)])
    return frozenset(accepted)


async def load_policy(db: AsyncSession, *, use_cache: bool = True) -> Policy:
    """The operator's policy, or the defaults when nothing has been saved.

    Cached per process for a minute: every upload asks, and the answer changes
    when an administrator saves — not between two files in one message.
    """

    global _cache
    if use_cache and _cache is not None and time.monotonic() - _cache[0] < CACHE_TTL_SECONDS:
        return _cache[1]
    mode_row = await db.get(SystemSetting, KEY_MODE)
    blocked_row = await db.get(SystemSetting, KEY_BLOCKED)
    allowed_row = await db.get(SystemSetting, KEY_ALLOWED)
    policy = Policy(
        mode=normalize_mode(mode_row.value if mode_row else None),
        blocked=_parse_list(blocked_row.value if blocked_row else None, DEFAULT_BLOCKED),
        allowed=_parse_list(allowed_row.value if allowed_row else None, DEFAULT_ALLOWED),
    )
    _cache = (time.monotonic(), policy)
    return policy


async def save_policy(db: AsyncSession, *, mode: str, blocked: list[str], allowed: list[str]) -> Policy:
    """Validate, store and return the saved policy. Flushes; the caller commits.

    Raises ``ValueError`` naming every entry that is not a plain extension, so
    the operator sees what was wrong rather than a silently shortened list.
    """

    if mode not in MODES:
        raise ValueError(f"Unknown mode '{mode}'. Use 'blocklist' or 'allowlist'.")
    blocked_ok, blocked_bad = normalize_extension_list(blocked)
    allowed_ok, allowed_bad = normalize_extension_list(allowed)
    bad = blocked_bad + allowed_bad
    if bad:
        shown = ", ".join(repr(b) for b in bad[:5])
        raise ValueError(f"Not a file extension: {shown}. Use letters and digits only, up to 16 characters.")
    if len(blocked_ok) > MAX_LIST_ENTRIES or len(allowed_ok) > MAX_LIST_ENTRIES:
        raise ValueError(f"A list may hold at most {MAX_LIST_ENTRIES} extensions.")

    for key, value in (
        (KEY_MODE, mode),
        (KEY_BLOCKED, json.dumps(blocked_ok)),
        (KEY_ALLOWED, json.dumps(allowed_ok)),
    ):
        row = await db.get(SystemSetting, key)
        if row:
            row.value = value
        else:
            db.add(SystemSetting(key=key, value=value))
    await db.flush()
    invalidate_policy_cache()
    return Policy(mode=mode, blocked=frozenset(blocked_ok), allowed=frozenset(allowed_ok))


async def reset_policy(db: AsyncSession) -> Policy:
    return await save_policy(db, mode=MODE_BLOCKLIST, blocked=sorted(DEFAULT_BLOCKED), allowed=sorted(DEFAULT_ALLOWED))


# --------------------------------------------------------------------------- #
# Deciding about a file
# --------------------------------------------------------------------------- #


def _suffixes(filename: str) -> list[str]:
    name = (filename or "").strip().replace("\\", "/")
    return [s.lstrip(".").lower() for s in PurePath(name).suffixes if s.lstrip(".")]


def kind_for_extension(ext: str) -> str:
    if ext in legacy.ALLOWED_IMAGE_EXTENSIONS:
        return KIND_IMAGE
    if ext in legacy.ALLOWED_VIDEO_EXTENSIONS:
        return KIND_VIDEO
    if ext in legacy.ALLOWED_AUDIO_EXTENSIONS:
        return KIND_AUDIO
    if ext in legacy.ALLOWED_DOCUMENT_EXTENSIONS:
        return KIND_DOCUMENT
    return KIND_FILE


def classify(filename: str, policy: Policy = DEFAULT_POLICY) -> tuple[str, str]:
    """(extension, kind) for a file the policy accepts; ``UploadPolicyError`` otherwise.

    Every suffix is checked against the blocklist, not only the last: a
    ``report.pdf.exe`` is an executable however it is dressed, and a
    ``photo.exe.jpg`` is a name chosen to get past a check that reads one
    suffix. The allowlist, when on, reads the last suffix only — that is the
    one that decides what the file *is*.
    """

    if not filename or not filename.strip():
        raise UploadPolicyError("Missing file name.")
    suffixes = _suffixes(filename)
    if not suffixes:
        raise UploadPolicyError("Files must have an extension.")
    for ext in suffixes:
        if ext in policy.blocked:
            raise UploadPolicyError(f'File type ".{ext}" is not allowed on this platform.')
    ext = suffixes[-1]
    if policy.mode == MODE_ALLOWLIST and ext not in policy.allowed:
        raise UploadPolicyError(f'File type ".{ext}" is not on the list of allowed file types.')
    return ext, kind_for_extension(ext)


_EXECUTABLE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"MZ", "a Windows executable"),
    (b"\x7fELF", "a Linux executable"),
    (b"\xfe\xed\xfa\xce", "a macOS executable"),
    (b"\xfe\xed\xfa\xcf", "a macOS executable"),
    (b"\xce\xfa\xed\xfe", "a macOS executable"),
    (b"\xcf\xfa\xed\xfe", "a macOS executable"),
    (b"\xca\xfe\xba\xbe", "a Java class or macOS universal binary"),
)

_MARKUP_MARKERS: tuple[bytes, ...] = (b"<svg", b"<!doctype html", b"<html", b"<script", b"<?xml")


def _looks_like_markup(head: bytes) -> bool:
    """HTML or SVG text, allowing a BOM, whitespace and an XML prologue."""

    text = head.lstrip(b"\xef\xbb\xbf\xff\xfe\xfe\xff").lstrip().lower()
    if not text.startswith(b"<"):
        return False
    return any(marker in text for marker in _MARKUP_MARKERS)


def check_content(raw: bytes, *, ext: str, kind: str) -> None:
    """Refuse a file whose bytes contradict its name. Not configurable.

    The lists say which *names* the operator accepts. This says the bytes
    behind the name must belong to it: no executable under any name, and no
    HTML or SVG behind a name the platform would serve inline.
    """

    head = bytes(raw[:_SNIFF_BYTES])
    if not head:
        raise UploadPolicyError("Empty file.")
    for signature, what in _EXECUTABLE_SIGNATURES:
        if head.startswith(signature):
            raise UploadPolicyError(f'"{ext}" file rejected: its contents are {what}.')
    if kind in INLINE_KINDS and _looks_like_markup(head):
        raise UploadPolicyError(f'"{ext}" file rejected: its contents are HTML or SVG, not {kind}.')
    if kind == KIND_IMAGE and ext not in ("ico",) and _detect_image_mime(head) is None and _looks_like_text(head):
        # An image whose bytes are plain text is not an image. Binary formats
        # this product does not sniff (HEIC variants, exotic TIFFs) pass; only
        # text pretending to be a picture is refused.
        raise UploadPolicyError(f'"{ext}" file rejected: its contents are not an image.')


def _detect_image_mime(head: bytes) -> str | None:
    from app.services.attachment_extract import _detect_image_mime as sniff

    return sniff(head)


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


async def check_upload(db: AsyncSession, *, filename: str, raw: bytes) -> tuple[str, str]:
    """The whole decision for one uploaded file: (extension, kind), or ``UploadPolicyError``."""

    policy = await load_policy(db)
    ext, kind = classify(filename, policy)
    check_content(raw, ext=ext, kind=kind)
    return ext, kind


async def classify_name(db: AsyncSession, filename: str) -> tuple[str, str]:
    """Name-only decision, for paths that have no bytes in hand (attaching from Media)."""

    return classify(filename, await load_policy(db))
