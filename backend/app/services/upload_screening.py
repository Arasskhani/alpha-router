"""Screening every user upload gets before it is stored or parsed.

Knowledge documents have had this for a while (format validation, archive
bomb checks, ClamAV). Chat attachments, voice notes and project media went
straight from ``read_upload_bounded`` into object storage and the text
extractors. This module is the one place all of them call.

Order matters: the cheap structural check on Office archives runs first so a
decompression bomb never reaches the scanner or a parser; then the bytes go
to ClamAV. Fail-closed follows ``clamav_required`` exactly as Knowledge does.
"""

from __future__ import annotations

import logging
import os

from app.config import get_settings
from app.core.archive_safety import OOXML_EXTENSIONS, ArchiveSafetyError, validate_ooxml_archive
from app.services.malware_scan_service import (
    MalwareScanError,
    MalwareScannerUnavailable,
    scan_bytes,
)

logger = logging.getLogger(__name__)


class UploadRejected(ValueError):
    """The upload must not be stored. ``status_code`` is what the API answers."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _extension(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def check_archive_structure(raw: bytes, filename: str) -> None:
    ext = _extension(filename)
    if ext not in OOXML_EXTENSIONS:
        return
    try:
        validate_ooxml_archive(raw, ext)
    except ArchiveSafetyError as exc:
        raise UploadRejected(f"{os.path.basename(filename)}: {exc}", status_code=422) from exc


async def scan_for_malware(raw: bytes, filename: str) -> None:
    settings = get_settings()
    try:
        result = await scan_bytes(raw)
    except MalwareScannerUnavailable as exc:
        raise UploadRejected(
            "Malware scanning is unavailable; upload refused.", status_code=503
        ) from exc
    except MalwareScanError as exc:
        if settings.clamav_required:
            raise UploadRejected("Malware scan failed; upload refused.", status_code=503) from exc
        logger.warning("malware scan error ignored (clamav_required=false): %s", exc)
        return
    if not result.clean:
        logger.warning(
            "upload rejected by malware scan: file=%s signature=%s",
            os.path.basename(filename),
            result.signature,
        )
        raise UploadRejected("Upload rejected: the file matched a malware signature.", status_code=422)
    if result.skipped:
        logger.info("malware scan skipped for %s (scanner unavailable, not required)", os.path.basename(filename))


async def screen_upload(raw: bytes, filename: str) -> None:
    """Run every check. Raises UploadRejected; returns None when the bytes may be kept."""
    check_archive_structure(raw, filename)
    await scan_for_malware(raw, filename)
