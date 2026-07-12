"""User media library API (per-user quota, search, schedule, bulk ops)."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_active_user
from app.database import get_db
from app.models.user import User
from app.models.user_media_prefs import UserMediaPreferences
from app.services.storage_service import purge_expired_media
from app.services.user_media_service import (
    _media_row_dict,
    MediaZipLimitError,
    build_media_zip_file,
    delete_all_user_media,
    delete_user_media_ids,
    get_or_create_user_media_prefs,
    get_user_media_quota_bytes,
    list_user_media_filtered,
    prefs_to_dict,
    stream_media_zip,
    user_media_quota_summary,
)

router = APIRouter(prefix="/api/user/media", tags=["user-media"])


class BulkDeleteIn(BaseModel):
    ids: list[int] = Field(default_factory=list)


class DownloadZipIn(BaseModel):
    ids: list[int] = Field(default_factory=list)


class SchedulePatchIn(BaseModel):
    cleanup_enabled: bool | None = None
    cleanup_retention_days: int | None = None
    cleanup_hour: int | None = None
    cleanup_minute: int | None = None


@router.get("/quota")
async def media_quota(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await purge_expired_media(db)
    return await user_media_quota_summary(db, user.id)


@router.get("")
async def list_media(
    q: str | None = Query(None, description="Search prompt, filename, model, kind"),
    from_date: str | None = Query(None, description="Gregorian date YYYY-MM-DD"),
    to_date: str | None = Query(None, description="Gregorian date YYYY-MM-DD"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await purge_expired_media(db)
    rows, total = await list_user_media_filtered(
        db,
        user.id,
        q=q,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_media_row_dict(r) for r in rows],
        "total": total,
        "quota_bytes": await get_user_media_quota_bytes(db),
    }


@router.get("/schedule")
async def get_media_schedule(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    prefs = await get_or_create_user_media_prefs(db, user.id)
    return prefs_to_dict(prefs)


@router.patch("/schedule")
async def patch_media_schedule(
    body: SchedulePatchIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    prefs = await get_or_create_user_media_prefs(db, user.id)
    if body.cleanup_enabled is not None:
        prefs.cleanup_enabled = bool(body.cleanup_enabled)
    if body.cleanup_retention_days is not None:
        prefs.cleanup_retention_days = max(1, min(3650, int(body.cleanup_retention_days)))
    if body.cleanup_hour is not None:
        prefs.cleanup_hour = max(0, min(23, int(body.cleanup_hour)))
    if body.cleanup_minute is not None:
        prefs.cleanup_minute = max(0, min(59, int(body.cleanup_minute)))
    await db.flush()
    return {"ok": True, "schedule": prefs_to_dict(prefs)}


@router.post("/download-zip")
async def download_media_zip(
    body: DownloadZipIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        path, _packed = await build_media_zip_file(db, user.id, body.ids)
    except MediaZipLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"nitro-media-{stamp}.zip"
    return StreamingResponse(
        stream_media_zip(path),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/bulk-delete")
async def bulk_delete_media(
    body: BulkDeleteIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await delete_user_media_ids(db, user.id, body.ids)
    return {"ok": True, "removed": removed}


@router.delete("/all")
async def delete_all_media(user: User = Depends(require_active_user), db: AsyncSession = Depends(get_db)):
    removed = await delete_all_user_media(db, user.id)
    return {"ok": True, "removed": removed}


@router.delete("/{asset_id}")
async def delete_one_media(
    asset_id: int,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
):
    removed = await delete_user_media_ids(db, user.id, [asset_id])
    if not removed:
        raise HTTPException(404, detail="Media not found")
    return {"ok": True}
