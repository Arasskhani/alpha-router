"""In-app chat using enabled models (admin + user)."""

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_active_user
from app.branding import CHAT_CLIENT_APP
from app.config import get_settings
from app.database import get_db
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.budget_service import (
    budget_request_blocked,
    ensure_budget_period,
    get_user_budget_state,
    resolve_monthly_budget,
)
from app.services.bounded_io import BoundedIOError, clamp_limit, read_upload_bounded
from app.services.model_capabilities import image_generation_capabilities, supports_vision
from app.services.media_authorization_service import MediaAccessAction, load_authorized_media_asset
from app.services.attachment_extract import processed_attachment_payload
from app.services.attachment_policy import (
    AttachmentPolicyError,
    MAX_ATTACHMENTS_PER_REQUEST,
    media_response_type_and_disposition,
    resolve_attachment_mime,
    validate_attachment_filename,
    validate_attachment_size,
)
from app.services.chat_title_service import generate_chat_title
from app.services.chat_export_service import (
    ChatExportError,
    build_download_content_disposition,
    build_pdf_content_disposition,
    render_chat_pdf,
)
from app.services.chat_docx_service import ChatExportError as DocxExportError
from app.services.chat_docx_service import render_chat_docx
from app.services.image_prompt_service import (
    ENHANCE_CONTEXTS,
    ENHANCE_MODES,
    enhance_image_generation_prompt,
    enhance_user_prompt,
)
from app.services.model_access_service import filter_models_for_subject, resolve_access_subject
from app.services.proxy_service import STREAM_SSE_HEADERS, preflight_stream_chat, stream_chat
from app.services.transcription_service import transcribe_audio_bytes
from app.services.voice_refine_service import refine_voice_transcript
from app.services.storage_service import (
    list_user_media,
    media_public_url,
    purge_expired_media,
    read_media_bytes,
    store_generated_blob,
    store_generated_media,
    unlink_storage_if_unreferenced,
)
router = APIRouter(prefix="/api/chat", tags=["chat"])

@router.get("/models")
async def chat_models(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    conn_count = (await db.execute(select(func.count()).select_from(Connection))).scalar() or 0
    if conn_count == 0:
        await db.execute(delete(AIModel))
        await db.commit()
        return []

    rows = (
        await db.execute(
            select(AIModel)
            .join(Connection, Connection.id == AIModel.connection_id)
            .where(AIModel.is_enabled == True, Connection.is_active == True)  # noqa: E712
        )
    ).scalars().all()
    subject = await resolve_access_subject(db, user_id=user.id)
    rows = await filter_models_for_subject(db, list(rows), subject)
    return [
        {
            "id": f"model::{m.id}",
            "name": m.display_name or m.external_id,
            "external_id": m.external_id,
            **image_generation_capabilities(
                external_id=m.external_id or "",
                is_image_model=bool(m.is_image_model),
                pricing_raw=m.pricing_raw,
            ),
            "supports_vision": supports_vision(
                external_id=m.external_id or "",
                is_image_model=bool(m.is_image_model),
                pricing_raw=m.pricing_raw,
            ),
            "is_image_model": bool(
                m.is_image_model
                or "image" in (m.external_id or "").lower()
                or "dall" in (m.external_id or "").lower()
                or "flux" in (m.external_id or "").lower()
                or "sdxl" in (m.external_id or "").lower()
                or "stable-diffusion" in (m.external_id or "").lower()
                or "nanobanana" in (m.external_id or "").lower()
            ),
        }
        for m in rows
    ]


class ChatToolsIn(BaseModel):
    web_search: bool = False
    web_search_depth: str = "medium"
    web_fetch: bool = False
    image_generation: bool = False
    code_interpreter: bool = False


class ChatRequest(BaseModel):
    model: str
    messages: list[dict]
    stream: bool = True
    web_search: bool = False
    tools: ChatToolsIn | None = None
    chat_session_id: str | None = None
    persist_chat: bool = False
    user_message: dict | None = None
    assistant_client_message_id: str | None = None


class ChatTitleIn(BaseModel):
    model: str
    messages: list[dict]


class EnhancePromptIn(BaseModel):
    model: str
    prompt: str
    mode: str  # "improve" | "translate" | "translate_improve"
    context: str = "image"  # "image" | "chat"


class EnhanceImagePromptIn(BaseModel):
    model: str
    prompt: str
    mode: str  # "improve" | "translate" | "translate_improve"


class MediaStoreIn(BaseModel):
    kind: str = "image"
    data_url: str | None = None
    source_url: str | None = None
    file_name: str | None = None
    model: str | None = None
    prompt: str | None = None
    chat_session_id: str | None = None
    metadata: dict | None = None


@router.post("/session-title")
async def chat_session_title(
    body: ChatTitleIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Short overview title from conversation start (not the first user message verbatim)."""
    title = await generate_chat_title(db, user, body.model, body.messages)
    return {"title": title}


@router.post("/enhance-prompt")
async def enhance_prompt(
    body: EnhancePromptIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Lightly improve or translate a user prompt (image or chat context)."""
    if body.mode not in ENHANCE_MODES:
        raise HTTPException(status_code=400, detail="Invalid enhancement mode")
    if body.context not in ENHANCE_CONTEXTS:
        raise HTTPException(status_code=400, detail="Invalid enhancement context")
    text = await enhance_user_prompt(
        db, user, body.model, body.prompt, body.mode, context=body.context
    )
    return {"prompt": text}


@router.post("/enhance-image-prompt")
async def enhance_image_prompt(
    body: EnhanceImagePromptIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy endpoint — image context only."""
    if body.mode not in ENHANCE_MODES:
        raise HTTPException(status_code=400, detail="Invalid enhancement mode")
    text = await enhance_image_generation_prompt(db, user, body.model, body.prompt, body.mode)
    return {"prompt": text}


@router.post("/completions")
async def chat_completions(
    request: Request,
    body: ChatRequest,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    tools = body.tools.model_dump() if body.tools else {}
    payload = {
        "model": body.model,
        "messages": body.messages,
        "stream": True,
        "web_search": body.web_search or tools.get("web_search", False),
        "tools": tools,
        "user": user.email or user.username,
        "chat_session_id": body.chat_session_id,
        "persist_chat": body.persist_chat,
        "user_message": body.user_message,
        "assistant_client_message_id": body.assistant_client_message_id,
    }
    resolved = await preflight_stream_chat(
        db,
        payload,
        user_id=user.id,
        skip_budget=False,
    )
    await db.commit()
    gen = stream_chat(
        request,
        payload,
        user_id=user.id,
        username=user.username,
        source="alpha_router_chat",
        client_app=CHAT_CLIENT_APP,
        skip_budget=False,
        resolved=resolved,
    )
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers=STREAM_SSE_HEADERS,
    )


@router.post("/voice")
async def voice_message(
    file: UploadFile = File(...),
    chat_session_id: str | None = Form(None),
    language: str | None = Form(None),
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a voice note, store it, and return transcript for chat."""
    budget, usage = await get_user_budget_state(db, user)
    if blocked := budget_request_blocked(budget, usage):
        raise HTTPException(status_code=402, detail=blocked)

    try:
        voice_limit = clamp_limit(
            get_settings().max_voice_upload_bytes,
            minimum=1024 * 1024,
            maximum=25 * 1024 * 1024,
        )
        raw = await read_upload_bounded(file, max_bytes=voice_limit)
    except BoundedIOError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    mime = (file.content_type or "audio/webm").split(";")[0].strip() or "audio/webm"
    filename = file.filename or "voice.webm"

    try:
        transcript = await transcribe_audio_bytes(
            db,
            raw,
            filename=filename,
            mime_type=mime,
            language=language,
            user_id=user.id,
            username=user.username,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Log the full provider error server-side; return a generic message so
        # upstream STT provider internals are not leaked to the chat client.
        import logging

        logging.getLogger("app.api.chat").exception("Transcription failed")
        raise HTTPException(status_code=502, detail="Transcription failed. Please try again.") from exc

    try:
        asset = await store_generated_blob(
            db,
            user_id=user.id,
            username=user.username,
            kind="audio",
            blob=raw,
            mime=mime,
            source_model=None,
            source_prompt=transcript[:2000],
            chat_session_id=chat_session_id,
            file_name_hint=filename,
            metadata={"transcript": transcript},
        )
    except ValueError as exc:
        status_code = 413 if "limit" in str(exc).lower() or "quota" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {
        "id": asset.id,
        "url": media_public_url(asset.id),
        "transcript": transcript,
        "mime_type": asset.mime_type,
    }


class VoiceRefineIn(BaseModel):
    transcript: str
    model: str | None = None
    context: list[dict] | None = None


@router.post("/voice/refine")
async def refine_voice_message(
    body: VoiceRefineIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Correct speech-to-text errors in a transcript using conversation context."""
    transcript = (body.transcript or "").strip()
    if not transcript:
        return {"transcript": ""}
    model_ref = (body.model or "").strip() or None
    refined = await refine_voice_transcript(db, user, model_ref, transcript, body.context)
    return {"transcript": refined}


@router.post("/attachments/process")
async def process_attachments(
    files: list[UploadFile] = File(...),
    chat_session_id: str | None = Form(None),
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate, store, and extract content from chat attachments."""
    await ensure_budget_period(db, user)
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > MAX_ATTACHMENTS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"You can attach up to {MAX_ATTACHMENTS_PER_REQUEST} files at once.",
        )

    out: list[dict] = []
    total_bytes = 0
    from app.services.transfer_limits_service import get_transfer_limits

    transfer = await get_transfer_limits(db)
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
    for upload in files:
        filename = upload.filename or "attachment"
        try:
            _, kind = validate_attachment_filename(filename)
            remaining = total_limit - total_bytes
            if remaining <= 0:
                raise BoundedIOError(
                    f"Attachments exceed the total per-message limit "
                    f"({max(1, total_limit // (1024 * 1024))} MB)."
                )
            raw = await read_upload_bounded(
                upload,
                max_bytes=min(attachment_limit, remaining),
            )
            validate_attachment_size(len(raw), max_bytes=attachment_limit)
            total_bytes += len(raw)
        except BoundedIOError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except AttachmentPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        mime = resolve_attachment_mime(
            filename=filename,
            kind=kind,
            client_mime=upload.content_type,
        )
        try:
            asset = await store_generated_blob(
                db,
                user_id=user.id,
                username=user.username,
                kind=kind,
                blob=raw,
                mime=mime,
                source_model=None,
                source_prompt=filename,
                chat_session_id=chat_session_id,
                file_name_hint=filename,
                metadata={"attachment": True},
            )
        except ValueError as exc:
            status_code = 413 if "limit" in str(exc).lower() or "quota" in str(exc).lower() else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        out.append(
            processed_attachment_payload(
                filename=filename,
                kind=kind,
                mime_type=asset.mime_type,
                url=media_public_url(asset.id),
                raw=raw,
            )
        )

    return {"attachments": out}


@router.post("/media/store")
async def store_media(
    body: MediaStoreIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        asset = await store_generated_media(
            db,
            user_id=user.id,
            username=user.username,
            kind=body.kind or "image",
            source_model=body.model,
            source_prompt=body.prompt,
            chat_session_id=body.chat_session_id,
            data_url=body.data_url,
            source_url=body.source_url,
            file_name_hint=body.file_name,
            metadata=body.metadata or {},
        )
    except ValueError as exc:
        detail = str(exc)
        if "quota" in detail.lower() or "limit" in detail.lower() or "too large" in detail.lower():
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": asset.id,
        "kind": asset.kind,
        "file_name": asset.file_name,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "expires_at": asset.expires_at.isoformat() if asset.expires_at else None,
        "url": media_public_url(asset.id),
    }


@router.get("/media")
async def user_media(
    limit: int = 200,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await purge_expired_media(db)
    rows = await list_user_media(db, user.id, limit=min(500, max(1, limit)))
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "mime_type": r.mime_type,
            "file_name": r.file_name,
            "size_bytes": r.size_bytes,
            "source_model": r.source_model,
            "source_prompt": r.source_prompt,
            "chat_session_id": r.chat_session_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            "url": media_public_url(r.id),
        }
        for r in rows
    ]


@router.get("/media/{asset_id}/file")
async def media_file(
    asset_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await load_authorized_media_asset(
        db,
        user,
        asset_id,
        action=MediaAccessAction.READ,
    )
    try:
        data = await read_media_bytes(row)
    except FileNotFoundError:
        raise HTTPException(404, detail="File not found") from None
    media_type, content_disposition = media_response_type_and_disposition(
        file_name=row.file_name or "download",
        kind=getattr(row, "kind", None),
        stored_mime=row.mime_type,
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition},
    )


@router.delete("/media/{asset_id}")
async def delete_media(
    asset_id: int,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    row = await load_authorized_media_asset(
        db,
        user,
        asset_id,
        action=MediaAccessAction.DELETE,
    )
    storage_path = row.storage_path
    await db.delete(row)
    await db.flush()
    await unlink_storage_if_unreferenced(db, storage_path)
    return {"ok": True}


class ChatExportPdfIn(BaseModel):
    content: str
    title: str | None = None


@router.post("/export/pdf")
async def export_chat_pdf(
    payload: ChatExportPdfIn,
    user: User = Depends(require_active_user),
):
    """Export an assistant chat message (markdown) to a PDF file.

    The content is the caller's own chat content; it is HTML-escaped before
    markdown parsing, JavaScript is disabled in the render context, and all
    sub-resource requests are aborted (anti-SSRF). See ``chat_export_service``.
    """
    if not payload.content or not payload.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")
    try:
        pdf_bytes = await render_chat_pdf(
            content=payload.content,
            title=payload.title,
        )
    except ChatExportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": build_pdf_content_disposition(payload.title),
            "Cache-Control": "no-store",
        },
    )


class ChatExportDocxIn(BaseModel):
    content: str
    title: str | None = None


@router.post("/export/docx")
async def export_chat_docx(
    payload: ChatExportDocxIn,
    user: User = Depends(require_active_user),
):
    """Export an assistant chat message (markdown) to a Word .docx file.

    ``python-docx`` only constructs the OpenXML package (no code execution, no
    network). See ``chat_docx_service``.
    """
    if not payload.content or not payload.content.strip():
        raise HTTPException(status_code=400, detail="content must not be empty")
    try:
        docx_bytes = await asyncio.to_thread(
            render_chat_docx, content=payload.content, title=payload.title
        )
    except DocxExportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": build_download_content_disposition(payload.title, "docx"),
            "Cache-Control": "no-store",
        },
    )
