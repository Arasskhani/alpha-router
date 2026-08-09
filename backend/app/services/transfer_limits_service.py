"""Global transfer size limits (upload / chat attachments total / ZIP download).

Stored as SystemSetting values in megabytes (and attachment count); applied to all users.
Also stores Code Interpreter workspace admission limits (file count / total MB).
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SystemSetting

_KEY_UPLOAD_MB = "max_upload_file_mb"
_KEY_CHAT_TOTAL_MB = "max_chat_attachments_total_mb"
_KEY_ZIP_MB = "max_media_zip_download_mb"
_KEY_CHAT_COUNT = "max_chat_attachments_count"
_KEY_CI_WORKSPACE_FILES = "max_code_interpreter_workspace_files"
_KEY_CI_WORKSPACE_TOTAL_MB = "max_code_interpreter_workspace_total_mb"

DEFAULT_UPLOAD_FILE_MB = 25
DEFAULT_CHAT_ATTACHMENTS_TOTAL_MB = 36
DEFAULT_MEDIA_ZIP_DOWNLOAD_MB = 256
DEFAULT_CHAT_ATTACHMENTS_COUNT = 5
DEFAULT_CI_WORKSPACE_TOTAL_MB = 16

MIN_UPLOAD_FILE_MB = 1
MAX_UPLOAD_FILE_MB = 1024
MIN_CHAT_ATTACHMENTS_TOTAL_MB = 1
MAX_CHAT_ATTACHMENTS_TOTAL_MB = 2048
MIN_MEDIA_ZIP_DOWNLOAD_MB = 1
MAX_MEDIA_ZIP_DOWNLOAD_MB = 8192  # keep below 10g container /tmp
MIN_CHAT_ATTACHMENTS_COUNT = 1
MAX_CHAT_ATTACHMENTS_COUNT = 500
MIN_CI_WORKSPACE_FILES = 1
MAX_CI_WORKSPACE_FILES = 500
MIN_CI_WORKSPACE_TOTAL_MB = 1
MAX_CI_WORKSPACE_TOTAL_MB = 64

_CACHE: tuple[float, dict[str, int]] | None = None
_CACHE_TTL_SEC = 30.0


def _mb_to_bytes(mb: int) -> int:
    return int(mb) * 1024 * 1024


def invalidate_transfer_limits_cache() -> None:
    global _CACHE
    _CACHE = None


def _clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _normalize_limits(
    upload_mb: int,
    chat_total_mb: int,
    zip_mb: int,
    attachments_count: int = DEFAULT_CHAT_ATTACHMENTS_COUNT,
    workspace_files: int | None = None,
    workspace_total_mb: int = DEFAULT_CI_WORKSPACE_TOTAL_MB,
) -> dict[str, int]:
    upload_mb = _clamp_int(upload_mb, minimum=MIN_UPLOAD_FILE_MB, maximum=MAX_UPLOAD_FILE_MB)
    chat_total_mb = _clamp_int(
        chat_total_mb,
        minimum=max(MIN_CHAT_ATTACHMENTS_TOTAL_MB, upload_mb),
        maximum=MAX_CHAT_ATTACHMENTS_TOTAL_MB,
    )
    zip_mb = _clamp_int(zip_mb, minimum=MIN_MEDIA_ZIP_DOWNLOAD_MB, maximum=MAX_MEDIA_ZIP_DOWNLOAD_MB)
    attachments_count = _clamp_int(
        attachments_count,
        minimum=MIN_CHAT_ATTACHMENTS_COUNT,
        maximum=MAX_CHAT_ATTACHMENTS_COUNT,
    )
    if workspace_files is None:
        workspace_files = attachments_count
    workspace_files = _clamp_int(
        workspace_files,
        minimum=MIN_CI_WORKSPACE_FILES,
        maximum=MAX_CI_WORKSPACE_FILES,
    )
    workspace_total_mb = _clamp_int(
        workspace_total_mb,
        minimum=MIN_CI_WORKSPACE_TOTAL_MB,
        maximum=MAX_CI_WORKSPACE_TOTAL_MB,
    )
    return {
        "max_upload_file_mb": upload_mb,
        "max_chat_attachments_total_mb": chat_total_mb,
        "max_media_zip_download_mb": zip_mb,
        "max_chat_attachments_count": attachments_count,
        "max_code_interpreter_workspace_files": workspace_files,
        "max_code_interpreter_workspace_total_mb": workspace_total_mb,
        "max_upload_file_bytes": _mb_to_bytes(upload_mb),
        "max_chat_attachments_total_bytes": _mb_to_bytes(chat_total_mb),
        "max_media_zip_download_bytes": _mb_to_bytes(zip_mb),
        "max_code_interpreter_workspace_total_bytes": _mb_to_bytes(workspace_total_mb),
    }


def _defaults_from_env() -> dict[str, int]:
    from app.config import get_settings

    settings = get_settings()
    upload_mb = max(1, int(round(settings.max_media_input_bytes / (1024 * 1024))) or DEFAULT_UPLOAD_FILE_MB)
    # Prefer media input as the unified single-file default; fall back sanely.
    if settings.max_attachment_bytes and settings.max_attachment_bytes < settings.max_media_input_bytes:
        # Keep unified single-file at media default when attaching was lower historically.
        pass
    chat_mb = max(
        upload_mb,
        int(round(settings.max_attachments_total_bytes / (1024 * 1024))) or DEFAULT_CHAT_ATTACHMENTS_TOTAL_MB,
    )
    zip_mb = max(
        1,
        int(round(settings.max_zip_aggregate_bytes / (1024 * 1024))) or DEFAULT_MEDIA_ZIP_DOWNLOAD_MB,
    )
    return _normalize_limits(upload_mb, chat_mb, zip_mb, DEFAULT_CHAT_ATTACHMENTS_COUNT)


def peek_cached_transfer_limits() -> dict[str, int] | None:
    global _CACHE
    if not _CACHE:
        return None
    ts, data = _CACHE
    if time.monotonic() - ts > _CACHE_TTL_SEC:
        return None
    return dict(data)


def cached_upload_limit_bytes() -> int:
    cached = peek_cached_transfer_limits()
    if cached:
        return int(cached["max_upload_file_bytes"])
    return int(_defaults_from_env()["max_upload_file_bytes"])


def cached_zip_aggregate_limit_bytes() -> int:
    cached = peek_cached_transfer_limits()
    if cached:
        return int(cached["max_media_zip_download_bytes"])
    return int(_defaults_from_env()["max_media_zip_download_bytes"])


def cached_chat_attachments_count() -> int:
    cached = peek_cached_transfer_limits()
    if cached:
        return int(cached["max_chat_attachments_count"])
    return int(_defaults_from_env()["max_chat_attachments_count"])


def _store_cache(data: dict[str, int]) -> dict[str, int]:
    global _CACHE
    _CACHE = (time.monotonic(), dict(data))
    return dict(data)


async def get_transfer_limits(db: AsyncSession) -> dict[str, int]:
    cached = peek_cached_transfer_limits()
    if cached:
        return cached

    from sqlalchemy import select

    rows = (
        await db.execute(
            select(SystemSetting).where(
                SystemSetting.key.in_(
                    [
                        _KEY_UPLOAD_MB,
                        _KEY_CHAT_TOTAL_MB,
                        _KEY_ZIP_MB,
                        _KEY_CHAT_COUNT,
                        _KEY_CI_WORKSPACE_FILES,
                        _KEY_CI_WORKSPACE_TOTAL_MB,
                    ]
                )
            )
        )
    ).scalars().all()
    kv = {r.key: (r.value or "").strip() for r in rows}
    defaults = _defaults_from_env()

    def _read(key: str, fallback: int) -> int:
        raw = kv.get(key, "")
        if not raw:
            return fallback
        try:
            return int(raw)
        except ValueError:
            return fallback

    attachments_count = _read(_KEY_CHAT_COUNT, defaults["max_chat_attachments_count"])
    # Inherit upload count when workspace file limit is not explicitly stored.
    raw_workspace_files = kv.get(_KEY_CI_WORKSPACE_FILES, "")
    if not raw_workspace_files:
        workspace_files: int | None = None
    else:
        try:
            workspace_files = int(raw_workspace_files)
        except ValueError:
            workspace_files = None

    data = _normalize_limits(
        _read(_KEY_UPLOAD_MB, defaults["max_upload_file_mb"]),
        _read(_KEY_CHAT_TOTAL_MB, defaults["max_chat_attachments_total_mb"]),
        _read(_KEY_ZIP_MB, defaults["max_media_zip_download_mb"]),
        attachments_count,
        workspace_files,
        _read(_KEY_CI_WORKSPACE_TOTAL_MB, DEFAULT_CI_WORKSPACE_TOTAL_MB),
    )
    return _store_cache(data)


async def set_transfer_limits(
    db: AsyncSession,
    *,
    max_upload_file_mb: int | None = None,
    max_chat_attachments_total_mb: int | None = None,
    max_media_zip_download_mb: int | None = None,
    max_chat_attachments_count: int | None = None,
    max_code_interpreter_workspace_files: int | None = None,
    max_code_interpreter_workspace_total_mb: int | None = None,
) -> dict[str, int]:
    current = await get_transfer_limits(db)
    upload_mb = (
        current["max_upload_file_mb"] if max_upload_file_mb is None else int(max_upload_file_mb)
    )
    chat_mb = (
        current["max_chat_attachments_total_mb"]
        if max_chat_attachments_total_mb is None
        else int(max_chat_attachments_total_mb)
    )
    zip_mb = (
        current["max_media_zip_download_mb"]
        if max_media_zip_download_mb is None
        else int(max_media_zip_download_mb)
    )
    attachments_count = (
        current["max_chat_attachments_count"]
        if max_chat_attachments_count is None
        else int(max_chat_attachments_count)
    )

    if max_upload_file_mb is not None:
        upload_mb = _clamp_int(upload_mb, minimum=MIN_UPLOAD_FILE_MB, maximum=MAX_UPLOAD_FILE_MB)
    if max_chat_attachments_total_mb is not None:
        chat_mb = _clamp_int(
            chat_mb,
            minimum=MIN_CHAT_ATTACHMENTS_TOTAL_MB,
            maximum=MAX_CHAT_ATTACHMENTS_TOTAL_MB,
        )
    if max_media_zip_download_mb is not None:
        zip_mb = _clamp_int(zip_mb, minimum=MIN_MEDIA_ZIP_DOWNLOAD_MB, maximum=MAX_MEDIA_ZIP_DOWNLOAD_MB)
    if max_chat_attachments_count is not None:
        attachments_count = _clamp_int(
            attachments_count,
            minimum=MIN_CHAT_ATTACHMENTS_COUNT,
            maximum=MAX_CHAT_ATTACHMENTS_COUNT,
        )

    existing_workspace_files = await db.get(SystemSetting, _KEY_CI_WORKSPACE_FILES)
    existing_workspace_total = await db.get(SystemSetting, _KEY_CI_WORKSPACE_TOTAL_MB)
    workspace_explicitly_stored = bool(
        existing_workspace_files and (existing_workspace_files.value or "").strip()
    )

    if max_code_interpreter_workspace_files is not None:
        workspace_files: int | None = _clamp_int(
            int(max_code_interpreter_workspace_files),
            minimum=MIN_CI_WORKSPACE_FILES,
            maximum=MAX_CI_WORKSPACE_FILES,
        )
        persist_workspace_files = True
    elif workspace_explicitly_stored:
        try:
            workspace_files = int((existing_workspace_files.value or "").strip())
        except ValueError:
            workspace_files = None
        persist_workspace_files = workspace_files is not None
    else:
        # Not stored → keep inheriting from attachments_count after this update.
        workspace_files = None
        persist_workspace_files = False

    if max_code_interpreter_workspace_total_mb is not None:
        workspace_total_mb = _clamp_int(
            int(max_code_interpreter_workspace_total_mb),
            minimum=MIN_CI_WORKSPACE_TOTAL_MB,
            maximum=MAX_CI_WORKSPACE_TOTAL_MB,
        )
        persist_workspace_total = True
    elif existing_workspace_total and (existing_workspace_total.value or "").strip():
        try:
            workspace_total_mb = int((existing_workspace_total.value or "").strip())
        except ValueError:
            workspace_total_mb = DEFAULT_CI_WORKSPACE_TOTAL_MB
        persist_workspace_total = True
    else:
        workspace_total_mb = DEFAULT_CI_WORKSPACE_TOTAL_MB
        persist_workspace_total = False

    if chat_mb < upload_mb:
        raise ValueError(
            f"Maximum chat attachments total ({chat_mb} MB) must be >= maximum upload size ({upload_mb} MB)."
        )

    data = _normalize_limits(
        upload_mb,
        chat_mb,
        zip_mb,
        attachments_count,
        workspace_files,
        workspace_total_mb,
    )
    updates = {
        _KEY_UPLOAD_MB: str(data["max_upload_file_mb"]),
        _KEY_CHAT_TOTAL_MB: str(data["max_chat_attachments_total_mb"]),
        _KEY_ZIP_MB: str(data["max_media_zip_download_mb"]),
        _KEY_CHAT_COUNT: str(data["max_chat_attachments_count"]),
    }
    if persist_workspace_files:
        updates[_KEY_CI_WORKSPACE_FILES] = str(data["max_code_interpreter_workspace_files"])
    if persist_workspace_total:
        updates[_KEY_CI_WORKSPACE_TOTAL_MB] = str(data["max_code_interpreter_workspace_total_mb"])

    for key, val in updates.items():
        row = await db.get(SystemSetting, key)
        if row:
            row.value = val
        else:
            db.add(SystemSetting(key=key, value=val))
    await db.flush()
    invalidate_transfer_limits_cache()
    return _store_cache(data)


def transfer_limits_public_view(data: dict[str, int]) -> dict[str, Any]:
    return {
        "max_upload_file_mb": data["max_upload_file_mb"],
        "max_chat_attachments_total_mb": data["max_chat_attachments_total_mb"],
        "max_media_zip_download_mb": data["max_media_zip_download_mb"],
        "max_chat_attachments_count": data["max_chat_attachments_count"],
        "max_code_interpreter_workspace_files": data["max_code_interpreter_workspace_files"],
        "max_code_interpreter_workspace_total_mb": data["max_code_interpreter_workspace_total_mb"],
        "max_upload_file_bytes": data["max_upload_file_bytes"],
        "max_chat_attachments_total_bytes": data["max_chat_attachments_total_bytes"],
        "max_media_zip_download_bytes": data["max_media_zip_download_bytes"],
        "max_code_interpreter_workspace_total_bytes": data["max_code_interpreter_workspace_total_bytes"],
    }
