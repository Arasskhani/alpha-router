"""Allowlist / blocklist for chat file attachments."""

from __future__ import annotations

from pathlib import PurePath

# Never allow — executables, scripts, web content, archives, shortcuts, etc.
BLOCKED_EXTENSIONS: frozenset[str] = frozenset(
    {
        "apk",
        "app",
        "application",
        "asp",
        "aspx",
        "bat",
        "bin",
        "cab",
        "cmd",
        "com",
        "cpl",
        "crt",
        "deb",
        "dll",
        "dmg",
        "exe",
        "gadget",
        "hta",
        "htm",
        "html",
        "inf",
        "ins",
        "iso",
        "jar",
        "js",
        "jse",
        "jsp",
        "lnk",
        "mjs",
        "msc",
        "msi",
        "msp",
        "mst",
        "php",
        "pif",
        "ps1",
        "psm1",
        "py",
        "pyc",
        "pyo",
        "pyw",
        "rb",
        "reg",
        "rpm",
        "scr",
        "sh",
        "svg",
        "svgz",
        "swf",
        "tar",
        "vb",
        "vbe",
        "vbs",
        "ws",
        "wsc",
        "wsf",
        "wsh",
        "xhtml",
        "7z",
        "rar",
        "zip",
        "gz",
        "bz2",
        "xz",
        "z",
        "url",
        "desktop",
        "lnk",
        "torrent",
        "wasm",
        "elf",
        "so",
        "dylib",
        "sys",
        "drv",
        "ocx",
        "cpl",
        "hta",
        "xht",
        "shtml",
        "mht",
        "mhtml",
    }
)

ALLOWED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
        "bmp",
        "tif",
        "tiff",
        "heic",
        "heif",
        "avif",
        "ico",
    }
)

ALLOWED_VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        "mp4",
        "m4v",
        "mov",
        "mkv",
        "webm",
        "avi",
        "wmv",
        "flv",
        "mpeg",
        "mpg",
        "mpe",
        "mp2",
        "m2v",
        "3gp",
        "3g2",
        "ts",
        "m2ts",
        "mts",
        "ogv",
        "vob",
    }
)

ALLOWED_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {
        "mp3",
        "ogg",
        "oga",
        "opus",
        "wav",
        "flac",
        "aac",
        "m4a",
        "wma",
        "aiff",
        "aif",
        "aifc",
        "mid",
        "midi",
        "weba",
        "amr",
        "caf",
    }
)

ALLOWED_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "xlsm",
        "csv",
        "tsv",
        "txt",
        "text",
        "md",
        "markdown",
        "rtf",
        "odt",
        "ods",
        "odp",
        "ppt",
        "pptx",
        "json",
        "yaml",
        "yml",
        "xml",
        "log",
        "ini",
        "cfg",
        "conf",
        "tex",
        "rst",
        "sql",
        "toml",
        "properties",
    }
)

ALLOWED_EXTENSIONS = (
    ALLOWED_IMAGE_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS | ALLOWED_AUDIO_EXTENSIONS | ALLOWED_DOCUMENT_EXTENSIONS
)

# Extension → MIME for documents. Client Content-Type is never trusted for these.
DOCUMENT_MIME_BY_EXTENSION: dict[str, str] = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "txt": "text/plain",
    "text": "text/plain",
    "md": "text/plain",
    "markdown": "text/plain",
    "rtf": "application/rtf",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "json": "application/json",
    "yaml": "application/yaml",
    "yml": "application/yaml",
    "xml": "application/xml",
    "log": "text/plain",
    "ini": "text/plain",
    "cfg": "text/plain",
    "conf": "text/plain",
    "tex": "text/plain",
    "rst": "text/plain",
    "sql": "text/plain",
    "toml": "application/toml",
    "properties": "text/plain",
}

IMAGE_MIME_BY_EXTENSION: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "heic": "image/heic",
    "heif": "image/heif",
    "avif": "image/avif",
    "ico": "image/x-icon",
}

VIDEO_MIME_BY_EXTENSION: dict[str, str] = {
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
    "avi": "video/x-msvideo",
    "wmv": "video/x-ms-wmv",
    "flv": "video/x-flv",
    "mpeg": "video/mpeg",
    "mpg": "video/mpeg",
    "mpe": "video/mpeg",
    "mp2": "video/mpeg",
    "m2v": "video/mpeg",
    "3gp": "video/3gpp",
    "3g2": "video/3gpp2",
    "ts": "video/mp2t",
    "m2ts": "video/mp2t",
    "mts": "video/mp2t",
    "ogv": "video/ogg",
    "vob": "video/mpeg",
}

AUDIO_MIME_BY_EXTENSION: dict[str, str] = {
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/opus",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "aac": "audio/aac",
    "m4a": "audio/mp4",
    "wma": "audio/x-ms-wma",
    "aiff": "audio/aiff",
    "aif": "audio/aiff",
    "aifc": "audio/aiff",
    "mid": "audio/midi",
    "midi": "audio/midi",
    "weba": "audio/webm",
    "amr": "audio/amr",
    "caf": "audio/x-caf",
}

# Video MIME types safe enough to serve inline for <video> playback.
INLINE_VIDEO_MIMES: frozenset[str] = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "video/x-matroska",
        "video/ogg",
        "video/x-msvideo",
        "video/mpeg",
        "video/3gpp",
        "video/3gpp2",
        "video/mp2t",
        "video/x-ms-wmv",
        "video/x-flv",
    }
)

# Never store or serve these as Content-Type (XSS / script execution risk).
UNSAFE_MEDIA_MIMES: frozenset[str] = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/javascript",
        "application/javascript",
        "application/x-javascript",
        "text/jscript",
        "text/vbscript",
        "application/x-httpd-php",
        "text/x-python",
        "application/x-python-code",
        "text/x-sh",
        "application/x-sh",
        "application/x-msdownload",
    }
)

MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
MAX_ATTACHMENTS_PER_REQUEST = 5


def _extension(filename: str) -> str:
    name = (filename or "").strip().replace("\\", "/")
    parts = PurePath(name).suffixes
    if not parts:
        return ""
    return parts[-1].lstrip(".").lower()


def _all_extensions(filename: str) -> list[str]:
    name = (filename or "").strip().replace("\\", "/")
    return [s.lstrip(".").lower() for s in PurePath(name).suffixes if s]


def _normalize_mime(value: str | None) -> str:
    return (value or "").split(";")[0].strip().lower()


class AttachmentPolicyError(ValueError):
    pass


def validate_attachment_filename(filename: str) -> tuple[str, str]:
    """Return (extension, kind) where kind is image|video|audio|document."""
    if not filename or not filename.strip():
        raise AttachmentPolicyError("Missing file name.")

    for ext in _all_extensions(filename):
        if ext in BLOCKED_EXTENSIONS:
            raise AttachmentPolicyError(f'File type ".{ext}" is not allowed for security reasons.')

    ext = _extension(filename)
    if not ext:
        raise AttachmentPolicyError("Files must have a recognized extension.")
    if ext in BLOCKED_EXTENSIONS:
        raise AttachmentPolicyError(f'File type ".{ext}" is not allowed for security reasons.')
    if ext not in ALLOWED_EXTENSIONS:
        raise AttachmentPolicyError(
            f'File type ".{ext}" is not supported. Use images, video, audio, or text documents.'
        )

    if ext in ALLOWED_IMAGE_EXTENSIONS:
        kind = "image"
    elif ext in ALLOWED_VIDEO_EXTENSIONS:
        kind = "video"
    elif ext in ALLOWED_AUDIO_EXTENSIONS:
        kind = "audio"
    else:
        kind = "document"
    return ext, kind


def validate_attachment_size(size: int, *, max_bytes: int | None = None) -> None:
    if size <= 0:
        raise AttachmentPolicyError("Empty file.")
    limit = int(max_bytes) if max_bytes is not None else MAX_ATTACHMENT_BYTES
    if limit <= 0:
        limit = MAX_ATTACHMENT_BYTES
    if size > limit:
        raise AttachmentPolicyError(f"File is too large (max {max(1, limit // (1024 * 1024))} MB).")


def resolve_attachment_mime(
    *,
    filename: str,
    kind: str,
    client_mime: str | None = None,
) -> str:
    """Derive a safe MIME for storage. Document uploads ignore client Content-Type."""
    ext = _extension(filename)
    kind_norm = (kind or "").strip().lower()
    client = _normalize_mime(client_mime)

    if kind_norm == "image":
        mapped = IMAGE_MIME_BY_EXTENSION.get(ext)
        if mapped:
            return mapped
        if client.startswith("image/") and client not in UNSAFE_MEDIA_MIMES:
            return client
        return "application/octet-stream"

    if kind_norm == "video":
        mapped = VIDEO_MIME_BY_EXTENSION.get(ext)
        if mapped:
            return mapped
        if client.startswith("video/") and client not in UNSAFE_MEDIA_MIMES:
            return client
        return "video/mp4"

    if kind_norm == "audio":
        mapped = AUDIO_MIME_BY_EXTENSION.get(ext)
        if mapped:
            return mapped
        if client.startswith("audio/") and client not in UNSAFE_MEDIA_MIMES:
            return client
        return "audio/mpeg"

    # Documents and anything else: extension map only; never trust client.
    mapped = DOCUMENT_MIME_BY_EXTENSION.get(ext)
    if mapped and mapped not in UNSAFE_MEDIA_MIMES:
        return mapped
    return "application/octet-stream"


def coerce_safe_storage_mime(kind: str, mime: str | None) -> str:
    """Strip unsafe MIME types before persistence (defense in depth)."""
    kind_norm = (kind or "").strip().lower()
    cleaned = _normalize_mime(mime) or "application/octet-stream"
    if cleaned in UNSAFE_MEDIA_MIMES:
        return "application/octet-stream"
    if kind_norm == "document" and cleaned.startswith("text/html"):
        return "application/octet-stream"
    if kind_norm == "image" and cleaned == "image/svg+xml":
        return "application/octet-stream"
    if kind_norm == "video":
        if cleaned in INLINE_VIDEO_MIMES or cleaned.startswith("video/"):
            return cleaned if cleaned.startswith("video/") else "video/mp4"
        return "application/octet-stream"
    if kind_norm == "audio" and cleaned not in INLINE_AUDIO_MIMES:
        if cleaned.startswith("audio/"):
            return "audio/mpeg"
        return "application/octet-stream"
    return cleaned


def is_inline_image_media(*, kind: str | None, mime: str | None) -> bool:
    """True when the asset may be served with Content-Disposition: inline."""
    kind_norm = (kind or "").strip().lower()
    cleaned = _normalize_mime(mime)
    if cleaned in UNSAFE_MEDIA_MIMES:
        return False
    if kind_norm in {"document", "video", "audio"}:
        return False
    if kind_norm == "image":
        return cleaned.startswith("image/") or not cleaned
    return cleaned.startswith("image/")


def is_inline_video_media(*, kind: str | None, mime: str | None) -> bool:
    kind_norm = (kind or "").strip().lower()
    cleaned = _normalize_mime(mime)
    if cleaned in UNSAFE_MEDIA_MIMES:
        return False
    if kind_norm in {"document", "image", "audio"}:
        return False
    if kind_norm == "video":
        return cleaned in INLINE_VIDEO_MIMES or cleaned.startswith("video/")
    return cleaned in INLINE_VIDEO_MIMES or cleaned in {"video/mp4", "video/webm"}


# Audio MIME types safe to serve inline (for <audio> playback).
INLINE_AUDIO_MIMES: frozenset[str] = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/ogg",
        "audio/webm",
        "audio/flac",
        "audio/aac",
        "audio/x-aac",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
    }
)


def is_inline_audio_media(*, kind: str | None, mime: str | None) -> bool:
    """True when the asset may be served with Content-Disposition: inline."""
    kind_norm = (kind or "").strip().lower()
    cleaned = _normalize_mime(mime)
    if cleaned in UNSAFE_MEDIA_MIMES:
        return False
    if kind_norm in {"document", "image", "video"}:
        return False
    if kind_norm == "audio":
        return cleaned in INLINE_AUDIO_MIMES or cleaned.startswith("audio/")
    return cleaned in INLINE_AUDIO_MIMES


def build_media_content_disposition(file_name: str, *, disposition: str) -> str:
    """RFC 6266 Content-Disposition with ASCII fallback + UTF-8 filename*."""
    from urllib.parse import quote

    disp = disposition if disposition in ("inline", "attachment") else "attachment"
    raw = (file_name or "download").replace("\\", "/").split("/")[-1]
    raw = raw.replace("\r", "").replace("\n", "").replace('"', "").strip() or "download"
    ascii_name = ("".join(c for c in raw if (c.isascii() and c.isalnum()) or c in "-_.") or "download")[:80]
    utf8_name = quote(raw[:120], safe="")
    return f"{disp}; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


def media_response_type_and_disposition(
    *,
    file_name: str,
    kind: str | None,
    stored_mime: str | None,
) -> tuple[str, str]:
    """Safe (media_type, Content-Disposition) for GET media file responses."""
    kind_norm = (kind or "").strip().lower()
    stored = _normalize_mime(stored_mime)

    if is_inline_image_media(kind=kind_norm, mime=stored):
        mime = (
            stored
            if stored.startswith("image/")
            else resolve_attachment_mime(filename=file_name, kind="image", client_mime=stored)
        )
        if mime in UNSAFE_MEDIA_MIMES or not mime.startswith("image/"):
            return (
                "application/octet-stream",
                build_media_content_disposition(file_name, disposition="attachment"),
            )
        return mime, build_media_content_disposition(file_name, disposition="inline")

    if is_inline_video_media(kind=kind_norm, mime=stored):
        mime = stored if stored.startswith("video/") else "video/mp4"
        if mime not in INLINE_VIDEO_MIMES and not mime.startswith("video/"):
            mime = "video/mp4"
        return mime, build_media_content_disposition(file_name, disposition="inline")

    if is_inline_audio_media(kind=kind_norm, mime=stored):
        mime = stored if stored.startswith("audio/") else "audio/mpeg"
        if mime not in INLINE_AUDIO_MIMES and not mime.startswith("audio/"):
            mime = "audio/mpeg"
        return mime, build_media_content_disposition(file_name, disposition="inline")

    # Documents / unknown / legacy unsafe MIME: force download + extension-derived type.
    mime = resolve_attachment_mime(filename=file_name, kind="document", client_mime=None)
    return mime, build_media_content_disposition(file_name, disposition="attachment")
