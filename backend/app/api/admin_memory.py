"""Admin configuration, stats, reindex, and purge for automatic user memory."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_memory, require_memory_write
from app.database import get_db, get_read_db
from app.models.chat import UserMemory, UserMemoryJob
from app.models.cost_accounting import UsageOperation
from app.models.project import ProjectMemory, ProjectMemoryJob
from app.models.user import User
from app.services.memory_job_admin_service import list_failed_jobs, retry_failed_jobs
from app.services.memory_maintenance_service import reindex_all_memories
from app.services.memory_relearn_service import MAX_DAYS, RelearnUnavailable, estimate_relearn, start_relearn
from app.services.memory_settings_service import (
    MemorySettingsError,
    get_memory_settings,
    update_memory_settings,
)
from app.services.user_memory_service import delete_all_memories

router = APIRouter(prefix="/api/admin/memory", tags=["admin-memory"])


class MemorySettingsPatch(BaseModel):
    feature_enabled: bool | None = None
    extraction_model_id: int | None = Field(default=None)
    embedding_model: str | None = None
    embedding_dimensions: int | None = Field(default=None, ge=0, le=65_536)
    extract_debounce_seconds: int | None = Field(default=None, ge=5, le=3600)
    extract_max_wait_seconds: int | None = Field(default=None, ge=30, le=7200)
    extract_min_new_messages: int | None = Field(default=None, ge=1, le=20)
    extract_max_tokens: int | None = Field(default=None, ge=256, le=16_000)
    extract_monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    max_per_user: int | None = Field(default=None, ge=10, le=500)
    inject_max_items: int | None = Field(default=None, ge=1, le=50)
    inject_max_chars: int | None = Field(default=None, ge=200, le=8000)
    core_items: int | None = Field(default=None, ge=0, le=20)
    semantic_top_k: int | None = Field(default=None, ge=0, le=40)
    lexical_top_k: int | None = Field(default=None, ge=0, le=40)
    min_similarity: float | None = Field(default=None, ge=0, le=1)
    retrieval_timeout_ms: int | None = Field(default=None, ge=50, le=5000)
    allowed_sensitive_categories: list[str] | None = None
    stale_archive_days: int | None = Field(default=None, ge=0, le=3650)
    soft_delete_purge_days: int | None = Field(default=None, ge=1, le=365)
    suppression_days: int | None = Field(default=None, ge=1, le=3650)
    history_completion_enabled: bool | None = None
    relearn_enabled: bool | None = None
    context_fit_enabled: bool | None = None
    context_share_percent: int | None = Field(default=None, ge=30, le=95)
    context_default_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    summary_enabled: bool | None = None
    summary_model_id: int | None = Field(default=None)
    summary_keep_recent: int | None = Field(default=None, ge=4, le=200)
    summary_monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    summary_person_monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    recall_person_monthly_budget_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    recall_enabled: bool | None = None
    plan_memory_enabled: bool | None = None
    plan_ttl_days: int | None = Field(default=None, ge=7, le=365)
    recall_max_items: int | None = Field(default=None, ge=1, le=10)
    recall_max_chars: int | None = Field(default=None, ge=500, le=12_000)
    recall_min_similarity: float | None = Field(default=None, ge=0, le=1)
    project_feature_enabled: bool | None = None
    project_max_per_project: int | None = Field(default=None, ge=10, le=2000)
    project_inject_max_items: int | None = Field(default=None, ge=1, le=200)
    project_inject_max_chars: int | None = Field(default=None, ge=200, le=24_000)
    project_manual_items: int | None = Field(default=None, ge=0, le=200)
    project_extract_debounce_seconds: int | None = Field(default=None, ge=5, le=3600)
    project_extract_max_wait_seconds: int | None = Field(default=None, ge=30, le=7200)
    project_extract_min_new_messages: int | None = Field(default=None, ge=1, le=20)
    project_semantic_top_k: int | None = Field(default=None, ge=0, le=60)
    project_lexical_top_k: int | None = Field(default=None, ge=0, le=60)
    project_min_similarity: float | None = Field(default=None, ge=0, le=1)


@router.get("/settings")
async def get_settings(
    db: AsyncSession = Depends(get_read_db),
    _user: User = Depends(require_memory),
) -> dict[str, Any]:
    return await get_memory_settings(db)


async def _audit(db: AsyncSession, request: Request, admin: User, action: str, resource_id: str, detail: dict) -> None:
    """One Admin Logs row for a change made on Admin -> Memory."""
    from app.services.client_ip import resolve_client_ip
    from app.services.security_audit import log_security_event

    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action=action,
        resource_type="memory",
        resource_id=resource_id,
        detail=detail,
    )


@router.patch("/settings")
async def patch_settings(
    body: MemorySettingsPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_memory_write),
) -> dict[str, Any]:
    """Save the settings; a save that changes something is recorded as memory_settings_changed.

    The record has each changed setting before and after. These decide what
    is learned about people, with which model, at what cost and for how long:
    exactly what an auditor looks for. Nothing in them is secret.
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return await get_memory_settings(db)
    before = await get_memory_settings(db)
    try:
        result = await update_memory_settings(db, updates)
    except MemorySettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    changes = {
        name: {"from": before.get(name), "to": result.get(name)}
        for name in sorted(result)
        if before.get(name) != result.get(name)
    }
    if changes:
        await _audit(db, request, admin, "memory_settings_changed", "settings", {"changes": changes})
    await db.commit()
    return result


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_read_db),
    _user: User = Depends(require_memory),
) -> dict[str, Any]:
    import datetime as dt

    now = dt.datetime.utcnow()
    total = int(
        (
            await db.execute(select(func.count()).select_from(UserMemory).where(UserMemory.deleted_at.is_(None)))
        ).scalar_one()
        or 0
    )
    week = int(
        (
            await db.execute(
                select(func.count())
                .select_from(UserMemory)
                .where(
                    UserMemory.deleted_at.is_(None),
                    UserMemory.created_at >= now - dt.timedelta(days=7),
                )
            )
        ).scalar_one()
        or 0
    )
    jobs = (await db.execute(select(UserMemoryJob.status, func.count()).group_by(UserMemoryJob.status))).all()
    jobs_by_status = {str(status): int(count) for status, count in jobs}
    oldest_pending = (
        await db.execute(
            select(func.min(UserMemoryJob.created_at)).where(UserMemoryJob.status.in_(("pending", "retry")))
        )
    ).scalar_one_or_none()
    oldest_age = None
    if oldest_pending is not None:
        oldest_age = max(0, int((now - oldest_pending).total_seconds()))
    dead = int(jobs_by_status.get("dead") or 0)
    backlog = int(
        (
            await db.execute(
                select(func.count())
                .select_from(UserMemory)
                .where(
                    UserMemory.deleted_at.is_(None),
                    UserMemory.embedding_status.in_(("pending", "failed")),
                )
            )
        ).scalar_one()
        or 0
    )
    extract_cost = (
        await db.execute(
            select(func.coalesce(func.sum(UsageOperation.total_cost_usd), 0)).where(
                UsageOperation.operation_type == "memory_extract",
                UsageOperation.started_at >= now - dt.timedelta(days=30),
            )
        )
    ).scalar_one()
    from app.services.memory_extraction_service import extraction_spend_this_month

    # Month to date, both scopes, on the same clock the cap uses.
    extract_cost_mtd = await extraction_spend_this_month(db)
    project_total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ProjectMemory)
                .where(
                    ProjectMemory.deleted_at.is_(None),
                    ProjectMemory.source_type == "auto_chat",
                )
            )
        ).scalar_one()
        or 0
    )
    project_manual = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ProjectMemory)
                .where(
                    ProjectMemory.deleted_at.is_(None),
                    ProjectMemory.source_type != "auto_chat",
                )
            )
        ).scalar_one()
        or 0
    )
    project_jobs = (
        await db.execute(select(ProjectMemoryJob.status, func.count()).group_by(ProjectMemoryJob.status))
    ).all()
    project_jobs_by_status = {str(status): int(count) for status, count in project_jobs}
    project_backlog = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ProjectMemory)
                .where(
                    ProjectMemory.deleted_at.is_(None),
                    ProjectMemory.embedding_status.in_(("pending", "failed")),
                )
            )
        ).scalar_one()
        or 0
    )
    project_extract_cost = (
        await db.execute(
            select(func.coalesce(func.sum(UsageOperation.total_cost_usd), 0)).where(
                UsageOperation.operation_type == "project_memory_extract",
                UsageOperation.started_at >= now - dt.timedelta(days=30),
            )
        )
    ).scalar_one()
    return {
        "total_memories": total,
        "memories_last_7d": week,
        "jobs_by_status": jobs_by_status,
        "oldest_pending_job_age_seconds": oldest_age,
        "dead_letter_count": dead,
        "embedding_backlog": backlog,
        "extraction_cost_usd_30d": float(extract_cost or 0),
        "extraction_cost_usd_mtd": float(extract_cost_mtd or 0),
        "retrieval_p95_seconds": None,
        "project_learned_memories": project_total,
        "project_manual_memories": project_manual,
        "project_jobs_by_status": project_jobs_by_status,
        "project_dead_letter_count": int(project_jobs_by_status.get("dead") or 0),
        "project_embedding_backlog": project_backlog,
        "project_extraction_cost_usd_30d": float(project_extract_cost or 0),
    }


@router.get("/failed-jobs")
async def get_failed_jobs(
    scope: Literal["user", "project"] = Query("user"),
    db: AsyncSession = Depends(get_read_db),
    _user: User = Depends(require_memory),
) -> dict[str, Any]:
    """Extraction jobs that failed for good: how many, why, and the newest of them."""
    return await list_failed_jobs(db, scope)


class RetryFailedJobs(BaseModel):
    scope: Literal["user", "project"]
    job_ids: list[str] | None = Field(default=None, max_length=500)


@router.post("/failed-jobs/retry")
async def post_retry_failed_jobs(
    body: RetryFailedJobs,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_memory_write),
) -> dict[str, Any]:
    """Run failed jobs again from where their chats were mined to; audited."""
    counts = await retry_failed_jobs(db, body.scope, job_ids=body.job_ids)
    selected = len(body.job_ids) if body.job_ids is not None else "all"
    await _audit(
        db, request, admin, "memory_jobs_retried", body.scope, {"scope": body.scope, "selected": selected, **counts}
    )
    await db.commit()
    return {"ok": True, "scope": body.scope, **counts}


@router.get("/relearn/estimate")
async def get_relearn_estimate(
    days: int = Query(30, ge=1, le=MAX_DAYS),
    db: AsyncSession = Depends(get_read_db),
    _user: User = Depends(require_memory),
) -> dict[str, Any]:
    """What reading the last ``days`` of chats again would take, before anything is run."""
    return await estimate_relearn(db, days=days)


class StartRelearn(BaseModel):
    days: int = Field(ge=1, le=MAX_DAYS)


@router.post("/relearn")
async def post_relearn(
    body: StartRelearn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_memory_write),
) -> dict[str, Any]:
    """Queue the last ``days`` of chats to be read again for memory; audited."""
    try:
        result = await start_relearn(db, days=body.days)
    except RelearnUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    detail = {key: result[key] for key in ("days", "chats", "messages", "parts", "queued", "merged")}
    await _audit(db, request, admin, "memory_relearn_started", "relearn", detail)
    await db.commit()
    return {"ok": True, **result}


@router.get("/recall/status")
async def get_recall_status(
    db: AsyncSession = Depends(get_read_db),
    _user: User = Depends(require_memory),
) -> dict[str, Any]:
    """How far the index of earlier chats has got, and its jobs."""
    from app.services.chat_recall_service import recall_status

    return await recall_status(db)


@router.get("/recall/backfill/estimate")
async def get_recall_backfill_estimate(
    db: AsyncSession = Depends(get_read_db),
    _user: User = Depends(require_memory),
) -> dict[str, Any]:
    """What indexing the chats not yet indexed would take, before anything is run."""
    from app.services.chat_recall_service import estimate_backfill

    return await estimate_backfill(db)


@router.post("/recall/backfill")
async def post_recall_backfill(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_memory_write),
) -> dict[str, Any]:
    """Queue every chat with something not yet indexed for recall; audited."""
    from app.services.chat_recall_service import start_backfill

    try:
        result = await start_backfill(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _audit(db, request, admin, "memory_recall_backfill_started", "recall", dict(result))
    await db.commit()
    return {"ok": True, **result}


@router.post("/reindex")
async def post_reindex(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_memory_write),
) -> dict[str, Any]:
    try:
        result = await reindex_all_memories(db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _audit(db, request, admin, "memory_index_rebuilt", "index", dict(result))
    await db.commit()
    return {"ok": True, **result}


@router.post("/purge-user/{user_id}")
async def post_purge_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_memory_write),
) -> dict[str, Any]:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    deleted = await delete_all_memories(db, user_id, actor="admin")
    await _audit(db, request, admin, "memory_user_purged", str(user_id), {"user_id": user_id, "deleted": deleted})
    await db.commit()
    return {"ok": True, "deleted": deleted, "user_id": user_id, "purged_by": admin.id}
