"""Admin configuration, stats, reindex, and purge for automatic user memory."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_storage, require_storage_write
from app.database import get_db, get_read_db
from app.models.chat import UserMemory, UserMemoryJob
from app.models.cost_accounting import UsageOperation
from app.models.project import ProjectMemory, ProjectMemoryJob
from app.models.user import User
from app.services.memory_maintenance_service import reindex_all_memories
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
    _user: User = Depends(require_storage),
) -> dict[str, Any]:
    return await get_memory_settings(db)


@router.patch("/settings")
async def patch_settings(
    body: MemorySettingsPatch,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_storage_write),
) -> dict[str, Any]:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return await get_memory_settings(db)
    try:
        result = await update_memory_settings(db, updates)
        await db.commit()
        return result
    except MemorySettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_read_db),
    _user: User = Depends(require_storage),
) -> dict[str, Any]:
    import datetime as dt

    now = dt.datetime.utcnow()
    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(UserMemory)
                .where(UserMemory.deleted_at.is_(None))
            )
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
    jobs = (
        await db.execute(
            select(UserMemoryJob.status, func.count())
            .group_by(UserMemoryJob.status)
        )
    ).all()
    jobs_by_status = {str(status): int(count) for status, count in jobs}
    oldest_pending = (
        await db.execute(
            select(func.min(UserMemoryJob.created_at)).where(
                UserMemoryJob.status.in_(("pending", "retry"))
            )
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
        await db.execute(
            select(ProjectMemoryJob.status, func.count()).group_by(
                ProjectMemoryJob.status
            )
        )
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
        "retrieval_p95_seconds": None,
        "project_learned_memories": project_total,
        "project_manual_memories": project_manual,
        "project_jobs_by_status": project_jobs_by_status,
        "project_dead_letter_count": int(project_jobs_by_status.get("dead") or 0),
        "project_embedding_backlog": project_backlog,
        "project_extraction_cost_usd_30d": float(project_extract_cost or 0),
    }


@router.post("/reindex")
async def post_reindex(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_storage_write),
) -> dict[str, Any]:
    try:
        result = await reindex_all_memories(db)
        await db.commit()
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/purge-user/{user_id}")
async def post_purge_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_storage_write),
) -> dict[str, Any]:
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    deleted = await delete_all_memories(db, user_id, actor="admin")
    await db.commit()
    return {"ok": True, "deleted": deleted, "user_id": user_id, "purged_by": admin.id}
