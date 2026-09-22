"""Attach existing personal or project media into chat without re-persisting."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession
from app.models.media import MediaAsset
from app.models.project import ProjectMediaAsset
from app.models.user import User
from app.services.attachment_extract import extract_document_text_bounded
from app.services.attachment_policy import (
    AttachmentPolicyError,
    resolve_attachment_mime,
    validate_attachment_size,
)
from app.services.bounded_io import clamp_limit
from app.services.project_access_service import require_capability
from app.services.project_media_service import (
    project_media_public_url,
    read_project_media_bytes,
)
from app.services.storage_service import media_public_url, read_media_bytes
from app.services.transfer_limits_service import get_transfer_limits
from app.services.upload_file_policy import KIND_DOCUMENT, KIND_FILE, classify_name

#: Kinds whose bytes are read for text. ``file`` is stored as a document and
#: gets the same treatment: text when the bytes are text, nothing otherwise.
_TEXT_KINDS: frozenset[str] = frozenset({KIND_DOCUMENT, KIND_FILE})


def unique_positive_ids(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for raw in ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _reject_video(*, kind: str, mime: str) -> None:
    kind_norm = (kind or "").strip().lower()
    mime_norm = (mime or "").strip().lower()
    if kind_norm == "video" or mime_norm.startswith("video/"):
        raise HTTPException(
            status_code=400,
            detail="Video files cannot be attached to chat. Use an image or a document.",
        )


async def resolve_attach_scope(
    db: AsyncSession,
    *,
    project_id: str | None,
    chat_session_id: str | None,
    user: object | None = None,
) -> str | None:
    """Return the project id media_ids belong to, or None for personal media."""
    requested = (project_id or "").strip() or None
    session_project: str | None = None
    if chat_session_id:
        if user is not None:
            from app.services.chat_session_access import resolve_owned_chat_session

            session = await resolve_owned_chat_session(db, user=user, chat_session_id=chat_session_id)
        else:
            session = await db.get(ChatSession, chat_session_id)
        if session is not None:
            session_project = (session.project_id or "").strip() or None
    if requested and session_project and requested != session_project:
        raise HTTPException(
            status_code=400,
            detail="project_id does not match this chat.",
        )
    if session_project:
        return session_project
    if requested:
        raise HTTPException(
            status_code=400,
            detail="Project media can only be attached from a project chat.",
        )
    return None


async def _read_personal_bytes(row: MediaAsset) -> bytes:
    try:
        return await read_media_bytes(row)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Media not found") from exc


async def _read_project_bytes(
    db: AsyncSession,
    *,
    project_id: str,
    media_id: int,
    user: User,
) -> bytes:
    loaded = await read_project_media_bytes(
        db,
        project_id=project_id,
        media_id=media_id,
        user=user,
    )
    if loaded is None:
        raise HTTPException(status_code=404, detail="Media not found")
    return loaded[1]


def _payload(
    *,
    filename: str,
    kind: str,
    mime_type: str,
    url: str,
    text: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": filename,
        "kind": kind,
        "mime_type": mime_type,
        "url": url,
    }
    if kind in _TEXT_KINDS:
        # Same shape as a fresh upload (``attachment_extract._attach_text``):
        # ``binary`` marks a file whose bytes held no text, so the model is
        # given its name and size rather than replacement-character noise.
        if text is not None:
            item["text"] = text
        else:
            item["binary"] = True
    return item


async def attachments_from_existing_media(
    db: AsyncSession,
    user: User,
    media_ids: list[int],
    *,
    chat_session_id: str | None = None,
    project_id: str | None = None,
) -> list[dict]:
    """Build ProcessedAttachment dicts from already-stored media.

    Images are referenced by URL only. Documents and unknown files (kind
    ``file``) are read for text extraction. Nothing is written back to
    personal or project media storage.
    """
    ids = unique_positive_ids(media_ids)
    if not ids:
        raise HTTPException(status_code=400, detail="No media selected.")

    transfer = await get_transfer_limits(db)
    max_count = int(transfer["max_chat_attachments_count"])
    if len(ids) > max_count:
        raise HTTPException(
            status_code=400,
            detail=f"You can attach up to {max_count} files at once.",
        )
    attachment_limit = clamp_limit(
        int(transfer["max_upload_file_bytes"]),
        minimum=1024 * 1024,
        maximum=1024 * 1024 * 1024,
    )
    total_limit = clamp_limit(
        int(transfer["max_chat_attachments_total_bytes"]),
        minimum=attachment_limit,
        maximum=2048 * 1024 * 1024,
    )

    scoped_project_id = await resolve_attach_scope(
        db,
        project_id=project_id,
        chat_session_id=chat_session_id,
        user=user,
    )
    if scoped_project_id:
        await require_capability(
            db,
            project_id=scoped_project_id,
            user=user,
            capability="media.read",
        )

    out: list[dict] = []
    total_bytes = 0
    for media_id in ids:
        if scoped_project_id:
            row = await db.get(ProjectMediaAsset, media_id)
            if row is None or row.project_id != scoped_project_id:
                raise HTTPException(status_code=404, detail="Media not found")
            url = project_media_public_url(scoped_project_id, int(row.id))
        else:
            row = await db.get(MediaAsset, media_id)
            if row is None or int(row.user_id) != int(user.id):
                raise HTTPException(status_code=404, detail="Media not found")
            url = media_public_url(int(row.id))

        filename = (row.file_name or "attachment").strip() or "attachment"
        mime = (row.mime_type or "").strip()
        _reject_video(kind=str(row.kind or ""), mime=mime)
        # The stored row says ``document`` for anything that is not media; the
        # name decides whether that is a document the platform can parse or a
        # ``file`` it can only offer as text-if-text. Re-classifying also means
        # an asset the operator has since blocked cannot be attached.
        try:
            _, kind = await classify_name(db, filename)
        except AttachmentPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        size = int(row.size_bytes or 0)
        raw: bytes | None = None
        if size <= 0:
            if scoped_project_id:
                raw = await _read_project_bytes(
                    db,
                    project_id=scoped_project_id,
                    media_id=int(row.id),
                    user=user,
                )
            else:
                raw = await _read_personal_bytes(row)
            size = len(raw)
        try:
            validate_attachment_size(size, max_bytes=attachment_limit)
        except AttachmentPolicyError as exc:
            status_code = 413 if "too large" in str(exc).lower() else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        if total_bytes + size > total_limit:
            raise HTTPException(
                status_code=413,
                detail=(f"Attachments exceed the total per-message limit ({max(1, total_limit // (1024 * 1024))} MB)."),
            )
        total_bytes += size

        resolved_mime = resolve_attachment_mime(
            filename=filename,
            kind=kind,
            client_mime=mime,
        )
        text: str | None = None
        if kind in _TEXT_KINDS:
            if raw is None:
                if scoped_project_id:
                    raw = await _read_project_bytes(
                        db,
                        project_id=scoped_project_id,
                        media_id=int(row.id),
                        user=user,
                    )
                else:
                    raw = await _read_personal_bytes(row)
            text = await extract_document_text_bounded(raw, filename)
        out.append(
            _payload(
                filename=filename,
                kind=kind,
                mime_type=resolved_mime,
                url=url,
                text=text,
            )
        )
    return out
