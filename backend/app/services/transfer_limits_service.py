"""Global transfer size limits (upload / chat attachments total / ZIP download).

Stored as SystemSetting values in megabytes; applied to all users.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import SystemSetting

_KEY_UPLOAD_MB = "max_upload_file_mb"
_KEY_CHAT_TOTAL_MB = "max_chat_attachments_total_mb"
_KEY_ZIP_MB = "max_media_zip_download_mb"

DEFAULT_UPLOAD_FILE_MB = 25
DEFAULT_CHAT_ATTACHMENTS_TOTAL_MB = 36
DEFAULT_MEDIA_ZIP_DOWNLOAD_MB = 256

MIN_UPLOAD_FILE_MB = 1
MAX_UPLOAD_FILE_MB = 1024
MIN_CHAT_ATTACHMENTS_TOTAL_MB = 1
MAX_CHAT_ATTACHMENTS_TOTAL_MB = 2048
MIN_MEDIA_ZIP_DOWNLOAD_MB = 1
MAX_MEDIA_ZIP_DOWNLOAD_MB = 8192  # keep below 10g container /tmp

_CACHE: tuple[float, dict[str, int]] | None = None
_CACHE_TTL_SEC = 30.0


def _mb_to_bytes(mb: int) -> int:
    return int(mb) * 1024 * 1024


def invalidate_transfer_limits_cache() -> None:
    global _CACHE
    _CACHE = None


def _clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _normalize_limits(upload_mb: int, chat_total_mb: int, zip_mb: int) -> dict[str, int]:
    upload_mb = _clamp_int(upload_mb, minimum=MIN_UPLOAD_FILE_MB, maximum=MAX_UPLOAD_FILE_MB)
    chat_total_mb = _clamp_int(
        chat_total_mb,
        minimum=max(MIN_CHAT_ATTACHMENTS_TOTAL_MB, upload_mb),
        maximum=MAX_CHAT_ATTACHMENTS_TOTAL_MB,
    )
    zip_mb = _clamp_int(zip_mb, minimum=MIN_MEDIA_ZIP_DOWNLOAD_MB, maximum=MAX_MEDIA_ZIP_DOWNLOAD_MB)
    return {
        "max_upload_file_mb": upload_mb,
        "max_chat_attachments_total_mb": chat_total_mb,
        "max_media_zip_download_mb": zip_mb,
        "max_upload_file_bytes": _mb_to_bytes(upload_mb),
        "max_chat_attachments_total_bytes": _mb_to_bytes(chat_total_mb),
        "max_media_zip_download_bytes": _mb_to_bytes(zip_mb),
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
    return _normalize_limits(upload_mb, chat_mb, zip_mb)


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
                SystemSetting.key.in_([_KEY_UPLOAD_MB, _KEY_CHAT_TOTAL_MB, _KEY_ZIP_MB])
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

    data = _normalize_limits(
        _read(_KEY_UPLOAD_MB, defaults["max_upload_file_mb"]),
        _read(_KEY_CHAT_TOTAL_MB, defaults["max_chat_attachments_total_mb"]),
        _read(_KEY_ZIP_MB, defaults["max_media_zip_download_mb"]),
    )
    return _store_cache(data)


async def set_transfer_limits(
    db: AsyncSession,
    *,
    max_upload_file_mb: int | None = None,
    max_chat_attachments_total_mb: int | None = None,
    max_media_zip_download_mb: int | None = None,
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

    if chat_mb < upload_mb:
        raise ValueError(
            f"Maximum chat attachments total ({chat_mb} MB) must be >= maximum upload size ({upload_mb} MB)."
        )

    data = _normalize_limits(upload_mb, chat_mb, zip_mb)
    updates = {
        _KEY_UPLOAD_MB: str(data["max_upload_file_mb"]),
        _KEY_CHAT_TOTAL_MB: str(data["max_chat_attachments_total_mb"]),
        _KEY_ZIP_MB: str(data["max_media_zip_download_mb"]),
    }
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
        "max_upload_file_bytes": data["max_upload_file_bytes"],
        "max_chat_attachments_total_bytes": data["max_chat_attachments_total_bytes"],
        "max_media_zip_download_bytes": data["max_media_zip_download_bytes"],
    }
