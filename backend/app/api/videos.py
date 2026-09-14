"""Async video generation API (Text-to-Video / Image-to-Video via OpenRouter)."""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_active_user
from app.api.images import resolve_reference_image_for_upstream
from app.config import get_settings
from app.core.text_safety import strip_nul
from app.database import get_db
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.user import User
from app.models.video import VideoGenerationJob
from app.services.budget_reservation_service import (
    reservation_hold_usd,
    reservation_key,
    reserve,
)
from app.services.model_access_service import resolve_access_subject, user_can_access_model
from app.services.model_capabilities import video_generation_capabilities
from app.services.openrouter_video_service import (
    catalog_video_durations,
    parse_video_duration,
    normalize_video_aspect_ratio,
    normalize_video_resolution,
)
from app.services.secret_crypto import decrypt_secret
from app.services.video_job_service import (
    VideoJobAlreadyCompleted,
    cancel_video_job,
    create_video_job,
    kick_video_job,
    serialize_job,
)
from app.services import object_storage_service as oss
from app.services.video_providers import get_video_adapter
from app.services.chat_channel_guard import assert_session_allows_model_generation
from app.services.project_billing_service import resolve_project_id_for_request

router = APIRouter(prefix="/api/videos", tags=["videos"])


class VideoRequest(BaseModel):
    prompt: str
    model: str
    operation: str = "generation"  # generation | img2vid
    reference_image: str | None = None
    chat_session_id: str | None = None
    project_id: str | None = None
    persist: bool = True
    duration: int | None = None
    resolution: str | None = "720p"
    aspect_ratio: str | None = "16:9"
    generate_audio: bool = False
    seed: int | None = None
    routing: dict[str, Any] | None = None
    assistant_client_message_id: str | None = None


def _normalize_model_id(raw: str) -> str:
    return (raw or "").strip()


async def _resolve_video_model(
    db: AsyncSession,
    raw_model: str,
    *,
    access_user_id: int | None = None,
) -> tuple[str, str | None, str | None, str | None, AIModel | None]:
    model_id = _normalize_model_id(raw_model)
    subject = await resolve_access_subject(db, user_id=access_user_id) if access_user_id is not None else None
    row: AIModel | None = None
    if model_id.startswith("model::"):
        try:
            model_pk = int(model_id.split("::", 1)[1])
        except Exception:
            model_pk = None
        if model_pk is not None:
            row = (
                (
                    await db.execute(
                        select(AIModel).where(AIModel.id == model_pk, AIModel.is_enabled == True)  # noqa: E712
                    )
                )
                .scalars()
                .first()
            )
        if row:
            conn = await db.get(Connection, row.connection_id)
            if conn and conn.is_active:
                if subject is None or await user_can_access_model(db, row, subject):
                    return (
                        row.external_id,
                        decrypt_secret(conn.api_key_encrypted),
                        conn.base_url,
                        conn.provider_type,
                        row,
                    )
            row = None

    if not row:
        candidates = (
            await db.execute(
                select(AIModel, Connection)
                .join(Connection, Connection.id == AIModel.connection_id)
                .where(
                    AIModel.external_id == model_id,
                    AIModel.is_enabled == True,  # noqa: E712
                    Connection.is_active == True,  # noqa: E712
                )
                .order_by(AIModel.id.desc())
            )
        ).all()
        for cand_row, conn in candidates:
            if subject is None or await user_can_access_model(db, cand_row, subject):
                return (
                    cand_row.external_id,
                    decrypt_secret(conn.api_key_encrypted),
                    conn.base_url,
                    conn.provider_type,
                    cand_row,
                )

    return model_id, None, None, None, None


def _client_ip(request: Request) -> str | None:
    from app.services.client_ip import resolve_client_ip

    return resolve_client_ip(request)


@router.post("/generate")
async def generate_video(
    request: Request,
    body: VideoRequest,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    await assert_session_allows_model_generation(db, body.chat_session_id)
    settings = get_settings()
    prompt = strip_nul((body.prompt or "").strip())
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    model_id, api_key, _base_url, provider_type, ai_model = await _resolve_video_model(
        db, body.model, access_user_id=user.id
    )
    if not api_key or ai_model is None:
        raise HTTPException(status_code=400, detail="Video model is not available")
    try:
        connection = await db.get(Connection, ai_model.connection_id)
        adapter_key = (getattr(connection, "adapter_key", None) or provider_type or "unknown").strip().lower()
        get_video_adapter(provider_type or "unknown", adapter_key=adapter_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    caps = video_generation_capabilities(
        external_id=model_id,
        is_video_model=bool(getattr(ai_model, "is_video_model", False)),
        pricing_raw=ai_model.pricing_raw,
    )
    operation = (body.operation or "generation").strip().lower()
    if body.reference_image and operation not in ("img2vid", "image_to_video"):
        operation = "img2vid"
    if operation in ("img2vid", "image_to_video"):
        operation = "img2vid"
        if not caps.get("supports_image_to_video"):
            raise HTTPException(status_code=400, detail="Selected model does not support image-to-video")
        if not body.reference_image:
            raise HTTPException(status_code=400, detail="reference_image is required for image-to-video")
    else:
        operation = "generation"
        if not caps.get("supports_text_to_video") and not caps.get("supports_image_to_video"):
            # Allow if catalog marks is_video_model even without modality metadata.
            if not getattr(ai_model, "is_video_model", False):
                raise HTTPException(status_code=400, detail="Selected model does not support video generation")

    duration = parse_video_duration(body.duration)
    if duration is None:
        raise HTTPException(status_code=400, detail="Duration is required")
    resolution = normalize_video_resolution(body.resolution)
    max_res = normalize_video_resolution(settings.video_max_resolution)
    # Simple ordinal check via known list order.
    order = ["480p", "720p", "1080p", "1K", "2K", "4K"]
    try:
        if order.index(resolution) > order.index(max_res):
            resolution = max_res
    except ValueError:
        resolution = "720p"
    aspect_ratio = normalize_video_aspect_ratio(body.aspect_ratio) or "16:9"
    supported_durations = catalog_video_durations(caps.get("supported_durations"))
    if supported_durations and duration not in set(supported_durations):
        raise HTTPException(status_code=400, detail="Requested duration is not supported by the selected video model")
    max_duration = int(settings.video_max_duration_seconds or 0)
    if max_duration > 0 and duration > max_duration:
        raise HTTPException(
            status_code=400,
            detail=f"Requested duration exceeds the deployment limit of {max_duration}s",
        )
    supported_resolutions = {str(value).lower() for value in (caps.get("supported_resolutions") or [])}
    if supported_resolutions and resolution.lower() not in supported_resolutions:
        raise HTTPException(status_code=400, detail="Requested resolution is not supported by the selected video model")
    supported_aspects = {str(value) for value in (caps.get("supported_aspect_ratios") or [])}
    if supported_aspects and aspect_ratio not in supported_aspects:
        raise HTTPException(
            status_code=400, detail="Requested aspect ratio is not supported by the selected video model"
        )

    hold_body = body.model_dump()
    if request.headers.get("Idempotency-Key"):
        hold_body["_idempotency_key"] = request.headers["Idempotency-Key"]
    hold = await reserve(
        db,
        user_id=user.id,
        alpha_router_api_key_id=None,
        amount_usd=await reservation_hold_usd(
            db,
            service_type="video",
            ai_model=ai_model,
            provider_type=provider_type or "unknown",
            model_id=model_id,
            quantity=float(duration),
            unit="second",
        ),
        operation="video",
        model_id=model_id,
        idempotency_key=reservation_key(hold_body, operation="video"),
    )
    budget_reservation_id = hold.id if hold else None

    reference_image = None
    if body.reference_image:
        reference_image = await resolve_reference_image_for_upstream(db, user, body.reference_image)

    try:
        project_id_for_billing = await resolve_project_id_for_request(
            db,
            user=user,
            chat_session_id=body.chat_session_id,
            project_id=body.project_id,
        )
        job = await create_video_job(
            db,
            user=user,
            model_id=model_id,
            prompt=prompt,
            operation=operation,
            params={
                "duration": duration,
                "resolution": resolution,
                "aspect_ratio": aspect_ratio,
                "generate_audio": bool(body.generate_audio),
                "seed": body.seed,
                "assistant_client_message_id": (body.assistant_client_message_id or "").strip() or None,
            },
            chat_session_id=body.chat_session_id,
            persist=bool(body.persist),
            reference_image=reference_image,
            budget_reservation_id=budget_reservation_id,
            idempotency_key=hold_body.get("_idempotency_key"),
            catalog_model_id=ai_model.id,
            source_ip=_client_ip(request),
            connection_id=ai_model.connection_id,
            provider_type=provider_type or "unknown",
            adapter_key=adapter_key,
            capability_snapshot=caps,
            project_id=project_id_for_billing,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    await db.commit()
    kick_video_job(job.id)
    return serialize_job(job)


@router.get("/jobs/{job_id}")
async def get_video_job(
    job_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job = await db.get(VideoGenerationJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    payload = serialize_job(job)
    if int(job.persist or 0) == 0 and job.status == "completed" and job.ephemeral_storage_path:
        payload["media_url"] = f"/api/videos/jobs/{job.id}/private-file"
    return payload


@router.get("/jobs/{job_id}/private-file")
async def get_private_video_file(
    job_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job = await db.get(VideoGenerationJob, job_id)
    if (
        job is None
        or job.user_id != user.id
        or int(job.persist or 0) == 1
        or job.status != "completed"
        or not job.ephemeral_storage_path
        or (job.ephemeral_expires_at and job.ephemeral_expires_at < datetime.datetime.utcnow())
        or job.ephemeral_consumed_at is not None
    ):
        raise HTTPException(status_code=404, detail="Private video is unavailable")
    try:
        data = await asyncio.to_thread(oss.get_object_bytes, job.ephemeral_storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Private video is unavailable") from None
    job.ephemeral_consumed_at = datetime.datetime.utcnow()
    path = job.ephemeral_storage_path
    job.ephemeral_storage_path = None
    await db.commit()
    await asyncio.to_thread(oss.delete_object, path)
    return Response(content=data, media_type="video/mp4", headers={"Content-Disposition": "inline"})


@router.post("/jobs/{job_id}/cancel")
async def cancel_video_job_endpoint(
    job_id: str,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    job = await db.get(VideoGenerationJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job = await cancel_video_job(db, job)
    except VideoJobAlreadyCompleted:
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail="The provider already finished this video; it will be delivered and billed.",
        )
    await db.commit()
    return serialize_job(job)
