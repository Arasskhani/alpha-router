"""One-time migration from filesystem chat/media layout to DB JSON + object storage."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import MediaAsset
from app.models.system import SystemSetting
from app.models.user import User
from app.models.chat import UserChatPrefs
from app.services import object_storage_service as oss
from app.services.storage_service import (
    _LEGACY_MEDIA_ROOT,
    _ext_from_mime,
    _sanitize_username_dir,
    read_media_bytes_sync,
)
from app.services.user_chat_storage_service import _default_prefs, _normalize_prefs

logger = logging.getLogger(__name__)

_LEGACY_CHATS_ROOT = Path(__file__).resolve().parents[2] / "storage" / "chats"
_MIGRATION_KEY = "storage_layout_v2_completed"
_SESSIONS_FILE = "sessions.json"
_FOLDERS_FILE = "folders.json"
_PREFS_FILE = "prefs.json"


def _legacy_chats_users_root() -> Path:
    return _LEGACY_CHATS_ROOT / "users"


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        logger.warning("Failed to read legacy chat file %s", path, exc_info=True)
        return []


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("Failed to read legacy prefs file %s", path, exc_info=True)
        return {}


async def _migration_completed(db: AsyncSession) -> bool:
    row = await db.get(SystemSetting, _MIGRATION_KEY)
    return bool(row and (row.value or "").lower() in ("1", "true", "yes", "done"))


async def _mark_migration_completed(db: AsyncSession) -> None:
    row = await db.get(SystemSetting, _MIGRATION_KEY)
    if row:
        row.value = "true"
    else:
        db.add(SystemSetting(key=_MIGRATION_KEY, value="true"))
    await db.flush()


async def migrate_legacy_storage_layout(db: AsyncSession) -> dict[str, Any]:
    """Move chats → JSONB table, media → object storage/S3, then remove legacy directories."""
    if await _migration_completed(db):
        return {"skipped": True}

    oss.ensure_bucket()
    chat_stats = await _migrate_chats_from_files(db)
    media_stats = await _migrate_media_to_object_storage(db)
    cleanup_stats = _cleanup_legacy_directories()

    await _mark_migration_completed(db)
    await db.commit()

    summary = {
        "skipped": False,
        "chats": chat_stats,
        "media": media_stats,
        "cleanup": cleanup_stats,
    }
    logger.info("Storage layout migration completed: %s", summary)
    return summary


async def _migrate_chats_from_files(db: AsyncSession) -> dict[str, int]:
    users_root = _legacy_chats_users_root()
    if not users_root.is_dir():
        return {"users": 0, "imported": 0, "skipped": 0}

    users_by_name = {u.username: u for u in (await db.execute(select(User))).scalars().all()}
    imported = 0
    skipped = 0
    touched_users = 0

    for user_dir in sorted(users_root.iterdir()):
        if not user_dir.is_dir():
            continue
        username = user_dir.name
        user = users_by_name.get(username)
        if not user:
            for candidate, row in users_by_name.items():
                if _sanitize_username_dir(candidate) == username:
                    user = row
                    break
        if not user:
            logger.warning("Skipping legacy chat dir %s — user not found in DB", user_dir)
            skipped += 1
            continue

        prefs = _normalize_prefs(_read_json_object(user_dir / _PREFS_FILE))
        if prefs == _default_prefs():
            skipped += 1
            continue

        row = await db.get(UserChatPrefs, user.id)
        if row is None:
            row = UserChatPrefs(user_id=user.id, prefs=prefs)
            db.add(row)
            imported += 1
        elif not row.prefs:
            row.prefs = prefs
            imported += 1
        else:
            skipped += 1
        touched_users += 1

    await db.flush()
    return {"users": touched_users, "imported": imported, "skipped": skipped}


async def _migrate_media_to_object_storage(db: AsyncSession) -> dict[str, int]:
    rows = (await db.execute(select(MediaAsset))).scalars().all()
    uploaded = 0
    skipped = 0
    missing = 0

    for row in rows:
        storage_path = (row.storage_path or "").replace("\\", "/")
        username = (
            await db.execute(select(User.username).where(User.id == row.user_id))
        ).scalar_one_or_none() or "unknown"

        try:
            blob = read_media_bytes_sync(row)
        except FileNotFoundError:
            logger.warning("Missing legacy media blob for asset %s at %s", row.id, storage_path)
            missing += 1
            continue

        if row.kind == "image" or (row.mime_type or "").startswith("image/"):
            from app.services.storage_service import media_content_hash

            blob, mime, content_hash = media_content_hash(blob, row.mime_type, row.kind)
        else:
            from app.services.storage_service import sha256_hex

            mime = row.mime_type
            content_hash = (row.content_hash or "").strip() or sha256_hex(blob)

        target_key = oss.media_object_key(
            _sanitize_username_dir(username),
            content_hash,
            _ext_from_mime(mime),
        )

        if storage_path == target_key and oss.object_exists(target_key):
            if row.content_hash != content_hash:
                row.content_hash = content_hash
                row.mime_type = mime
                row.size_bytes = len(blob)
                uploaded += 1
            else:
                skipped += 1
            continue

        if not oss.object_exists(target_key):
            oss.put_object(target_key, blob, mime)

        row.storage_path = target_key
        row.content_hash = content_hash
        row.mime_type = mime
        row.size_bytes = len(blob)
        uploaded += 1

    await db.flush()
    return {"uploaded": uploaded, "skipped": skipped, "missing": missing, "total": len(rows)}


def _cleanup_legacy_directories() -> dict[str, Any]:
    removed_chat_users = 0
    removed_media_files = 0

    users_root = _legacy_chats_users_root()
    if users_root.is_dir():
        for user_dir in list(users_root.iterdir()):
            if user_dir.is_dir():
                shutil.rmtree(user_dir, ignore_errors=True)
                removed_chat_users += 1
        shutil.rmtree(users_root, ignore_errors=True)

    if _LEGACY_CHATS_ROOT.is_dir():
        try:
            _LEGACY_CHATS_ROOT.rmdir()
        except OSError:
            pass

    if _LEGACY_MEDIA_ROOT.is_dir():
        for path in _LEGACY_MEDIA_ROOT.rglob("*"):
            if path.is_file():
                try:
                    path.unlink()
                    removed_media_files += 1
                except OSError:
                    pass
        shutil.rmtree(_LEGACY_MEDIA_ROOT, ignore_errors=True)

    return {
        "removed_chat_user_dirs": removed_chat_users,
        "removed_media_files": removed_media_files,
    }


_MEDIA_STORAGE_V3_KEY = "media_storage_v3_completed"


@dataclass(frozen=True)
class _MediaTargetState:
    digest: str
    new_key: str
    mime: str
    size: int
    blob: bytes
    old_path: str


def _plan_media_reconcile_survivors(
    rows: list[MediaAsset],
    targets: dict[int, _MediaTargetState],
) -> tuple[set[int], set[int]]:
    """When multiple rows share the same normalized content, keep the newest id."""
    from collections import defaultdict

    groups: dict[tuple[int, str], list[int]] = defaultdict(list)
    for row in rows:
        state = targets.get(row.id)
        if not state:
            continue
        groups[(row.user_id, state.digest)].append(row.id)

    keep: set[int] = set()
    delete: set[int] = set()
    for ids in groups.values():
        ids.sort(reverse=True)
        keep.add(ids[0])
        delete.update(ids[1:])
    return keep, delete


async def _storage_v3_completed(db: AsyncSession) -> bool:
    row = await db.get(SystemSetting, _MEDIA_STORAGE_V3_KEY)
    return bool(row and (row.value or "").lower() in ("1", "true", "yes", "done"))


async def _mark_storage_v3_completed(db: AsyncSession) -> None:
    row = await db.get(SystemSetting, _MEDIA_STORAGE_V3_KEY)
    if row:
        row.value = "true"
    else:
        db.add(SystemSetting(key=_MEDIA_STORAGE_V3_KEY, value="true"))
    await db.flush()


async def reconcile_media_storage_v3(db: AsyncSession) -> dict[str, Any]:
    """
    One-time repair: username-based object-storage paths, normalized image hashes, duplicate row cleanup.
    Safe to run after upgrades; idempotent once flagged complete.
    """
    if await _storage_v3_completed(db):
        return {"skipped": True}

    from app.services.storage_service import (
        _ext_from_mime,
        media_content_hash,
        object_key_for_user_media,
        read_media_bytes_sync,
        sha256_hex,
        unlink_storage_if_unreferenced,
    )
    from app.services.user_media_service import cleanup_duplicate_media_assets

    users_by_id = {u.id: u.username for u in (await db.execute(select(User))).scalars().all()}
    rows = (await db.execute(select(MediaAsset).order_by(MediaAsset.id))).scalars().all()
    targets: dict[int, _MediaTargetState] = {}

    for row in rows:
        username = users_by_id.get(row.user_id) or "unknown"
        old_path = (row.storage_path or "").replace("\\", "/")

        try:
            blob = read_media_bytes_sync(row)
        except FileNotFoundError:
            logger.warning("Skipping media asset %s — blob missing at %s", row.id, old_path)
            continue

        if row.kind == "image" or (row.mime_type or "").startswith("image/"):
            blob, mime, digest = media_content_hash(blob, row.mime_type, row.kind)
        else:
            mime = row.mime_type
            digest = sha256_hex(blob)

        new_key = object_key_for_user_media(username, digest, _ext_from_mime(mime))
        targets[row.id] = _MediaTargetState(
            digest=digest,
            new_key=new_key,
            mime=mime,
            size=len(blob),
            blob=blob,
            old_path=old_path,
        )

    keep_ids, delete_ids = _plan_media_reconcile_survivors(rows, targets)
    old_paths: set[str] = set()
    updated = 0
    deleted = 0
    uploaded_keys: set[str] = set()

    for row in rows:
        if row.id in delete_ids:
            if row.storage_path:
                old_paths.add(row.storage_path.replace("\\", "/"))
            await db.delete(row)
            deleted += 1
            continue

        state = targets.get(row.id)
        if not state or row.id not in keep_ids:
            continue

        changed = (
            state.old_path != state.new_key
            or (row.content_hash or "").strip().lower() != state.digest
            or row.size_bytes != state.size
            or row.mime_type != state.mime
        )
        if not changed:
            continue

        if state.old_path and state.old_path != state.new_key:
            old_paths.add(state.old_path)
        if state.new_key not in uploaded_keys and not oss.object_exists(state.new_key):
            oss.put_object(state.new_key, state.blob, state.mime)
            uploaded_keys.add(state.new_key)

        row.content_hash = state.digest
        row.storage_path = state.new_key
        row.mime_type = state.mime
        row.size_bytes = state.size
        updated += 1

    await db.flush()
    removed_dupes = await cleanup_duplicate_media_assets(db)
    for path in old_paths:
        await unlink_storage_if_unreferenced(db, path)

    await _mark_storage_v3_completed(db)
    await db.commit()
    summary = {
        "skipped": False,
        "updated_assets": updated,
        "deleted_duplicates": deleted,
        "removed_duplicates": removed_dupes,
    }
    logger.info("Media storage v3 reconciliation completed: %s", summary)
    return summary
