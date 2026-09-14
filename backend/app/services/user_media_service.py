"""User media library: quota, search, bulk ops, per-user cleanup."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import tempfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import MediaAsset
from app.models.system import SystemSetting
from app.models.user_media_prefs import UserMediaPreferences
from app.services.storage_service import media_public_url, read_media_bytes, unlink_storage_if_unreferenced

USER_MEDIA_QUOTA_BYTES = 1024 * 1024 * 1024  # default 1 GiB per user (when setting unset)
_KEY_USER_MEDIA_QUOTA_GB = "user_media_quota_gb"
DEFAULT_USER_MEDIA_QUOTA_GB = 1
MIN_USER_MEDIA_QUOTA_GB = 1
MAX_USER_MEDIA_QUOTA_GB = 100
_QUOTA_BYTES_CACHE: tuple[float, int] | None = None
MAX_ZIP_ITEMS = 100
MAX_ZIP_SINGLE_FILE_BYTES = 50 * 1024 * 1024
MAX_ZIP_AGGREGATE_BYTES = 256 * 1024 * 1024  # legacy env fallback ceiling
# Absolute ceiling aligned with transfer_limits_service / 10g /tmp headroom.
MAX_ZIP_AGGREGATE_BYTES_HARD = 8192 * 1024 * 1024


class MediaZipLimitError(ValueError):
    pass


def _zip_limits() -> tuple[int, int, int]:
    from app.config import get_settings
    from app.services.bounded_io import clamp_limit
    from app.services.transfer_limits_service import cached_zip_aggregate_limit_bytes

    settings = get_settings()
    items = clamp_limit(settings.max_zip_items, minimum=1, maximum=MAX_ZIP_ITEMS)
    single = clamp_limit(
        settings.max_zip_single_file_bytes,
        minimum=1024 * 1024,
        maximum=MAX_ZIP_SINGLE_FILE_BYTES,
    )
    aggregate = clamp_limit(
        cached_zip_aggregate_limit_bytes(),
        minimum=single,
        maximum=MAX_ZIP_AGGREGATE_BYTES_HARD,
    )
    return items, single, aggregate


def _gb_to_bytes(gb: int) -> int:
    return gb * 1024 * 1024 * 1024


def _format_quota_limit(gb: int) -> str:
    label = f"{gb} GB" if gb != 1 else "1 GB"
    return label


def invalidate_user_media_quota_cache() -> None:
    global _QUOTA_BYTES_CACHE
    _QUOTA_BYTES_CACHE = None


async def get_user_media_quota_gb(db: AsyncSession) -> int:
    row = await db.get(SystemSetting, _KEY_USER_MEDIA_QUOTA_GB)
    if not row or not (row.value or "").strip():
        return DEFAULT_USER_MEDIA_QUOTA_GB
    try:
        gb = int(row.value)
    except (TypeError, ValueError):
        return DEFAULT_USER_MEDIA_QUOTA_GB
    return max(MIN_USER_MEDIA_QUOTA_GB, min(MAX_USER_MEDIA_QUOTA_GB, gb))


async def get_user_media_quota_bytes(db: AsyncSession) -> int:
    global _QUOTA_BYTES_CACHE
    now = time.monotonic()
    if _QUOTA_BYTES_CACHE and now - _QUOTA_BYTES_CACHE[0] < 300.0:
        return _QUOTA_BYTES_CACHE[1]
    gb = await get_user_media_quota_gb(db)
    bytes_val = _gb_to_bytes(gb)
    _QUOTA_BYTES_CACHE = (now, bytes_val)
    return bytes_val


async def set_user_media_quota_gb(db: AsyncSession, gb: int) -> int:
    clamped = max(MIN_USER_MEDIA_QUOTA_GB, min(MAX_USER_MEDIA_QUOTA_GB, int(gb)))
    invalidate_user_media_quota_cache()
    val = str(clamped)
    row = await db.get(SystemSetting, _KEY_USER_MEDIA_QUOTA_GB)
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key=_KEY_USER_MEDIA_QUOTA_GB, value=val))
    await db.flush()
    return clamped


async def count_users_over_media_quota(db: AsyncSession) -> int:
    quota = await get_user_media_quota_bytes(db)
    rows = (await db.execute(select(MediaAsset))).scalars().all()
    by_user: dict[int, list[MediaAsset]] = defaultdict(list)
    for row in rows:
        by_user[row.user_id].append(row)
    over = 0
    for user_rows in by_user.values():
        used = sum(int(r.size_bytes or 0) for r in dedupe_media_rows_by_hash(user_rows))
        if used > quota:
            over += 1
    return over


class MediaQuotaExceededError(Exception):
    def __init__(self, used_bytes: int, incoming_bytes: int, quota_bytes: int):
        self.used_bytes = used_bytes
        self.incoming_bytes = incoming_bytes
        self.quota_bytes = quota_bytes
        gb = max(1, round(quota_bytes / (1024 * 1024 * 1024)))
        limit_label = _format_quota_limit(gb)
        super().__init__(
            f"Media storage quota exceeded ({limit_label} limit). Used {used_bytes} bytes, need {incoming_bytes} more."
        )


async def get_user_media_used_bytes(db: AsyncSession, user_id: int) -> int:
    rows = (await db.execute(select(MediaAsset).where(MediaAsset.user_id == user_id))).scalars().all()
    deduped = dedupe_media_rows_by_hash(rows)
    return sum(int(r.size_bytes or 0) for r in deduped)


async def ensure_user_media_quota(db: AsyncSession, user_id: int, incoming_bytes: int) -> None:
    quota = await get_user_media_quota_bytes(db)
    used = await get_user_media_used_bytes(db, user_id)
    if used + max(0, incoming_bytes) > quota:
        raise MediaQuotaExceededError(used, incoming_bytes, quota)


async def get_or_create_user_media_prefs(db: AsyncSession, user_id: int) -> UserMediaPreferences:
    row = await db.get(UserMediaPreferences, user_id)
    if row:
        return row
    row = UserMediaPreferences(user_id=user_id)
    db.add(row)
    await db.flush()
    return row


def _parse_date(value: str | None, *, end_of_day: bool = False) -> dt.datetime | None:
    if not value or not value.strip():
        return None
    try:
        parsed = dt.datetime.strptime(value.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None
    if end_of_day:
        return parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


def _media_row_dict(row: MediaAsset) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "mime_type": row.mime_type,
        "file_name": row.file_name,
        "size_bytes": row.size_bytes,
        "source_model": row.source_model,
        "source_prompt": row.source_prompt,
        "chat_session_id": row.chat_session_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "url": media_public_url(row.id),
        "content_hash": row.content_hash,
    }


def dedupe_media_rows_by_hash(rows: list[MediaAsset]) -> list[MediaAsset]:
    """Keep one row per (user_id, content_hash); prefer newest id."""
    by_hash: dict[tuple[int, str], MediaAsset] = {}
    without_hash: list[MediaAsset] = []
    for row in rows:
        digest = (row.content_hash or "").strip().lower()
        if not digest:
            without_hash.append(row)
            continue
        key = (row.user_id, digest)
        prev = by_hash.get(key)
        if not prev or row.id > prev.id:
            by_hash[key] = row
    merged = [*by_hash.values(), *without_hash]
    merged.sort(
        key=lambda r: (
            r.created_at or dt.datetime.min,
            r.id,
        ),
        reverse=True,
    )
    return merged


async def cleanup_duplicate_media_assets(db: AsyncSession) -> int:
    """Delete duplicate media_assets rows that share user_id + content_hash."""
    rows = (
        (
            await db.execute(
                select(MediaAsset)
                .where(MediaAsset.content_hash.isnot(None))
                .where(MediaAsset.content_hash != "")
                .order_by(MediaAsset.user_id, MediaAsset.content_hash, MediaAsset.id.desc())
            )
        )
        .scalars()
        .all()
    )
    keep_ids: set[int] = set()
    to_delete: list[MediaAsset] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        key = (row.user_id, (row.content_hash or "").strip().lower())
        if key in seen:
            to_delete.append(row)
        else:
            seen.add(key)
            keep_ids.add(row.id)
    paths: list[str] = []
    for row in to_delete:
        paths.append(row.storage_path)
        await db.delete(row)
    await db.flush()
    for path in paths:
        await unlink_storage_if_unreferenced(db, path)
    return len(to_delete)


async def list_user_media_filtered(
    db: AsyncSession,
    user_id: int,
    *,
    q: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> tuple[list[MediaAsset], int]:
    stmt = select(MediaAsset).where(MediaAsset.user_id == user_id)

    needle = (q or "").strip().lower()
    if needle:
        like = f"%{needle}%"
        filt = or_(
            func.lower(func.coalesce(MediaAsset.source_prompt, "")).like(like),
            func.lower(MediaAsset.file_name).like(like),
            func.lower(func.coalesce(MediaAsset.source_model, "")).like(like),
            func.lower(MediaAsset.kind).like(like),
            func.lower(func.coalesce(MediaAsset.mime_type, "")).like(like),
        )
        stmt = stmt.where(filt)

    start = _parse_date(from_date)
    end = _parse_date(to_date, end_of_day=True)
    if start:
        stmt = stmt.where(MediaAsset.created_at >= start)
    if end:
        stmt = stmt.where(MediaAsset.created_at <= end)

    rows = (await db.execute(stmt.order_by(MediaAsset.created_at.desc()))).scalars().all()
    deduped = dedupe_media_rows_by_hash(rows)
    total = len(deduped)
    page = deduped[max(0, offset) : max(0, offset) + min(1000, max(1, limit))]
    return page, total


async def delete_user_media_ids(db: AsyncSession, user_id: int, ids: list[int]) -> int:
    if not ids:
        return 0
    unique = sorted({int(i) for i in ids if int(i) > 0})
    rows = (
        (await db.execute(select(MediaAsset).where(MediaAsset.user_id == user_id, MediaAsset.id.in_(unique))))
        .scalars()
        .all()
    )
    paths: list[str] = []
    for row in rows:
        paths.append(row.storage_path)
        await db.delete(row)
    await db.flush()
    for path in paths:
        await unlink_storage_if_unreferenced(db, path)
    return len(rows)


async def delete_all_user_media(db: AsyncSession, user_id: int) -> int:
    rows = (await db.execute(select(MediaAsset).where(MediaAsset.user_id == user_id))).scalars().all()
    paths = {row.storage_path for row in rows}
    await db.execute(delete(MediaAsset).where(MediaAsset.user_id == user_id))
    await db.flush()
    for path in paths:
        await unlink_storage_if_unreferenced(db, path)
    return len(rows)


async def purge_user_media_older_than(db: AsyncSession, user_id: int, retention_days: int) -> int:
    days = max(1, int(retention_days))
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    rows = (
        (await db.execute(select(MediaAsset).where(MediaAsset.user_id == user_id, MediaAsset.created_at < cutoff)))
        .scalars()
        .all()
    )
    paths: list[str] = []
    for row in rows:
        paths.append(row.storage_path)
        await db.delete(row)
    await db.flush()
    for path in paths:
        await unlink_storage_if_unreferenced(db, path)
    return len(rows)


async def user_media_quota_summary(db: AsyncSession, user_id: int) -> dict[str, Any]:
    quota = await get_user_media_quota_bytes(db)
    rows = (await db.execute(select(MediaAsset).where(MediaAsset.user_id == user_id))).scalars().all()
    deduped = dedupe_media_rows_by_hash(rows)
    used = sum(int(r.size_bytes or 0) for r in deduped)
    count = len(deduped)
    return {
        "quota_bytes": quota,
        "used_bytes": used,
        "remaining_bytes": max(0, quota - used),
        "file_count": count,
        "used_percent": round((used / quota) * 100, 2) if quota else 0,
    }


def prefs_to_dict(prefs: UserMediaPreferences) -> dict[str, Any]:
    return {
        "cleanup_enabled": bool(prefs.cleanup_enabled),
        "cleanup_retention_days": int(prefs.cleanup_retention_days or 30),
        "cleanup_hour": int(prefs.cleanup_hour or 0),
        "cleanup_minute": int(prefs.cleanup_minute or 0),
        "last_cleanup_at": prefs.last_cleanup_at.isoformat() if prefs.last_cleanup_at else None,
    }


def _zip_arcname(row: MediaAsset, used: set[str]) -> str:
    raw = (row.file_name or f"media-{row.id}").strip() or f"media-{row.id}"
    safe = "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in raw)
    candidate = f"{row.id}-{safe}"
    if candidate not in used:
        used.add(candidate)
        return candidate
    ext = ""
    if "." in safe:
        stem, ext = safe.rsplit(".", 1)
        ext = f".{ext}"
        stem = stem or f"media-{row.id}"
    else:
        stem = safe
    n = 2
    while True:
        alt = f"{row.id}-{stem}-{n}{ext}"
        if alt not in used:
            used.add(alt)
            return alt
        n += 1


async def build_media_zip_file(db: AsyncSession, user_id: int, ids: list[int]) -> tuple[Path, int]:
    from app.services.transfer_limits_service import get_transfer_limits

    await get_transfer_limits(db)
    max_items, max_single, max_aggregate = _zip_limits()
    unique = sorted({int(i) for i in ids if int(i) > 0})
    if not unique:
        raise ValueError("No media ids provided")
    if len(unique) > max_items:
        raise MediaZipLimitError(f"Too many media files (max {max_items})")

    rows = (
        (await db.execute(select(MediaAsset).where(MediaAsset.user_id == user_id, MediaAsset.id.in_(unique))))
        .scalars()
        .all()
    )
    if not rows:
        raise ValueError("No media files found")

    declared_total = 0
    for row in rows:
        size = max(0, int(row.size_bytes or 0))
        if size > max_single:
            raise MediaZipLimitError("A media file exceeds the ZIP single-file limit")
        declared_total += size
        if declared_total > max_aggregate:
            raise MediaZipLimitError(
                f"Selected media exceeds the ZIP download limit "
                f"({max(1, max_aggregate // (1024 * 1024))} MB). "
                "Select fewer files or ask an admin to raise Maximum ZIP download size."
            )

    fd, raw_path = tempfile.mkstemp(prefix="alpha-router-media-", suffix=".zip")
    os.close(fd)
    path = Path(raw_path)
    used_names: set[str] = set()
    packed = 0
    actual_total = 0
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for row in rows:
                try:
                    data = await read_media_bytes(row)
                except FileNotFoundError:
                    continue
                if len(data) > max_single:
                    raise MediaZipLimitError("A media file exceeds the ZIP single-file limit")
                actual_total += len(data)
                if actual_total > max_aggregate:
                    raise MediaZipLimitError(
                        f"Selected media exceeds the ZIP download limit "
                        f"({max(1, max_aggregate // (1024 * 1024))} MB). "
                        "Select fewer files or ask an admin to raise Maximum ZIP download size."
                    )
                arcname = _zip_arcname(row, used_names)
                await asyncio.to_thread(zf.writestr, arcname, data)
                packed += 1
        if packed == 0:
            raise ValueError("No media files available on disk")
        return path, packed
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def stream_media_zip(path: Path) -> AsyncIterator[bytes]:
    try:
        with path.open("rb") as handle:
            while chunk := await asyncio.to_thread(handle.read, 64 * 1024):
                yield chunk
    finally:
        path.unlink(missing_ok=True)


async def build_media_zip_bytes(db: AsyncSession, user_id: int, ids: list[int]) -> tuple[bytes, int]:
    """Compatibility wrapper; API endpoints use the temp-file streaming path."""
    path, packed = await build_media_zip_file(db, user_id, ids)
    try:
        return await asyncio.to_thread(path.read_bytes), packed
    finally:
        path.unlink(missing_ok=True)
