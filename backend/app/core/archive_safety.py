"""Structural safety checks for ZIP-based Office documents (docx/xlsx/pptx).

Shared by Knowledge ingestion, chat attachments and project media so a
decompression bomb, a path-traversal entry, an encrypted member, embedded
macros or an external relationship is refused the same way wherever the
file arrives. Limits come from the ``knowledge_max_archive_*`` settings.
"""

from __future__ import annotations

import stat
import zipfile
from io import BytesIO
from pathlib import PurePosixPath

from app.config import get_settings

OOXML_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx", ".xlsm"})


class ArchiveSafetyError(ValueError):
    pass


def validate_ooxml_archive(data: bytes, extension: str) -> None:
    """Raise ArchiveSafetyError when the archive is malformed or dangerous."""
    settings = get_settings()
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveSafetyError("Office document is not a valid ZIP archive") from exc
    with archive:
        entries = archive.infolist()
        if len(entries) > settings.knowledge_max_archive_entries:
            raise ArchiveSafetyError("Office document contains too many archive entries")
        total_compressed = 0
        total_uncompressed = 0
        names: set[str] = set()
        for entry in entries:
            normalized = entry.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if not normalized or normalized.startswith("/") or ".." in path.parts or "\x00" in normalized:
                raise ArchiveSafetyError("Office document contains an unsafe archive path")
            mode = (entry.external_attr >> 16) & 0xFFFF
            if mode and stat.S_ISLNK(mode):
                raise ArchiveSafetyError("Office document contains a symbolic link")
            if entry.flag_bits & 0x1:
                raise ArchiveSafetyError("Encrypted Office documents are not supported")
            total_compressed += max(1, int(entry.compress_size or 0))
            total_uncompressed += int(entry.file_size or 0)
            names.add(normalized)
            lowered = normalized.casefold()
            if lowered.endswith("vbaproject.bin") or "/embeddings/" in lowered or lowered.startswith("customxml/"):
                raise ArchiveSafetyError("Active or embedded Office content is not allowed")
        if total_uncompressed > settings.knowledge_max_archive_uncompressed_bytes:
            raise ArchiveSafetyError("Office document expands beyond the allowed size")
        if (
            total_uncompressed > 0
            and total_uncompressed / max(1, total_compressed) > settings.knowledge_max_archive_ratio
        ):
            raise ArchiveSafetyError("Office document has an unsafe compression ratio")

        required = {
            ".docx": "word/document.xml",
            ".pptx": "ppt/presentation.xml",
            ".xlsx": "xl/workbook.xml",
            ".xlsm": "xl/workbook.xml",
        }.get(extension)
        if required is None:
            raise ArchiveSafetyError("Unsupported Office document type")
        if required not in names or "[Content_Types].xml" not in names:
            raise ArchiveSafetyError("Office document structure does not match its extension")

        for entry in entries:
            if not entry.filename.casefold().endswith(".rels"):
                continue
            relationship_xml = archive.read(entry)
            if b'TargetMode="External"' in relationship_xml or b"TargetMode='External'" in relationship_xml:
                raise ArchiveSafetyError("External Office document relationships are not allowed")
