"""Time- and memory-bounded subprocess wrapper for untrusted document parsers."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import site
import subprocess
import sys
import tempfile
from pathlib import Path

from app.config import get_settings
from app.services.knowledge_file_service import (
    ParsedDocument,
    ParsedSegment,
    UnsafeDocumentError,
    ValidatedDocument,
)


class ParserSandboxError(RuntimeError):
    pass


_DEFAULT_SETTINGS = get_settings()
_PARSER_MEMORY_LIMIT = max(
    256 * 1024 * 1024,
    int(_DEFAULT_SETTINGS.knowledge_parser_memory_bytes),
)
_PARSER_CPU_LIMIT = max(30, int(_DEFAULT_SETTINGS.knowledge_parser_cpu_seconds))
_PARSER_OUTPUT_LIMIT = int(_DEFAULT_SETTINGS.knowledge_parser_max_output_bytes)


def _resource_limits() -> None:
    if os.name == "nt":
        return
    import resource

    resource.setrlimit(
        resource.RLIMIT_AS,
        (_PARSER_MEMORY_LIMIT, _PARSER_MEMORY_LIMIT),
    )
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (_PARSER_CPU_LIMIT, _PARSER_CPU_LIMIT + 5),
    )
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (
            _PARSER_OUTPUT_LIMIT,
            _PARSER_OUTPUT_LIMIT,
        ),
    )


def _sandbox_environment() -> dict[str, str]:
    settings = get_settings()
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(
            [*site.getsitepackages(), site.getusersitepackages()]
        ),
        "KNOWLEDGE_MAX_UPLOAD_BYTES": str(settings.knowledge_max_upload_bytes),
        "KNOWLEDGE_MAX_ARCHIVE_ENTRIES": str(settings.knowledge_max_archive_entries),
        "KNOWLEDGE_MAX_ARCHIVE_UNCOMPRESSED_BYTES": str(
            settings.knowledge_max_archive_uncompressed_bytes
        ),
        "KNOWLEDGE_MAX_ARCHIVE_RATIO": str(settings.knowledge_max_archive_ratio),
        "KNOWLEDGE_MAX_DOCUMENT_CHARACTERS": str(
            settings.knowledge_max_document_characters
        ),
        "KNOWLEDGE_MAX_PDF_PAGES": str(settings.knowledge_max_pdf_pages),
        "KNOWLEDGE_OCR_REQUIRED": "true"
        if settings.knowledge_ocr_required
        else "false",
        "KNOWLEDGE_OCR_LANGUAGES": settings.knowledge_ocr_languages,
        "KNOWLEDGE_OCR_DPI": str(settings.knowledge_ocr_dpi),
        "KNOWLEDGE_OCR_PAGE_TIMEOUT_SECONDS": str(
            settings.knowledge_ocr_page_timeout_seconds
        ),
        "KNOWLEDGE_OCR_MAX_PAGES": str(settings.knowledge_ocr_max_pages),
        "KNOWLEDGE_OCR_MIN_TEXT_CHARACTERS": str(
            settings.knowledge_ocr_min_text_characters
        ),
    }
    for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TESSDATA_PREFIX"):
        if os.environ.get(key):
            environment[key] = os.environ[key]
    return environment


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    await process.wait()


async def parse_document_in_sandbox(
    data: bytes,
    document: ValidatedDocument,
) -> ParsedDocument:
    settings = get_settings()
    script = Path(__file__).with_name("knowledge_parser_runner.py")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="alpharouter-parser-") as temp_dir:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            "--file-name",
            document.file_name,
            "--mime-type",
            document.mime_type,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=temp_dir,
            env=_sandbox_environment(),
            preexec_fn=_resource_limits if os.name != "nt" else None,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=data),
                timeout=max(10, settings.knowledge_parser_timeout_seconds),
            )
        except TimeoutError as exc:
            await _terminate_process(process)
            raise ParserSandboxError("Document parser exceeded its time limit") from exc
    if len(stdout) > settings.knowledge_parser_max_output_bytes:
        raise ParserSandboxError("Document parser output exceeded its size limit")
    error_text = stderr.decode("utf-8", errors="replace")[-2000:]
    if process.returncode == 3:
        message = error_text.split("UNSAFE:", 1)[-1].strip()
        raise UnsafeDocumentError(message or "Document parser rejected the source")
    if process.returncode != 0:
        raise ParserSandboxError(
            f"Document parser process failed ({error_text[:500] or 'no details'})"
        )
    try:
        payload = json.loads(stdout)
        raw_segments = payload["segments"]
        if not isinstance(raw_segments, list) or len(raw_segments) > 100_000:
            raise ValueError("invalid segment list")
        segments = tuple(
            ParsedSegment(
                text=str(item["text"]),
                page_number=(
                    int(item["page_number"])
                    if item.get("page_number") is not None
                    else None
                ),
                section=(
                    str(item["section"])[:512]
                    if item.get("section") is not None
                    else None
                ),
            )
            for item in raw_segments
        )
        character_count = int(payload["character_count"])
        if character_count != sum(len(segment.text) for segment in segments):
            raise ValueError("character count mismatch")
        if character_count > settings.knowledge_max_document_characters:
            raise ValueError("character limit exceeded")
        metadata = payload.get("metadata")
        security_flags = payload.get("security_flags")
        if not isinstance(metadata, dict) or not isinstance(security_flags, list):
            raise ValueError("invalid parser metadata")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ParserSandboxError("Document parser returned an invalid result") from exc
    return ParsedDocument(
        segments=segments,
        character_count=character_count,
        metadata=metadata,
        security_flags=tuple(str(flag)[:255] for flag in security_flags[:100]),
    )
