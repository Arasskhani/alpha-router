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

ALLOWED_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | ALLOWED_DOCUMENT_EXTENSIONS

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


class AttachmentPolicyError(ValueError):
    pass


def validate_attachment_filename(filename: str) -> tuple[str, str]:
    """Return (extension, kind) where kind is image|document."""
    if not filename or not filename.strip():
        raise AttachmentPolicyError("Missing file name.")

    for ext in _all_extensions(filename):
        if ext in BLOCKED_EXTENSIONS:
            raise AttachmentPolicyError(
                f'File type ".{ext}" is not allowed for security reasons.'
            )

    ext = _extension(filename)
    if not ext:
        raise AttachmentPolicyError("Files must have a recognized extension.")
    if ext in BLOCKED_EXTENSIONS:
        raise AttachmentPolicyError(f'File type ".{ext}" is not allowed for security reasons.')
    if ext not in ALLOWED_EXTENSIONS:
        raise AttachmentPolicyError(
            f'File type ".{ext}" is not supported. Use images (not SVG) or text documents.'
        )

    kind = "image" if ext in ALLOWED_IMAGE_EXTENSIONS else "document"
    return ext, kind


def validate_attachment_size(size: int) -> None:
    if size <= 0:
        raise AttachmentPolicyError("Empty file.")
    if size > MAX_ATTACHMENT_BYTES:
        raise AttachmentPolicyError(
            f"File is too large (max {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)."
        )
