"""Media storage helpers, retention, and object storage (SeaweedFS/S3)."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import hashlib
import json
import logging
import time
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import MediaAsset
from app.models.system import SystemSetting
from app.models.user import User
from app.services import object_storage_service as oss

logger = logging.getLogger(__name__)

_KEY_RETENTION_DAYS = "storage_retention_days"
_KEY_CLEAR_SCHEDULE_ENABLED = "storage_clear_schedule_enabled"
_KEY_CLEAR_SCHEDULE_HOUR = "storage_clear_schedule_hour"
_KEY_CLEAR_SCHEDULE_MINUTE = "storage_clear_schedule_minute"
_RETENTION_CACHE: tuple[float, int] | None = None
MAX_MEDIA_INPUT_BYTES = 25 * 1024 * 1024


def media_input_limit() -> int:
    """Single-file upload/media limit (bytes). Prefers admin transfer-limits cache."""
    from app.services.bounded_io import clamp_limit
    from app.services.transfer_limits_service import (
        MAX_UPLOAD_FILE_MB,
        cached_upload_limit_bytes,
    )

    return clamp_limit(
        cached_upload_limit_bytes(),
        minimum=1024 * 1024,
        maximum=MAX_UPLOAD_FILE_MB * 1024 * 1024,
    )


def _ext_from_mime(mime: str) -> str:
    m = (mime or "").lower()
    if "png" in m:
        return ".png"
    if "jpeg" in m or "jpg" in m:
        return ".jpg"
    if "webp" in m:
        return ".webp"
    if "gif" in m:
        return ".gif"
    if "pdf" in m:
        return ".pdf"
    if "csv" in m:
        return ".csv"
    if "sheet" in m or "excel" in m:
        return ".xlsx"
    if "word" in m:
        return ".docx"
    if "text/plain" in m:
        return ".txt"
    if "webm" in m:
        return ".webm"
    if "ogg" in m:
        return ".ogg"
    if "mpeg" in m or "mp3" in m:
        return ".mp3"
    if "wav" in m:
        return ".wav"
    if "mp4" in m or "m4a" in m:
        return ".m4a"
    return ".bin"


def _sanitize_name(name: str | None, fallback: str) -> str:
    base = (name or "").strip()
    if not base:
        return fallback
    return "".join(ch for ch in base if ch.isalnum() or ch in ("-", "_", ".", " ")).strip() or fallback


async def get_retention_days_cached(db: AsyncSession) -> int:
    global _RETENTION_CACHE
    now = time.monotonic()
    if _RETENTION_CACHE and now - _RETENTION_CACHE[0] < 300.0:
        return _RETENTION_CACHE[1]
    settings = await get_storage_settings(db)
    days = max(1, int(settings["retention_days"]))
    _RETENTION_CACHE = (now, days)
    return days


async def get_storage_settings(db: AsyncSession) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(SystemSetting).where(
                SystemSetting.key.in_(
                    [
                        _KEY_RETENTION_DAYS,
                        _KEY_CLEAR_SCHEDULE_ENABLED,
                        _KEY_CLEAR_SCHEDULE_HOUR,
                        _KEY_CLEAR_SCHEDULE_MINUTE,
                    ]
                )
            )
        )
    ).scalars().all()
    kv = {r.key: (r.value or "") for r in rows}
    retention_days = int(kv.get(_KEY_RETENTION_DAYS, "30") or 30)
    schedule_enabled = (kv.get(_KEY_CLEAR_SCHEDULE_ENABLED, "true") or "true").lower() in ("1", "true", "yes", "on")
    schedule_hour = max(0, min(23, int(kv.get(_KEY_CLEAR_SCHEDULE_HOUR, "3") or 3)))
    schedule_minute = max(0, min(59, int(kv.get(_KEY_CLEAR_SCHEDULE_MINUTE, "0") or 0)))
    return {
        "retention_days": retention_days,
        "clear_schedule_enabled": schedule_enabled,
        "clear_schedule_hour": schedule_hour,
        "clear_schedule_minute": schedule_minute,
    }


async def set_storage_settings(
    db: AsyncSession,
    *,
    retention_days: int | None = None,
    clear_schedule_enabled: bool | None = None,
    clear_schedule_hour: int | None = None,
    clear_schedule_minute: int | None = None,
) -> dict[str, Any]:
    updates: dict[str, str] = {}
    if retention_days is not None:
        updates[_KEY_RETENTION_DAYS] = str(max(1, retention_days))
    if clear_schedule_enabled is not None:
        updates[_KEY_CLEAR_SCHEDULE_ENABLED] = "true" if clear_schedule_enabled else "false"
    if clear_schedule_hour is not None:
        updates[_KEY_CLEAR_SCHEDULE_HOUR] = str(max(0, min(23, clear_schedule_hour)))
    if clear_schedule_minute is not None:
        updates[_KEY_CLEAR_SCHEDULE_MINUTE] = str(max(0, min(59, clear_schedule_minute)))

    for key, val in updates.items():
        row = await db.get(SystemSetting, key)
        if row:
            row.value = val
        else:
            db.add(SystemSetting(key=key, value=val))
    await db.flush()
    return await get_storage_settings(db)


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    from app.services.bounded_io import decode_data_url_bounded

    return decode_data_url_bounded(data_url, max_decoded_bytes=media_input_limit())


async def _download_url(url: str) -> tuple[bytes, str]:
    from app.services.bounded_io import bounded_get_bytes
    from app.services.ssrf_guard import safe_client

    async with safe_client() as client:
        return await bounded_get_bytes(client, url, max_bytes=media_input_limit())


async def resolve_media_blob(
    *,
    data_url: str | None = None,
    source_url: str | None = None,
) -> tuple[bytes, str]:
    """Load media bytes from a data URL or remote URL."""
    if data_url:
        return await asyncio.to_thread(_decode_data_url, data_url)
    if source_url:
        return await _download_url(source_url)
    raise ValueError("Either data_url or source_url is required")


def sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def user_storage_slug(username: str | None) -> str:
    return _sanitize_username_dir(username or "unknown")


def normalize_image_for_storage(blob: bytes, mime: str) -> tuple[bytes, str, str] | None:
    """Decode to RGB pixels; store as PNG; digest from pixel grid (not file bytes)."""
    del mime
    from app.services.image_decode_policy import normalize_image

    return normalize_image(blob)


def media_content_hash(blob: bytes, mime: str, kind: str) -> tuple[bytes, str, str]:
    """Return storage bytes, MIME, and SHA-256 hex (pixel-normalized for images)."""
    if kind == "image" or (mime or "").lower().startswith("image/"):
        normalized = normalize_image_for_storage(blob, mime)
        if normalized:
            storage_blob, storage_mime, digest = normalized
            return storage_blob, storage_mime, digest
    return blob, mime, sha256_hex(blob)


def object_key_for_user_media(username: str | None, content_hash: str, ext: str) -> str:
    return oss.media_object_key(user_storage_slug(username), content_hash, ext)


def _sanitize_username_dir(username: str) -> str:
    raw = (username or "").strip()
    if not raw:
        return "unknown"
    safe = "".join(ch for ch in raw if ch.isalnum() or ch in (".", "-", "_", "@"))
    safe = safe.strip(". ")
    return safe or "unknown"


async def _put_object_once(key: str, blob: bytes, mime: str) -> bool:
    if oss.object_exists(key):
        return False
    await asyncio.to_thread(oss.put_object, key, blob, mime)
    return True


async def _count_storage_path_refs(db: AsyncSession, storage_path: str) -> int:
    return int(
        (
            await db.execute(
                select(func.count(MediaAsset.id)).where(MediaAsset.storage_path == storage_path)
            )
        ).scalar()
        or 0
    )


async def unlink_storage_if_unreferenced(db: AsyncSession, storage_path: str) -> None:
    if await _count_storage_path_refs(db, storage_path) > 0:
        return
    if oss.is_cdn_object_key(storage_path):
        await asyncio.to_thread(oss.delete_object, storage_path)


async def _find_user_asset_by_hash(
    db: AsyncSession, user_id: int, content_hash: str
) -> MediaAsset | None:
    return (
        await db.execute(
            select(MediaAsset)
            .where(MediaAsset.user_id == user_id, MediaAsset.content_hash == content_hash)
            .order_by(MediaAsset.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def _resolve_username_raw(
    db: AsyncSession, user_id: int, username: str | None
) -> str:
    if username and username.strip():
        return username.strip()
    row = await db.get(User, user_id)
    return (row.username if row else None) or "unknown"


async def store_media_from_blob(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    blob: bytes,
    mime: str,
    content_hash: str,
    source_model: str | None = None,
    source_prompt: str | None = None,
    chat_session_id: str | None = None,
    file_name_hint: str | None = None,
    metadata: dict[str, Any] | None = None,
    username: str | None = None,
) -> MediaAsset:
    from app.services.user_media_service import MediaQuotaExceededError, ensure_user_media_quota

    digest = (content_hash or "").strip().lower()
    if not digest:
        raise ValueError("content_hash is required")

    owner_username = await _resolve_username_raw(db, user_id, username)
    ext = _ext_from_mime(mime)
    object_key = object_key_for_user_media(owner_username, digest, ext)

    existing = await _find_user_asset_by_hash(db, user_id, digest)
    if existing:
        now = dt.datetime.utcnow()
        retention_days = await get_retention_days_cached(db)
        expires_at = now + dt.timedelta(days=retention_days)
        await _put_object_once(object_key, blob, mime)
        existing.created_at = now
        existing.expires_at = expires_at
        existing.mime_type = mime
        existing.size_bytes = len(blob)
        existing.storage_path = object_key
        existing.file_name = _sanitize_name(
            file_name_hint, existing.file_name or f"{kind}-{now.strftime('%Y%m%d-%H%M%S')}{ext}"
        )
        if chat_session_id is not None:
            existing.chat_session_id = chat_session_id
        if source_model is not None:
            existing.source_model = source_model
        if source_prompt is not None:
            existing.source_prompt = source_prompt
        if metadata:
            existing.metadata_json = json.dumps(metadata)
        await db.flush()
        return existing

    try:
        await ensure_user_media_quota(db, user_id, len(blob))
    except MediaQuotaExceededError as exc:
        raise ValueError(str(exc)) from exc

    retention_days = await get_retention_days_cached(db)
    now = dt.datetime.utcnow()
    expires_at = now + dt.timedelta(days=retention_days)
    fallback_name = f"{kind}-{now.strftime('%Y%m%d-%H%M%S')}{ext}"
    file_name = _sanitize_name(file_name_hint, fallback_name)
    object_created = False
    try:
        object_created = await _put_object_once(object_key, blob, mime)
        row = MediaAsset(
            user_id=user_id,
            kind=kind,
            mime_type=mime,
            file_name=file_name,
            storage_path=object_key,
            content_hash=digest,
            size_bytes=len(blob),
            source_model=source_model,
            source_prompt=source_prompt,
            chat_session_id=chat_session_id,
            metadata_json=json.dumps(metadata or {}),
            created_at=now,
            expires_at=expires_at,
        )
        db.add(row)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            await db.expunge(row)
            raced = await _find_user_asset_by_hash(db, user_id, digest)
            if not raced:
                raise
            raced.created_at = now
            raced.expires_at = expires_at
            raced.mime_type = mime
            raced.file_name = file_name
            raced.storage_path = object_key
            raced.size_bytes = len(blob)
            if chat_session_id is not None:
                raced.chat_session_id = chat_session_id
            if source_model is not None:
                raced.source_model = source_model
            if source_prompt is not None:
                raced.source_prompt = source_prompt
            if metadata:
                raced.metadata_json = json.dumps(metadata)
            await db.flush()
            return raced
        return row
    except BaseException:
        if object_created:
            with contextlib.suppress(Exception):
                if await _count_storage_path_refs(db, object_key) == 0:
                    await asyncio.to_thread(oss.delete_object, object_key)
        raise


async def store_generated_media(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    source_model: str | None,
    source_prompt: str | None,
    chat_session_id: str | None,
    data_url: str | None = None,
    source_url: str | None = None,
    file_name_hint: str | None = None,
    metadata: dict[str, Any] | None = None,
    username: str | None = None,
) -> MediaAsset:
    if not data_url and not source_url:
        raise ValueError("Either data_url or source_url is required")
    blob, mime = await resolve_media_blob(data_url=data_url, source_url=source_url)
    return await store_generated_blob(
        db,
        user_id=user_id,
        kind=kind,
        blob=blob,
        mime=mime,
        source_model=source_model,
        source_prompt=source_prompt,
        chat_session_id=chat_session_id,
        file_name_hint=file_name_hint,
        metadata=metadata,
        username=username,
    )


async def store_generated_blob(
    db: AsyncSession,
    *,
    user_id: int,
    kind: str,
    blob: bytes,
    mime: str,
    source_model: str | None,
    source_prompt: str | None,
    chat_session_id: str | None,
    file_name_hint: str | None = None,
    metadata: dict[str, Any] | None = None,
    username: str | None = None,
) -> MediaAsset:
    if len(blob) > media_input_limit():
        raise ValueError("Media exceeds the allowed input limit")
    blob, mime, content_hash = await asyncio.to_thread(media_content_hash, blob, mime, kind)
    return await store_media_from_blob(
        db,
        user_id=user_id,
        kind=kind,
        blob=blob,
        mime=mime,
        content_hash=content_hash,
        source_model=source_model,
        source_prompt=source_prompt,
        chat_session_id=chat_session_id,
        file_name_hint=file_name_hint,
        metadata=metadata,
        username=username,
    )


def read_media_bytes_sync(asset: MediaAsset) -> bytes:
    path = (asset.storage_path or "").replace("\\", "/")
    if not oss.is_cdn_object_key(path):
        raise FileNotFoundError(path)
    try:
        return oss.get_object_bytes(path)
    except oss.ObjectNotFoundError:
        raise FileNotFoundError(path) from None


async def read_media_bytes(asset: MediaAsset) -> bytes:
    return await asyncio.to_thread(read_media_bytes_sync, asset)


async def list_user_media(db: AsyncSession, user_id: int, limit: int = 200) -> list[MediaAsset]:
    return (
        await db.execute(
            select(MediaAsset).where(MediaAsset.user_id == user_id).order_by(MediaAsset.created_at.desc()).limit(limit)
        )
    ).scalars().all()


async def storage_stats(db: AsyncSession) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(
                func.count(MediaAsset.id),
                func.min(MediaAsset.created_at),
                func.max(MediaAsset.created_at),
            )
        )
    ).one()
    total_logical_bytes = (
        await db.execute(select(func.coalesce(func.sum(MediaAsset.size_bytes), 0)))
    ).scalar() or 0
    settings = await get_storage_settings(db)
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=int(settings["retention_days"]))
    expired_count = (
        await db.execute(select(func.count(MediaAsset.id)).where(MediaAsset.created_at < cutoff))
    ).scalar() or 0
    return {
        "total_files": int(rows[0] or 0),
        "total_size_bytes": int(total_logical_bytes),
        "oldest_created_at": rows[1].isoformat() if rows[1] else None,
        "latest_created_at": rows[2].isoformat() if rows[2] else None,
        "expired_files": int(expired_count),
        "settings": settings,
    }


async def clear_all_media(db: AsyncSession) -> dict[str, int]:
    rows = (await db.execute(select(MediaAsset))).scalars().all()
    removed = len(rows)
    paths = {row.storage_path for row in rows}
    await db.execute(delete(MediaAsset))
    await db.flush()
    for path in paths:
        if oss.is_cdn_object_key(path):
            await asyncio.to_thread(oss.delete_object, path)
    return {"removed_files": removed}


async def purge_expired_media(db: AsyncSession, retention_days: int | None = None) -> dict[str, int]:
    settings = await get_storage_settings(db)
    days = retention_days if retention_days is not None else int(settings["retention_days"])
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=max(1, days))
    rows = (await db.execute(select(MediaAsset).where(MediaAsset.created_at < cutoff))).scalars().all()
    removed = 0
    paths: list[str] = []
    for row in rows:
        paths.append(row.storage_path)
        await db.delete(row)
        removed += 1
    await db.flush()
    for storage_path in paths:
        await unlink_storage_if_unreferenced(db, storage_path)
    return {"removed_files": removed}


def media_public_url(asset_id: int) -> str:
    return f"/api/chat/media/{asset_id}/file"


def format_size(size_bytes: int) -> str:
    size = float(size_bytes or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size_bytes} B"
