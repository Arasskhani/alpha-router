"""Project-owned media library: upload, list, download, delete.

Ownership is project-scoped, not user-scoped.  When a member leaves or
their account is deleted, files remain (``uploaded_by_user_id`` → NULL).
When the project is hard-deleted, rows cascade and object storage is
cleaned up by the service layer.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import time
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text_safety import strip_nul
from app.models.media import MediaAsset
from app.models.system import SystemSetting
from app.models.project import (
    PROJECT_MEDIA_KIND_DOCUMENT,
    PROJECT_MEDIA_KIND_IMAGE,
    PROJECT_MEDIA_KIND_OTHER,
    PROJECT_MEDIA_KIND_VIDEO,
    PROJECT_MEDIA_KINDS,
    ProjectMediaAsset,
)
from app.services.project_access_service import (
    append_project_audit,
    is_project_owner_role,
    require_capability,
)
from app.services.storage_service import _ext_from_mime, _sanitize_name, media_input_limit

_MAX_LIST_LIMIT = 200
DEFAULT_PROJECT_MEDIA_QUOTA_BYTES = 1024 * 1024 * 1024  # 1 GiB per project
_KEY_PROJECT_MEDIA_QUOTA_GB = "project_media_quota_gb"
DEFAULT_PROJECT_MEDIA_QUOTA_GB = 1
MIN_PROJECT_MEDIA_QUOTA_GB = 1
MAX_PROJECT_MEDIA_QUOTA_GB = 100
_PROJECT_QUOTA_BYTES_CACHE: tuple[float, int] | None = None
_PERSONAL_MEDIA_URL_RE = re.compile(r"/api/chat/media/(\d+)/file")
logger = logging.getLogger("app.services.project_media_service")


class ProjectMediaObjectStore(Protocol):
    async def put(self, key: str, body: bytes, mime: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


class S3ProjectMediaObjectStore:
    """Default adapter over SeaweedFS / S3."""

    async def put(self, key: str, body: bytes, mime: str) -> None:
        import asyncio

        from app.services import object_storage_service as oss

        if oss.object_exists(key):
            return
        await asyncio.to_thread(oss.put_object, key, body, mime)

    async def get(self, key: str) -> bytes:
        import asyncio

        from app.services import object_storage_service as oss

        return await asyncio.to_thread(oss.get_object_bytes, key)

    async def delete(self, key: str) -> None:
        import asyncio

        from app.services import object_storage_service as oss

        await asyncio.to_thread(oss.delete_object, key)

    async def exists(self, key: str) -> bool:
        import asyncio

        from app.services import object_storage_service as oss

        return await asyncio.to_thread(oss.object_exists, key)


def default_project_media_store() -> ProjectMediaObjectStore:
    return S3ProjectMediaObjectStore()


class ProjectMediaQuotaError(Exception):
    def __init__(self, used_bytes: int, incoming_bytes: int, quota_bytes: int):
        self.used_bytes = used_bytes
        self.incoming_bytes = incoming_bytes
        self.quota_bytes = quota_bytes
        super().__init__(
            f"Project media quota exceeded. Used {used_bytes} bytes, need {incoming_bytes} more "
            f"(limit {quota_bytes} bytes)."
        )


class ProjectMediaValidationError(Exception):
    """Raised for empty/oversized/invalid uploads."""


def _sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _infer_kind(mime: str, kind: str | None) -> str:
    if kind:
        normalized = kind.strip().lower()
        if normalized not in PROJECT_MEDIA_KINDS:
            raise ProjectMediaValidationError(f"Invalid media kind: {kind!r}")
        return normalized
    m = (mime or "").lower()
    if m.startswith("image/"):
        return PROJECT_MEDIA_KIND_IMAGE
    if m.startswith("video/"):
        return PROJECT_MEDIA_KIND_VIDEO
    if m.startswith("audio/"):
        return PROJECT_MEDIA_KIND_OTHER
    if m.startswith("text/") or m in (
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        return PROJECT_MEDIA_KIND_DOCUMENT
    return PROJECT_MEDIA_KIND_OTHER


def project_media_public_url(project_id: str, media_id: int) -> str:
    return f"/api/projects/{project_id}/media/{media_id}/download"


def invalidate_project_media_quota_cache() -> None:
    global _PROJECT_QUOTA_BYTES_CACHE
    _PROJECT_QUOTA_BYTES_CACHE = None


def _gb_to_bytes(gb: int) -> int:
    return gb * 1024 * 1024 * 1024


async def get_project_media_quota_gb(db: AsyncSession) -> int:
    row = await db.get(SystemSetting, _KEY_PROJECT_MEDIA_QUOTA_GB)
    if not row or not (row.value or "").strip():
        return DEFAULT_PROJECT_MEDIA_QUOTA_GB
    try:
        gb = int(row.value)
    except (TypeError, ValueError):
        return DEFAULT_PROJECT_MEDIA_QUOTA_GB
    return max(MIN_PROJECT_MEDIA_QUOTA_GB, min(MAX_PROJECT_MEDIA_QUOTA_GB, gb))


async def get_project_media_quota_bytes(db: AsyncSession) -> int:
    global _PROJECT_QUOTA_BYTES_CACHE
    now = time.monotonic()
    if _PROJECT_QUOTA_BYTES_CACHE and now - _PROJECT_QUOTA_BYTES_CACHE[0] < 300.0:
        return _PROJECT_QUOTA_BYTES_CACHE[1]
    gb = await get_project_media_quota_gb(db)
    bytes_val = _gb_to_bytes(gb)
    _PROJECT_QUOTA_BYTES_CACHE = (now, bytes_val)
    return bytes_val


async def set_project_media_quota_gb(db: AsyncSession, gb: int) -> int:
    clamped = max(MIN_PROJECT_MEDIA_QUOTA_GB, min(MAX_PROJECT_MEDIA_QUOTA_GB, int(gb)))
    invalidate_project_media_quota_cache()
    val = str(clamped)
    row = await db.get(SystemSetting, _KEY_PROJECT_MEDIA_QUOTA_GB)
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key=_KEY_PROJECT_MEDIA_QUOTA_GB, value=val))
    await db.flush()
    return clamped


async def count_projects_over_media_quota(db: AsyncSession) -> int:
    quota = await get_project_media_quota_bytes(db)
    rows = (
        await db.execute(
            select(
                ProjectMediaAsset.project_id,
                func.coalesce(func.sum(ProjectMediaAsset.size_bytes), 0),
            ).group_by(ProjectMediaAsset.project_id)
        )
    ).all()
    return sum(1 for _pid, used in rows if int(used or 0) > quota)


async def _resolved_project_quota_bytes(db: AsyncSession, quota_bytes: int | None) -> int:
    if quota_bytes is not None:
        return int(quota_bytes)
    return await get_project_media_quota_bytes(db)


def _to_client(row: ProjectMediaAsset) -> dict:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "uploadedByUserId": row.uploaded_by_user_id,
        "kind": row.kind,
        "mimeType": row.mime_type,
        "fileName": row.file_name,
        "sizeBytes": row.size_bytes,
        "sourceModel": row.source_model,
        "sourcePrompt": row.source_prompt,
        "chatSessionId": row.chat_session_id,
        "contentHash": row.content_hash,
        "storagePath": row.storage_path,
        "url": project_media_public_url(row.project_id, row.id),
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "expiresAt": row.expires_at.isoformat() if row.expires_at else None,
    }


def _object_key(project_id: str, content_hash: str, mime: str) -> str:
    from app.services.object_storage_service import project_media_object_key

    return project_media_object_key(project_id, content_hash, _ext_from_mime(mime))


async def _find_by_hash(db: AsyncSession, project_id: str, content_hash: str) -> ProjectMediaAsset | None:
    return (
        await db.execute(
            select(ProjectMediaAsset).where(
                ProjectMediaAsset.project_id == project_id,
                ProjectMediaAsset.content_hash == content_hash,
            )
        )
    ).scalar_one_or_none()


async def get_project_media_used_bytes(db: AsyncSession, project_id: str) -> int:
    return int(
        (
            await db.execute(
                select(func.coalesce(func.sum(ProjectMediaAsset.size_bytes), 0)).where(
                    ProjectMediaAsset.project_id == project_id
                )
            )
        ).scalar()
        or 0
    )


async def ensure_project_media_quota(
    db: AsyncSession,
    project_id: str,
    incoming_bytes: int,
    *,
    quota_bytes: int | None = None,
) -> None:
    resolved = await _resolved_project_quota_bytes(db, quota_bytes)
    used = await get_project_media_used_bytes(db, project_id)
    if used + max(0, incoming_bytes) > resolved:
        raise ProjectMediaQuotaError(used, incoming_bytes, resolved)


async def list_project_media(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    kind: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List project media. Requires ``media.read`` (members only)."""
    await require_capability(db, project_id=project_id, user=user, capability="media.read")

    limit = min(max(1, limit), _MAX_LIST_LIMIT)
    offset = max(0, offset)

    filters = [ProjectMediaAsset.project_id == project_id]
    if kind:
        normalized = kind.strip().lower()
        if normalized in PROJECT_MEDIA_KINDS:
            filters.append(ProjectMediaAsset.kind == normalized)
    if q and q.strip():
        term = f"%{q.strip()}%"
        filters.append(
            or_(
                ProjectMediaAsset.file_name.ilike(term),
                ProjectMediaAsset.source_prompt.ilike(term),
            )
        )

    total = int((await db.execute(select(func.count()).select_from(ProjectMediaAsset).where(*filters))).scalar() or 0)
    rows = (
        (
            await db.execute(
                select(ProjectMediaAsset)
                .where(*filters)
                .order_by(ProjectMediaAsset.created_at.desc(), ProjectMediaAsset.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [_to_client(row) for row in rows], total


async def get_project_media(
    db: AsyncSession,
    *,
    project_id: str,
    media_id: int,
    user: object,
) -> dict | None:
    """Return one media item, or None if it does not belong to this project."""
    await require_capability(db, project_id=project_id, user=user, capability="media.read")
    row = await db.get(ProjectMediaAsset, media_id)
    if row is None or row.project_id != project_id:
        return None
    return _to_client(row)


async def upload_project_media(
    db: AsyncSession,
    *,
    project_id: str,
    user: object,
    file_name: str,
    mime_type: str,
    content_bytes: bytes,
    kind: str | None = None,
    source_model: str | None = None,
    source_prompt: str | None = None,
    chat_session_id: str | None = None,
    object_store: ProjectMediaObjectStore | None = None,
    quota_bytes: int | None = None,
    content_hash: str | None = None,
) -> dict:
    """Upload a binary file as project-owned media.

    Requires ``media.upload``.  Duplicate content (same SHA-256 within the
    project) returns the existing asset without consuming extra quota.
    """
    access = await require_capability(db, project_id=project_id, user=user, capability="media.upload")

    blob = content_bytes or b""
    if not blob:
        raise ProjectMediaValidationError("Empty file is not allowed")
    max_bytes = media_input_limit()
    if len(blob) > max_bytes:
        raise ProjectMediaValidationError(f"File exceeds the {max_bytes} byte upload limit")

    mime = (mime_type or "application/octet-stream").strip()[:128] or "application/octet-stream"
    resolved_kind = _infer_kind(mime, kind)
    digest = (content_hash or "").strip().lower() or _sha256_hex(blob)
    if len(digest) != 64:
        digest = _sha256_hex(blob)
    existing = await _find_by_hash(db, project_id, digest)
    if existing is not None:
        return _to_client(existing)

    await ensure_project_media_quota(db, project_id, len(blob), quota_bytes=quota_bytes)

    store = object_store or default_project_media_store()
    now = dt.datetime.utcnow()
    ext = _ext_from_mime(mime)
    fallback = f"{resolved_kind}-{now.strftime('%Y%m%d-%H%M%S')}{ext}"
    safe_name = _sanitize_name(file_name, fallback)[:255]
    storage_path = _object_key(project_id, digest, mime)

    if not await store.exists(storage_path):
        await store.put(storage_path, blob, mime)

    row = ProjectMediaAsset(
        project_id=project_id,
        uploaded_by_user_id=access.user_id,
        kind=resolved_kind,
        mime_type=mime,
        file_name=safe_name,
        storage_path=storage_path,
        content_hash=digest,
        size_bytes=len(blob),
        source_model=strip_nul(source_model),
        source_prompt=strip_nul(source_prompt),
        chat_session_id=(chat_session_id or None),
        created_at=now,
    )
    db.add(row)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raced = await _find_by_hash(db, project_id, digest)
        if raced is None:
            raise
        return _to_client(raced)

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="media.upload",
        actor_user_id=access.user_id,
        payload={"media_id": row.id, "file_name": safe_name, "kind": resolved_kind},
    )
    return _to_client(row)


async def delete_project_media(
    db: AsyncSession,
    *,
    project_id: str,
    media_id: int,
    user: object,
    object_store: ProjectMediaObjectStore | None = None,
) -> bool | None:
    """Delete a project media asset.

    Owner can delete any file. Contributor can delete only their own.
    Returns None if the asset is hidden / not in this project.
    """
    access = await require_capability(db, project_id=project_id, user=user, capability="media.delete")
    row = await db.get(ProjectMediaAsset, media_id)
    if row is None or row.project_id != project_id:
        return None

    is_owner = is_project_owner_role(access.role)
    is_uploader = row.uploaded_by_user_id == access.user_id
    if not is_owner and not is_uploader:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete media you uploaded",
        )

    storage_path = row.storage_path
    await db.delete(row)
    await db.flush()

    remaining = int(
        (
            await db.execute(
                select(func.count(ProjectMediaAsset.id)).where(ProjectMediaAsset.storage_path == storage_path)
            )
        ).scalar()
        or 0
    )
    if remaining == 0:
        store = object_store or default_project_media_store()
        await store.delete(storage_path)

    await append_project_audit(
        db,
        project_id=project_id,
        event_type="media.delete",
        actor_user_id=access.user_id,
        payload={"media_id": media_id},
    )
    return True


async def read_project_media_bytes(
    db: AsyncSession,
    *,
    project_id: str,
    media_id: int,
    user: object,
    object_store: ProjectMediaObjectStore | None = None,
) -> tuple[ProjectMediaAsset, bytes] | None:
    """Read binary content for download. Requires ``media.read`` (members only)."""
    await require_capability(db, project_id=project_id, user=user, capability="media.read")
    row = await db.get(ProjectMediaAsset, media_id)
    if row is None or row.project_id != project_id:
        return None
    store = object_store or default_project_media_store()
    blob = await store.get(row.storage_path)
    return row, blob


async def cleanup_project_media_storage(
    db: AsyncSession,
    project_id: str,
    *,
    object_store: ProjectMediaObjectStore | None = None,
) -> int:
    """Delete object-store blobs for every media asset in a project.

    Intended for hard-delete of a project.  Rows themselves are expected
    to cascade via the ``project_id`` FK.
    """
    rows = (
        (await db.execute(select(ProjectMediaAsset).where(ProjectMediaAsset.project_id == project_id))).scalars().all()
    )
    store = object_store or default_project_media_store()
    paths = {row.storage_path for row in rows if row.storage_path}
    for path in paths:
        await store.delete(path)
    return len(paths)


async def maybe_save_generated_media_to_project(
    db: AsyncSession,
    *,
    project_id: str | None,
    user: object | None,
    content_bytes: bytes,
    mime_type: str,
    file_name: str,
    kind: str | None = None,
    source_model: str | None = None,
    source_prompt: str | None = None,
    chat_session_id: str | None = None,
    object_store: ProjectMediaObjectStore | None = None,
    quota_bytes: int | None = None,
) -> dict | None:
    """Best-effort copy of generated media into the project library.

    Never raises: missing project, no ``media.upload`` capability, quota,
    validation, or storage failures are logged and skipped so generation
    itself still succeeds. Personal generation (no ``project_id``) is a no-op.
    """
    pid = (project_id or "").strip()
    if not pid or user is None or not content_bytes:
        return None
    try:
        return await upload_project_media(
            db,
            project_id=pid,
            user=user,
            file_name=file_name,
            mime_type=mime_type,
            content_bytes=content_bytes,
            kind=kind,
            source_model=source_model,
            source_prompt=source_prompt,
            chat_session_id=chat_session_id,
            object_store=object_store,
            quota_bytes=quota_bytes,
        )
    except ProjectMediaQuotaError:
        logger.info(
            "Skipping project media save; quota exceeded project=%s bytes=%s",
            pid,
            len(content_bytes),
        )
        return None
    except ProjectMediaValidationError as exc:
        logger.info(
            "Skipping project media save; invalid generated blob project=%s: %s",
            pid,
            exc,
        )
        return None
    except Exception as exc:
        from fastapi import HTTPException

        if isinstance(exc, HTTPException):
            logger.info(
                "Skipping project media save; no upload access project=%s status=%s",
                pid,
                exc.status_code,
            )
            return None
        logger.exception(
            "Skipping project media save after generation project=%s",
            pid,
        )
        return None


async def persist_scoped_chat_media(
    db: AsyncSession,
    *,
    user: object,
    project_id: str | None,
    kind: str,
    blob: bytes,
    mime: str,
    file_name: str,
    source_model: str | None = None,
    source_prompt: str | None = None,
    chat_session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    object_store: ProjectMediaObjectStore | None = None,
    quota_bytes: int | None = None,
) -> str:
    """Store chat media in the project library when scoped, else the user library.

    Project quota / missing upload access falls back to the caller's personal
    media so the author still sees the file. Other members cannot read that
    fallback URL.
    """
    import asyncio

    from app.services.storage_service import (
        media_content_hash,
        media_public_url,
        store_media_from_blob,
    )

    hashed_blob, hashed_mime, digest = await asyncio.to_thread(media_content_hash, blob, mime, kind)
    pid = (project_id or "").strip()
    if pid:
        try:
            saved = await upload_project_media(
                db,
                project_id=pid,
                user=user,
                file_name=file_name,
                mime_type=hashed_mime,
                content_bytes=hashed_blob,
                kind=kind,
                source_model=source_model,
                source_prompt=source_prompt,
                chat_session_id=chat_session_id,
                object_store=object_store,
                quota_bytes=quota_bytes,
                content_hash=digest,
            )
            return project_media_public_url(pid, int(saved["id"]))
        except ProjectMediaQuotaError:
            logger.info(
                "Project media quota exceeded; falling back to user media project=%s",
                pid,
            )
        except ProjectMediaValidationError:
            raise
        except Exception as exc:
            from fastapi import HTTPException

            if isinstance(exc, HTTPException) and exc.status_code in (403, 404):
                logger.info(
                    "No project media upload access; falling back to user media project=%s",
                    pid,
                )
            else:
                raise

    user_id = getattr(user, "id", None)
    if user_id is None:
        raise ValueError("User is required to store media")
    asset = await store_media_from_blob(
        db,
        user_id=int(user_id),
        username=getattr(user, "username", None),
        kind=kind,
        blob=hashed_blob,
        mime=hashed_mime,
        content_hash=digest,
        source_model=source_model,
        source_prompt=source_prompt,
        chat_session_id=chat_session_id,
        file_name_hint=file_name,
        metadata=metadata,
    )
    return media_public_url(asset.id)


def collect_personal_media_ids(content: str) -> set[int]:
    if not content or "/api/chat/media/" not in content:
        return set()
    out: set[int] = set()
    for match in _PERSONAL_MEDIA_URL_RE.finditer(content):
        try:
            out.add(int(match.group(1)))
        except ValueError:
            continue
    return out


def apply_personal_media_url_map(content: str, mapping: dict[int, str]) -> str:
    if not mapping or "/api/chat/media/" not in content:
        return content

    def _replace(match: re.Match[str]) -> str:
        try:
            asset_id = int(match.group(1))
        except ValueError:
            return match.group(0)
        return mapping.get(asset_id, match.group(0))

    return _PERSONAL_MEDIA_URL_RE.sub(_replace, content)


async def rewrite_personal_media_urls_in_messages(
    db: AsyncSession,
    *,
    project_id: str | None,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rewrite personal /api/chat/media URLs to project download URLs when a copy exists."""
    pid = (project_id or "").strip()
    if not pid or not messages:
        return messages
    ids: set[int] = set()
    for payload in messages:
        content = payload.get("content")
        if isinstance(content, str):
            ids.update(collect_personal_media_ids(content))
    if not ids:
        return messages
    assets = (await db.execute(select(MediaAsset).where(MediaAsset.id.in_(list(ids))))).scalars().all()
    hash_by_id = {int(row.id): (row.content_hash or "").strip().lower() for row in assets if row.content_hash}
    hashes = {digest for digest in hash_by_id.values() if digest}
    if not hashes:
        return messages
    project_rows = (
        (
            await db.execute(
                select(ProjectMediaAsset).where(
                    ProjectMediaAsset.project_id == pid,
                    ProjectMediaAsset.content_hash.in_(list(hashes)),
                )
            )
        )
        .scalars()
        .all()
    )
    url_by_hash = {
        (row.content_hash or "").strip().lower(): project_media_public_url(pid, int(row.id))
        for row in project_rows
        if row.content_hash
    }
    mapping = {asset_id: url_by_hash[digest] for asset_id, digest in hash_by_id.items() if digest in url_by_hash}
    if not mapping:
        return messages
    for payload in messages:
        content = payload.get("content")
        if isinstance(content, str):
            payload["content"] = apply_personal_media_url_map(content, mapping)
    return messages
