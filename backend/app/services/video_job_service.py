"""Lifecycle + in-process worker for async video generation jobs."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import logging
import time
import uuid
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.text_safety import strip_nul
from app.database import AsyncSessionLocal
from app.models.model_catalog import AIModel
from app.models.user import User
from app.models.video import VideoGenerationJob
from app.services.openrouter_video_service import (
    parse_video_duration,
    normalize_video_aspect_ratio,
    normalize_video_resolution,
)
from app.services.video_providers import NormalizedVideoRequest, ProviderJobRef, get_video_adapter
from app.services.storage_service import (
    media_content_hash,
    media_public_url,
)
from app.services.user_chat_storage_service import finalize_chat_session_video
from app.services.project_media_service import collect_personal_media_ids, persist_scoped_chat_media
from app.services.video_billing_service import VideoBillingCapture, log_video_usage
from app.services.failure_details import describe_failure
from app.services.observability import correlation_scope, increment

_LOG = logging.getLogger("alpha_router.video_jobs")
_ACTIVE_TASKS: dict[str, asyncio.Task] = {}
_WORKER_TASK: asyncio.Task | None = None
_WORKER_STOP = asyncio.Event()
_TERMINAL = frozenset({"completed", "failed", "cancelled"})

# A failed poll is not a failed job. The clip is still being generated on the
# provider's side; all that broke is one status GET, and the next one a few
# seconds later almost always succeeds. Killing the job on the first network
# hiccup threw away work the user is billed for and reported a provider error
# that never happened. Only an unbroken run of failures means the provider is
# genuinely unreachable -- and the overall job deadline still applies
# throughout, so this can never extend a job past its timeout.
_MAX_CONSECUTIVE_POLL_FAILURES = 5


def _is_transient_poll_failure(exc: BaseException) -> bool:
    """True when retrying the same status GET is worth a try.

    Transport errors and 429/5xx are the provider or the path between us
    being briefly unavailable. A 4xx (bad job id, revoked key) or a malformed
    body will fail identically forever, so those are raised at once.
    """
    import httpx

    from app.services.openrouter_image_service import is_retryable_openrouter_transport_error

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        return status == 429 or status >= 500
    if isinstance(exc, LeaseLost):
        return False
    return is_retryable_openrouter_transport_error(exc)


class LeaseLost(RuntimeError):
    """Another worker now owns this job's lease; this runner must stop touching it.

    Raised inside the poll loop when the row's ``lease_owner`` no longer
    matches the claim this runner started with (the lease expired and
    ``claim_due_video_jobs`` handed the job to someone else). The job row,
    the reservation and billing all belong to the new owner from that point.
    """


class VideoJobAlreadyCompleted(RuntimeError):
    """The provider finished the job before the cancel reached it."""


# How long a claimed job stays leased to one worker, and how often a long
# phase renews that lease. The heartbeat must stay well under the lease so a
# single slow beat never lets a second worker claim a job that is running.
_LEASE_SECONDS = 120
_LEASE_HEARTBEAT_SECONDS = 30


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


def serialize_job(job: VideoGenerationJob, *, include_provider: bool = False) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if job.params_json:
        try:
            loaded = json.loads(job.params_json)
            if isinstance(loaded, dict):
                params = loaded
        except json.JSONDecodeError:
            params = {}
    media_url = None
    if job.media_asset_id:
        media_url = media_public_url(int(job.media_asset_id))
    if not media_url:
        stored = params.get("result_media_url")
        if isinstance(stored, str) and stored.strip():
            media_url = stored.strip()
    out: dict[str, Any] = {
        "id": job.id,
        "status": job.status,
        "operation": job.operation,
        "model": job.model_id,
        "prompt": job.prompt,
        "params": params,
        "media_url": media_url,
        "media_asset_id": job.media_asset_id,
        "chat_session_id": job.chat_session_id,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() + "Z" if job.created_at else None,
        "updated_at": job.updated_at.isoformat() + "Z" if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() + "Z" if job.completed_at else None,
    }
    request_log_id = params.get("request_log_id")
    if request_log_id is not None:
        with contextlib.suppress(TypeError, ValueError):
            out["request_log_id"] = int(request_log_id)
    if include_provider:
        out["provider_job_id"] = job.provider_job_id
    return out


async def count_active_jobs(db: AsyncSession, user_id: int) -> int:
    result = await db.execute(
        select(func.count(VideoGenerationJob.id)).where(
            VideoGenerationJob.user_id == user_id,
            VideoGenerationJob.status.in_(("queued", "running")),
        )
    )
    return int(result.scalar_one() or 0)


async def create_video_job(
    db: AsyncSession,
    *,
    user: User,
    model_id: str,
    prompt: str,
    operation: str,
    params: dict[str, Any],
    chat_session_id: str | None,
    persist: bool,
    reference_image: str | None,
    budget_reservation_id: str | None,
    idempotency_key: str | None,
    catalog_model_id: int | None,
    source_ip: str | None,
    connection_id: int | None = None,
    provider_type: str = "openrouter",
    adapter_key: str | None = None,
    capability_snapshot: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> VideoGenerationJob:
    settings = get_settings()
    if idempotency_key:
        existing = (
            await db.execute(
                select(VideoGenerationJob).where(
                    VideoGenerationJob.user_id == user.id,
                    VideoGenerationJob.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    max_concurrent = max(1, int(settings.video_max_concurrent_jobs_per_user or 1))
    active = await count_active_jobs(db, user.id)
    if active >= max_concurrent:
        raise PermissionError(f"Video generation concurrency limit reached ({max_concurrent} active job(s))")

    duration = parse_video_duration(params.get("duration"))
    if duration is None:
        raise ValueError("duration is required")
    resolution = normalize_video_resolution(params.get("resolution"))
    aspect = normalize_video_aspect_ratio(params.get("aspect_ratio"))
    clean_params = {
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect,
        "generate_audio": bool(params.get("generate_audio", False)),
    }
    if params.get("seed") is not None:
        clean_params["seed"] = params.get("seed")
    assistant_cid = str(params.get("assistant_client_message_id") or "").strip()
    if assistant_cid:
        clean_params["assistant_client_message_id"] = assistant_cid

    adapter = get_video_adapter(provider_type, adapter_key=adapter_key)
    job_id = str(uuid.uuid4())
    reference_storage_path = None
    reference_image_mime = None
    if reference_image:
        from app.services.bounded_io import decode_data_url_bounded
        from app.services import object_storage_service as oss

        reference_bytes, reference_image_mime = decode_data_url_bounded(
            reference_image,
            max_decoded_bytes=int(settings.max_media_input_bytes),
        )
        reference_storage_path = f"private/video-input/{job_id}.bin"
        await asyncio.to_thread(oss.put_object, reference_storage_path, reference_bytes, reference_image_mime)
    job = VideoGenerationJob(
        id=job_id,
        user_id=user.id,
        project_id=(project_id or "").strip() or None,
        chat_session_id=(chat_session_id or "").strip() or None,
        model_id=model_id,
        catalog_model_id=catalog_model_id,
        connection_id=connection_id,
        provider_type=(provider_type or "unknown").strip().lower(),
        adapter_key=(adapter_key or provider_type or "unknown").strip().lower(),
        adapter_version=getattr(adapter, "adapter_version", None),
        operation=(operation or "generation").strip().lower(),
        status="queued",
        prompt=strip_nul(prompt) or "",
        params_json=json.dumps(clean_params),
        budget_reservation_id=budget_reservation_id,
        idempotency_key=(idempotency_key or "")[:160] or None,
        persist=1 if persist else 0,
        reference_image=None,
        reference_storage_path=reference_storage_path,
        reference_image_mime=reference_image_mime,
        capability_snapshot_json=json.dumps(capability_snapshot or {}),
        source_ip=(source_ip or "")[:64] or None,
        created_at=_now(),
        updated_at=_now(),
        expires_at=_now() + datetime.timedelta(seconds=int(settings.video_job_timeout_seconds or 600) + 300),
        next_action_at=_now(),
    )
    db.add(job)
    await db.flush()
    return job


async def claim_due_video_jobs(*, limit: int = 4) -> list[str]:
    """Claim due jobs using a short lease so multiple workers cannot duplicate work."""
    now = _now()
    lease_until = now + datetime.timedelta(seconds=_LEASE_SECONDS)
    owner = f"video-worker:{uuid.uuid4()}"
    async with AsyncSessionLocal() as db:
        query = (
            select(VideoGenerationJob)
            .where(
                VideoGenerationJob.status.in_(("queued", "submitted", "running", "ingesting")),
                (VideoGenerationJob.next_action_at.is_(None) | (VideoGenerationJob.next_action_at <= now)),
                (VideoGenerationJob.lease_expires_at.is_(None) | (VideoGenerationJob.lease_expires_at < now)),
            )
            .order_by(VideoGenerationJob.created_at.asc())
            .limit(max(1, min(limit, 16)))
            .with_for_update(skip_locked=True)
        )
        rows = (await db.execute(query)).scalars().all()
        ids: list[str] = []
        for job in rows:
            job.lease_owner = owner
            job.lease_expires_at = lease_until
            job.attempt_count = int(job.attempt_count or 0) + 1
            job.next_action_at = None
            ids.append(job.id)
        if ids:
            await db.commit()
        return ids


async def _durable_worker_loop() -> None:
    """Continuously claim DB jobs; safe to run in each application worker."""
    while not _WORKER_STOP.is_set():
        try:
            job_ids = await claim_due_video_jobs()
            if job_ids:
                await asyncio.gather(*(_run_video_job(job_id) for job_id in job_ids))
            else:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- logged; expected failure of an external dependency
            _LOG.exception("Video durable worker iteration failed")
            await asyncio.sleep(2.0)


def start_video_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK is None or _WORKER_TASK.done():
        _WORKER_STOP.clear()
        _WORKER_TASK = asyncio.create_task(_durable_worker_loop(), name="video-durable-worker")


async def stop_video_worker() -> None:
    global _WORKER_TASK
    _WORKER_STOP.set()
    if _WORKER_TASK and not _WORKER_TASK.done():
        _WORKER_TASK.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _WORKER_TASK
    _WORKER_TASK = None


def kick_video_job(job_id: str) -> None:
    """Compatibility hook: durable workers discover queued jobs from the DB."""
    del job_id
    start_video_worker()


async def cancel_video_job(db: AsyncSession, job: VideoGenerationJob) -> VideoGenerationJob:
    if job.status in _TERMINAL:
        return job
    job.cancel_requested_at = _now()
    if job.provider_job_id:
        try:
            from app.models.connection import Connection
            from app.services.secret_crypto import decrypt_secret

            model = await db.get(AIModel, job.catalog_model_id) if job.catalog_model_id else None
            conn = await db.get(Connection, job.connection_id) if job.connection_id else None
            if model and conn and conn.is_active:
                adapter = get_video_adapter(job.provider_type, adapter_key=job.adapter_key)
                api_key = decrypt_secret(conn.api_key_encrypted)
                ref = ProviderJobRef(
                    provider_type=job.provider_type,
                    provider_job_id=job.provider_job_id,
                    polling_url=job.provider_polling_url,
                )
                # The provider may already have finished (and charged for) the
                # clip. Cancelling now would release the hold and drop a paid
                # result on the floor; let the runner ingest and bill it.
                try:
                    snapshot = await adapter.poll(api_key=api_key, base_url=conn.base_url, job=ref)
                except Exception:  # noqa: BLE001 -- falls back to a safe default value
                    snapshot = None
                if snapshot is not None and snapshot.state == "completed":
                    job.cancel_requested_at = None
                    raise VideoJobAlreadyCompleted(job.id)
                await adapter.cancel(
                    api_key=api_key,
                    base_url=conn.base_url,
                    job=ref,
                )
        except VideoJobAlreadyCompleted:
            raise
        except Exception:  # noqa: BLE001 -- logged; expected failure of an external dependency
            _LOG.warning("Provider cancel failed for video job %s", job.id, exc_info=True)
    job.status = "cancelled"
    job.error_code = "cancelled"
    job.error_message = "Cancelled by user"
    job.completed_at = _now()
    job.updated_at = _now()
    if job.budget_reservation_id:
        from app.services.budget_reservation_service import release

        await release(db, job.budget_reservation_id)
    await db.flush()
    task = _ACTIVE_TASKS.get(job.id)
    if task and not task.done():
        task.cancel()
    return job


async def reclaim_stale_video_jobs() -> int:
    """Mark stuck running/queued jobs as failed and settle billing when possible."""
    settings = get_settings()
    cutoff = _now() - datetime.timedelta(seconds=int(settings.video_job_reclaim_after_seconds or 900))
    reclaimed = 0
    async with AsyncSessionLocal() as db:
        if db.get_bind().dialect.name == "postgresql":
            locked = await db.execute(text("SELECT pg_try_advisory_xact_lock(56023119)"))
            if not bool(locked.scalar()):
                return 0
        rows = (
            (
                await db.execute(
                    select(VideoGenerationJob).where(
                        # "submitted" and "ingesting" belong here too: a worker that
                        # dies mid-submit or mid-ingest used to leave the job stuck
                        # in those states forever, holding its budget reservation
                        # and leaving the chat bubble pending with nothing to heal
                        # it. Safe to sweep now only because a live run heartbeats
                        # its lease, and the lease guard below skips those.
                        VideoGenerationJob.status.in_(("queued", "submitted", "running", "ingesting")),
                        VideoGenerationJob.updated_at < cutoff,
                        (
                            VideoGenerationJob.lease_expires_at.is_(None)
                            | (VideoGenerationJob.lease_expires_at < _now())
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for job in rows:
            job.status = "failed"
            job.error_code = "timeout"
            job.error_message = "Video job timed out and was reclaimed"
            job.completed_at = _now()
            job.updated_at = _now()
            reclaimed += 1
            try:
                user = await db.get(User, job.user_id)
                ai_model = await db.get(AIModel, job.catalog_model_id) if job.catalog_model_id else None
                if user:
                    capture = VideoBillingCapture(
                        model_id=job.model_id,
                        ai_model=ai_model,
                        provider_type=ai_model.provider_type if ai_model else "openrouter",
                    )
                    capture.add_usage(None, success=False, error_message=job.error_message)
                    await log_video_usage(
                        db,
                        user=user,
                        capture=capture,
                        prompt=job.prompt or "",
                        response_time_ms=0,
                        success=False,
                        error_message=job.error_message,
                        source_ip=job.source_ip,
                        operation=job.operation,
                        budget_reservation_id=job.budget_reservation_id,
                        job_id=job.id,
                        project_id=job.project_id,
                        error_code=job.error_code or "reclaimed",
                        provider_job_id=job.provider_job_id,
                    )
            except Exception:  # noqa: BLE001 -- logged; expected failure of an external dependency
                _LOG.exception("Failed settling reclaimed video job %s", job.id)
        if reclaimed:
            await db.commit()
    return reclaimed


async def _touch_video_job_lease(job_id: str, owner: str | None) -> bool:
    """Renew one job's lease and updated_at from an independent session.

    Returns False when the row is gone, already terminal, or has been taken
    over by another worker - the caller must then stop beating.
    """
    now = _now()
    conditions = [
        VideoGenerationJob.id == job_id,
        VideoGenerationJob.status.not_in(tuple(_TERMINAL)),
    ]
    if owner:
        conditions.append(VideoGenerationJob.lease_owner == owner)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(VideoGenerationJob)
            .where(*conditions)
            .values(
                lease_expires_at=now + datetime.timedelta(seconds=_LEASE_SECONDS),
                updated_at=now,
            )
        )
        await db.commit()
        return bool(result.rowcount)


@contextlib.asynccontextmanager
async def _lease_heartbeat(job_id: str, owner: str | None):
    """Keep the lease and updated_at fresh across a long, beat-less phase.

    The provider poll loop renews the lease on every iteration; ingest
    (provider download + object-storage write) is a single long await with no
    such beat. Left alone, an ingest longer than the lease lets
    claim_due_video_jobs hand the same "ingesting" job to a second worker -
    duplicate media and duplicate billing - and an ingest longer than
    VIDEO_JOB_RECLAIM_AFTER_SECONDS lets reclaim_stale_video_jobs mark a job
    that is actually succeeding as failed.
    """
    stop = asyncio.Event()

    async def beat() -> None:
        while not stop.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=_LEASE_HEARTBEAT_SECONDS)
            if stop.is_set():
                return
            try:
                if not await _touch_video_job_lease(job_id, owner):
                    return
            except Exception:  # noqa: BLE001 -- logged; expected failure of an external dependency
                _LOG.warning("Lease heartbeat failed for video job %s", job_id, exc_info=True)

    task = asyncio.create_task(beat(), name=f"video-lease-{job_id}")
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _provider_failure_text(snapshot: Any, status: str) -> str:
    """Why the provider ended the job — never an empty string.

    ``RuntimeError(snapshot.error_message)`` stored "None" when the provider
    reported a terminal state without any reason, and the caller then showed
    the user a bare "Video generation failed". When there is no text, say which
    state the provider reported and quote a little of its last payload.
    """
    message = (getattr(snapshot, "error_message", None) or "").strip() if snapshot is not None else ""
    if message:
        return message[:2000]
    provider_status = (getattr(snapshot, "provider_status", None) or status or "unknown").strip()
    raw = getattr(snapshot, "raw", None)
    excerpt = ""
    if isinstance(raw, dict):
        try:
            excerpt = json.dumps(raw, ensure_ascii=False)[:500]
        except (TypeError, ValueError):
            excerpt = ""
    base = f"Provider ended the job as '{provider_status}' without an error message"
    return f"{base}: {excerpt}" if excerpt else base


async def _run_video_job(job_id: str) -> None:  # noqa: C901 -- Phase 4 split; complexity must not grow
    # The job id doubles as this run's correlation id, so every log line the
    # worker writes carries it and the API Logs row points back at them.
    with correlation_scope(job_id):
        await _run_video_job_inner(job_id)


async def _run_video_job_inner(job_id: str) -> None:  # noqa: C901 -- same body, one indent in
    started = time.perf_counter()
    async with AsyncSessionLocal() as db:
        job = await db.get(VideoGenerationJob, job_id)
        if job is None or job.status in _TERMINAL:
            return
        # Whoever claimed this job owns its lease; the heartbeat renews only
        # that claim, so a stale runner can never steal it back.
        lease_owner = job.lease_owner
        user = await db.get(User, job.user_id)
        if user is None:
            job.status = "failed"
            job.error_code = "user_missing"
            job.error_message = "User not found"
            job.completed_at = _now()
            job.updated_at = _now()
            await db.commit()
            return

        ai_model = await db.get(AIModel, job.catalog_model_id) if job.catalog_model_id else None
        api_key = None
        base_url = None
        provider_type = job.provider_type or "openrouter"
        if ai_model is not None:
            from app.models.connection import Connection
            from app.services.secret_crypto import decrypt_secret

            conn = await db.get(Connection, ai_model.connection_id)
            if conn and conn.is_active:
                api_key = decrypt_secret(conn.api_key_encrypted)
                base_url = conn.base_url
                provider_type = job.provider_type or conn.provider_type or "openrouter"

        billing = VideoBillingCapture(
            model_id=job.model_id,
            ai_model=ai_model,
            provider_type=provider_type,
        )
        params: dict[str, Any] = {}
        if job.params_json:
            try:
                loaded = json.loads(job.params_json)
                if isinstance(loaded, dict):
                    params = loaded
            except json.JSONDecodeError:
                params = {}

        duration = parse_video_duration(params.get("duration"))
        success = False
        lease_lost = False
        error_message: str | None = None
        error_code: str | None = None
        http_status: int | None = None
        settings = get_settings()
        deadline = time.monotonic() + float(settings.video_job_timeout_seconds or 600)
        poll_interval = max(0.5, float(settings.video_job_poll_interval_ms or 2500) / 1000.0)

        try:
            if duration is None:
                raise RuntimeError("Video job is missing a duration")
            if not api_key:
                raise RuntimeError(f"No active {provider_type} connection for video model")
            adapter = get_video_adapter(provider_type, adapter_key=job.adapter_key)
            increment("video_job_started")

            job.status = "running"
            job.started_at = job.started_at or _now()
            job.updated_at = _now()
            await db.commit()

            reference_bytes = None
            reference_mime = job.reference_image_mime
            if job.reference_storage_path:
                from app.services import object_storage_service as oss

                reference_bytes = await asyncio.to_thread(
                    oss.get_object_bytes,
                    job.reference_storage_path,
                )
                input_path = job.reference_storage_path
                job.reference_storage_path = None
                await asyncio.to_thread(oss.delete_object, input_path)
                if job.operation != "img2vid":
                    job.operation = "img2vid"

            normalized_request = NormalizedVideoRequest(
                model_id=job.model_id,
                prompt=job.prompt,
                operation=job.operation,
                duration_seconds=duration,
                resolution=params.get("resolution"),
                aspect_ratio=params.get("aspect_ratio"),
                generate_audio=bool(params.get("generate_audio", False)),
                reference_image=reference_bytes,
                reference_image_mime=reference_mime,
                seed=params.get("seed"),
            )
            submit_started = _now()
            if job.provider_job_id:
                provider_job = ProviderJobRef(
                    provider_type=job.provider_type,
                    provider_job_id=job.provider_job_id,
                    polling_url=job.provider_polling_url,
                )
            else:
                job.status = "submitting"
                provider_job = await adapter.submit(
                    api_key=api_key,
                    base_url=base_url,
                    request=normalized_request,
                )
                increment("video_provider_submit")
                job.provider_job_id = provider_job.provider_job_id
                job.provider_polling_url = provider_job.polling_url
                job.status = "submitted"
                job.updated_at = _now()
                await db.commit()

            final_snapshot = None
            status = "submitted"
            poll_failures = 0
            while status not in _TERMINAL:
                if time.monotonic() > deadline:
                    raise TimeoutError("Video generation timed out")
                # Reload cancel + ownership state
                await db.refresh(job)
                if job.status == "cancelled":
                    raise asyncio.CancelledError()
                if lease_owner and job.lease_owner != lease_owner:
                    raise LeaseLost(job_id)
                job.lease_expires_at = _now() + datetime.timedelta(seconds=_LEASE_SECONDS)
                # Commit before sleeping/polling: otherwise this transaction (and
                # its pooled connection) stays open for the whole provider wait.
                await db.commit()
                await asyncio.sleep(poll_interval)
                try:
                    final_snapshot = await adapter.poll(
                        api_key=api_key,
                        base_url=base_url,
                        job=provider_job,
                    )
                except Exception as exc:  # noqa: BLE001 -- re-raised unless it is worth another poll
                    if not _is_transient_poll_failure(exc):
                        raise
                    poll_failures += 1
                    detail = describe_failure(exc)
                    _LOG.warning(
                        "video poll failed (%s/%s) job=%s: %s",
                        poll_failures,
                        _MAX_CONSECUTIVE_POLL_FAILURES,
                        job_id,
                        detail.message,
                    )
                    if poll_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                        raise
                    # Back to the top: the deadline, the cancel check and the
                    # lease heartbeat all run again before the next attempt.
                    continue
                poll_failures = 0
                status = final_snapshot.state
                job.provider_status_raw = json.dumps(final_snapshot.raw)[:20000]
                # When the provider signals completion, transition to "ingesting"
                # — NOT "completed" — so the frontend keeps polling until the
                # media asset is stored and media_url is available.
                if status == "completed":
                    job.status = "ingesting"
                elif status in _TERMINAL:
                    job.status = status
                else:
                    job.status = "running"
                job.updated_at = _now()
                await db.commit()

            if status == "cancelled":
                raise asyncio.CancelledError()
            if status != "completed" or final_snapshot is None:
                raise RuntimeError(_provider_failure_text(final_snapshot, status))

            # Fetching the asset and writing it to object storage can outlast
            # the lease; beat while it runs so no second worker claims this job.
            async with _lease_heartbeat(job_id, lease_owner):
                asset_ref = await adapter.fetch_result(
                    api_key=api_key,
                    base_url=base_url,
                    snapshot=final_snapshot,
                )

                from app.services.video_media_ingest_service import fetch_video_asset

                blob, mime = await fetch_video_asset(
                    url=asset_ref.url,
                    api_key=api_key,
                    requires_auth=asset_ref.requires_auth,
                    allowed_hosts=asset_ref.allowed_hosts,
                )
                usage = adapter.normalize_usage(final_snapshot)
                # Ensure provider cost/duration land under usage.* so
                # extract_normalized_usage can treat OpenRouter cost as exact.
                usage_payload: dict = dict(usage.raw) if isinstance(usage.raw, dict) else {}
                usage_obj = dict(usage_payload["usage"]) if isinstance(usage_payload.get("usage"), dict) else {}
                if usage.quantity is not None:
                    usage_obj.setdefault("duration_seconds", usage.quantity)
                if usage.cost_usd is not None:
                    usage_obj["cost"] = usage.cost_usd
                if usage_obj:
                    usage_payload["usage"] = usage_obj
                billing.add_usage(
                    usage_payload or usage.raw,
                    started_at=submit_started,
                    success=True,
                    quantity=usage.quantity or float(duration),
                    unit=usage.unit or "second",
                )

                media_url: str | None = None
                if int(job.persist or 0) == 1:
                    storage_blob, storage_mime, _digest = media_content_hash(blob, mime, "video")
                    media_url = await persist_scoped_chat_media(
                        db,
                        user=user,
                        project_id=job.project_id,
                        kind="video",
                        blob=storage_blob,
                        mime=storage_mime,
                        file_name="generated.mp4",
                        source_model=job.model_id,
                        source_prompt=job.prompt,
                        chat_session_id=job.chat_session_id,
                        metadata={"operation": job.operation, "duration": duration},
                    )
                    personal_ids = collect_personal_media_ids(media_url)
                    job.media_asset_id = next(iter(personal_ids), None)
                    params["result_media_url"] = media_url
                    job.params_json = json.dumps(params)
                    if job.chat_session_id:
                        await finalize_chat_session_video(
                            db,
                            user.id,
                            job.chat_session_id,
                            media_url,
                            job.prompt,
                            job.model_id,
                            params={
                                "duration": duration,
                                "resolution": params.get("resolution"),
                                "aspect_ratio": params.get("aspect_ratio"),
                                "operation": job.operation,
                            },
                        )
                else:
                    # Private mode uses a short-lived object, never SQL base64.
                    from app.services import object_storage_service as oss

                    private_key = f"private/videos/{job.id}.{mime.rsplit('/', 1)[-1]}"
                    await asyncio.to_thread(oss.put_object, private_key, blob, mime)
                    job.ephemeral_storage_path = private_key
                    job.ephemeral_expires_at = _now() + datetime.timedelta(minutes=15)
                    media_url = f"/api/videos/jobs/{job.id}/private-file"

            job.status = "completed"
            increment("video_job_completed")
            job.lease_owner = None
            job.lease_expires_at = None
            job.completed_at = _now()
            job.updated_at = _now()
            job.error_code = None
            job.error_message = None
            success = True
            await db.commit()
        except LeaseLost:
            # Not ours any more: no status change, no release, no billing.
            lease_lost = True
            await db.rollback()
            _LOG.warning("Video job %s lease taken over by another worker; runner %s stops", job_id, lease_owner)
            increment("video_job_lease_lost")
        except asyncio.CancelledError:
            await db.refresh(job)
            if job.status != "cancelled":
                job.status = "cancelled"
                job.error_code = "cancelled"
                job.error_message = "Cancelled"
                job.completed_at = _now()
                job.updated_at = _now()
            job.lease_owner = None
            job.lease_expires_at = None
            error_message = job.error_message
            error_code = job.error_code or "cancelled"
            billing.add_usage(None, success=False, error_message=error_message)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
            # str(exc) is empty for every httpx timeout and a bare ConnectError,
            # which used to store a failure with no reason at all.
            failure = describe_failure(exc)
            error_message = failure.message
            error_code = failure.code
            http_status = failure.http_status
            job.status = "failed"
            job.error_code = failure.code
            job.error_message = error_message
            job.completed_at = _now()
            job.updated_at = _now()
            job.lease_owner = None
            job.lease_expires_at = None
            billing.add_usage(None, success=False, error_message=error_message)
            await db.commit()
            _LOG.warning("Video job %s failed: %s", job_id, error_message)
            increment("video_job_failed")
        finally:
            # A runner that lost its lease settles nothing; the new owner does.
            if not lease_lost:
                try:
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    log_id = await log_video_usage(
                        db,
                        user=user,
                        capture=billing,
                        prompt=job.prompt or "",
                        response_time_ms=elapsed_ms,
                        success=success,
                        error_message=error_message,
                        source_ip=job.source_ip,
                        operation=job.operation,
                        budget_reservation_id=job.budget_reservation_id,
                        duration_seconds=duration,
                        job_id=job.id,
                        project_id=job.project_id,
                        error_code=error_code,
                        http_status=http_status,
                        provider_job_id=job.provider_job_id,
                        correlation_id=job_id,
                    )
                    if log_id and success:
                        job_params: dict[str, Any] = {}
                        if job.params_json:
                            try:
                                loaded = json.loads(job.params_json)
                                if isinstance(loaded, dict):
                                    job_params = loaded
                            except json.JSONDecodeError:
                                job_params = {}
                        job_params["request_log_id"] = int(log_id)
                        job.params_json = json.dumps(job_params)
                        assistant_cid = str(job_params.get("assistant_client_message_id") or "").strip()
                        if job.chat_session_id:
                            from app.services.user_chat_storage_service import (
                                attach_request_log_id_to_chat_message,
                            )

                            await attach_request_log_id_to_chat_message(
                                db,
                                user.id,
                                job.chat_session_id,
                                int(log_id),
                                client_message_id=assistant_cid or None,
                            )
                    await db.commit()
                except Exception:  # noqa: BLE001 -- logged; expected failure of an external dependency
                    _LOG.exception("Failed to settle video billing for job %s", job_id)
