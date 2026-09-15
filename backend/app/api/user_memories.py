"""Automatic user memory API (list, toggle, delete, export)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_active_user
from app.database import get_db, get_read_db
from app.models.user import User
from app.services.memory_settings_service import get_memory_settings
from app.services.user_chat_storage_service import load_user_prefs
from app.services.user_memory_service import (
    MemoryNotFoundError,
    MemoryValidationError,
    delete_all_memories,
    delete_memory,
    export_memories,
    list_memories,
    update_memory,
)
from app.services.user_profile_context_service import profile_payload

router = APIRouter(prefix="/api/user/memories", tags=["user-memories"])


class MemoryPatchIn(BaseModel):
    enabled: bool | None = None
    content: str | None = None


def _validation_error(exc: MemoryValidationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc) or "Invalid memory")


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Memory not found")


@router.get("")
async def get_user_memories(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    items, total = await list_memories(db, user.id, include_disabled=True, limit=limit, offset=offset)
    fresh = await db.get(User, user.id)
    prefs = await load_user_prefs(db, user.id)
    settings = await get_memory_settings(db)
    return {
        "memories": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "profile": profile_payload(fresh or user),
        "auto_capture": bool(prefs.get("memory_auto_capture", True)),
        "memory_enabled": bool(prefs.get("memory_enabled", True)),
        "feature_enabled": bool(settings.get("feature_enabled", True)),
        "extraction_configured": bool(settings.get("extraction_model_id")),
    }


@router.get("/export")
async def export_user_memories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db),
) -> JSONResponse:
    items = await export_memories(db, user.id)
    return JSONResponse(
        content={"memories": items, "total": len(items)},
        headers={"Content-Disposition": 'attachment; filename="alpharouter-memories.json"'},
    )


@router.patch("/{memory_id}")
async def patch_user_memory(
    memory_id: str,
    body: MemoryPatchIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if body.content is not None:
        raise HTTPException(status_code=400, detail="Memory content cannot be edited")
    if body.enabled is None:
        raise HTTPException(status_code=400, detail="No updates provided")
    try:
        payload = await update_memory(
            db,
            user.id,
            memory_id,
            enabled=body.enabled,
            actor="user",
        )
        await db.commit()
        return payload
    except MemoryNotFoundError as exc:
        raise _not_found() from exc
    except MemoryValidationError as exc:
        raise _validation_error(exc) from exc


@router.delete("/{memory_id}")
async def delete_user_memory(
    memory_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await delete_memory(db, user.id, memory_id, actor="user")
        await db.commit()
    except MemoryNotFoundError as exc:
        raise _not_found() from exc
    return {"ok": True}


@router.delete("")
async def delete_all_user_memories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    removed = await delete_all_memories(db, user.id, actor="user")
    await db.commit()
    return {"ok": True, "deleted": removed}
