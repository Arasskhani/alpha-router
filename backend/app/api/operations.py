"""Admin Operations dashboard (replaces legacy Debug latency UI)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operations, require_operations_write, require_super_admin
from app.database import get_db
from app.models.user import User
from app.services.operations_service import get_operations_dashboard

router = APIRouter(prefix="/api/admin/operations", tags=["operations"])


@router.get("/dashboard")
async def operations_dashboard(
    record: bool = Query(False, description="When true, record a new snapshot (Check Now)."),
    range: str = Query(
        "past_1d",
        description="Time window preset (e.g. past_1d, past_1h, today, this_week).",
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_operations),
):
    return await get_operations_dashboard(db, record=record, range_key=range)


@router.post("/check-now")
async def operations_check_now(
    range: str = Query("past_1d", description="Time window preset for refreshed charts."),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_operations_write),
):
    return await get_operations_dashboard(db, record=True, range_key=range)


@router.post("/data-key-rotation")
async def data_key_rotation(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Phase 9: re-encrypt all stored secrets with the primary data key.

    Super Admin only. Idempotent — a second call is a no-op once the rotation
    flag is set. Returns per-table counts of re-encrypted rows; no plaintext.
    """
    from app.db_migrate import apply_data_key_rotation

    return await apply_data_key_rotation(db)
