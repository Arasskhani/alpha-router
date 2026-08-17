"""Administrative legal-hold, retention, and audit-integrity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_agent_permission
from app.database import get_db
from app.models.knowledge import LegalHold
from app.models.user import User
from app.services.agent_governance_service import (
    SUPPORTED_HOLD_RESOURCE_TYPES,
    place_legal_hold,
    release_legal_hold,
    verify_governance_audit_chain,
)
from app.services.knowledge_retention_service import (
    schedule_expired_knowledge_retention,
)
from app.services.retention_policy_service import purge_expired_chat_messages

router = APIRouter(
    prefix="/api/admin/agents/governance",
    tags=["admin-agent-governance"],
)


class LegalHoldCreateBody(BaseModel):
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=8000)


class LegalHoldReleaseBody(BaseModel):
    reason: str | None = Field(default=None, max_length=8000)


def _hold_payload(hold: LegalHold) -> dict:
    return {
        "id": hold.id,
        "resource_type": hold.resource_type,
        "resource_id": hold.resource_id,
        "status": hold.status,
        "reason": hold.reason,
        "placed_by_user_id": hold.placed_by_user_id,
        "released_by_user_id": hold.released_by_user_id,
        "placed_at": hold.placed_at,
        "released_at": hold.released_at,
    }


@router.get("/holds")
async def list_legal_holds(
    status: str | None = Query(default=None, pattern=r"^(active|released)$"),
    resource_type: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=250, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("governance.read")),
):
    statement = select(LegalHold)
    if status:
        statement = statement.where(LegalHold.status == status)
    if resource_type:
        statement = statement.where(LegalHold.resource_type == resource_type)
    rows = (
        (
            await db.execute(
                statement.order_by(LegalHold.placed_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_hold_payload(row) for row in rows],
        "supported_resource_types": sorted(SUPPORTED_HOLD_RESOURCE_TYPES),
    }


@router.post("/holds")
async def create_legal_hold(
    body: LegalHoldCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("governance.hold.manage")),
):
    try:
        hold = await place_legal_hold(
            db,
            resource_type=body.resource_type,
            resource_id=body.resource_id,
            reason=body.reason,
            actor_user_id=user.id,
        )
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return _hold_payload(hold)


@router.post("/holds/{hold_id}/release")
async def release_hold(
    hold_id: str,
    body: LegalHoldReleaseBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("governance.hold.manage")),
):
    try:
        hold = await release_legal_hold(
            db,
            hold_id=hold_id,
            actor_user_id=user.id,
            reason=body.reason,
        )
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    return _hold_payload(hold)


@router.get("/audit/verify")
async def verify_audit_chain(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("governance.read")),
):
    verification = await verify_governance_audit_chain(db)
    return {
        "valid": verification.valid,
        "event_count": verification.event_count,
        "first_invalid_event_id": verification.first_invalid_event_id,
        "head_hash": verification.head_hash,
    }


@router.post("/retention/run")
async def run_retention(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("governance.retention.run")),
):
    chat = await purge_expired_chat_messages(db)
    knowledge = await schedule_expired_knowledge_retention(
        db,
        actor_user_id=user.id,
    )
    await db.commit()
    return {"chat": chat, "knowledge": knowledge}
