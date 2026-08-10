"""Explicit user memory CRUD API."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_active_user
from app.database import get_db, get_read_db
from app.models.user import User
from app.services.user_memory_service import (
    MemoryLimitError,
    MemoryNotFoundError,
    MemoryValidationError,
    create_memory,
    delete_all_memories,
    delete_memory,
    list_memories,
    update_memory,
)
from app.services.user_profile_context_service import profile_payload

router = APIRouter(prefix="/api/user/memories", tags=["user-memories"])


class MemoryCreateIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    source_session_id: str | None = None


class MemoryPatchIn(BaseModel):
    content: str | None = Field(None, min_length=1, max_length=2000)
    enabled: bool | None = None


def _validation_error(exc: MemoryValidationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc) or "Invalid memory")


def _limit_error(exc: MemoryLimitError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc) or "Memory limit reached")


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Memory not found")


@router.get("")
async def get_user_memories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    items = await list_memories(db, user.id, include_disabled=True)
    # Re-load from this session so directory fields stay current for Personalization UI.
    fresh = await db.get(User, user.id)
    return {
        "memories": items,
        "total": len(items),
        "profile": profile_payload(fresh or user),
    }


@router.post("")
async def post_user_memory(
    body: MemoryCreateIn,
    response: Response,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload, created = await create_memory(
            db,
            user.id,
            body.content,
            source_session_id=body.source_session_id,
        )
        await db.commit()
    except MemoryValidationError as exc:
        raise _validation_error(exc) from exc
    except MemoryLimitError as exc:
        raise _limit_error(exc) from exc
    response.status_code = 201 if created else 200
    return payload


@router.patch("/{memory_id}")
async def patch_user_memory(
    memory_id: str,
    body: MemoryPatchIn,
    user: User = Depends(require_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if body.content is None and body.enabled is None:
        raise HTTPException(status_code=400, detail="No updates provided")
    try:
        payload = await update_memory(
            db,
            user.id,
            memory_id,
            content=body.content,
            enabled=body.enabled,
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
        await delete_memory(db, user.id, memory_id)
        await db.commit()
    except MemoryNotFoundError as exc:
        raise _not_found() from exc
    return {"ok": True}


@router.delete("")
async def delete_all_user_memories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    removed = await delete_all_memories(db, user.id)
    await db.commit()
    return {"ok": True, "deleted": removed}
