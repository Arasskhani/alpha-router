"""Admin Operations dashboard (replaces legacy Debug latency UI)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operations, require_operations_write
from app.database import get_db
from app.models.user import User
from app.services.observability import snapshot
from app.services.operations_service import get_operations_dashboard

router = APIRouter(prefix="/api/admin/operations", tags=["operations"])


class CodeInterpreterCapacityPatch(BaseModel):
    max_concurrent_turns: int = Field(ge=1)
    max_per_subject: int = Field(ge=1)
    retry_after_seconds: int = Field(ge=1, le=300)


def _capacity_payload(policy: dict, runtime: dict, broker: dict) -> dict:
    return {
        "settings": {
            "max_concurrent_turns": int(policy["global_max"]),
            "max_per_subject": int(policy["per_subject_max"]),
            "retry_after_seconds": int(policy["retry_after_seconds"]),
            "lease_ttl_seconds": int(policy["lease_ttl_seconds"]),
            "heartbeat_seconds": int(policy["heartbeat_seconds"]),
            "hard_max_concurrent_turns": int(policy["hard_global_max"]),
        },
        "runtime": {
            "active": int(runtime["active"]),
            "available": int(runtime["available"]),
            "limit": int(runtime["limit"]),
            "utilization_percent": round(
                (int(runtime["active"]) / max(1, int(runtime["limit"]))) * 100,
                1,
            ),
        },
        "broker": broker,
    }


async def _sandbox_broker_capacity() -> dict:
    from app.config import get_settings
    from app.sandbox.executor import DockerBrokerSandboxExecutor

    settings = get_settings()
    broker_url = (settings.code_sandbox_broker_url or "").strip()
    token = (settings.code_sandbox_broker_token or "").strip()
    if not broker_url or not token:
        return {"status": "not_configured"}
    executor = DockerBrokerSandboxExecutor(
        base_url=broker_url,
        token=token,
        execution_timeout_seconds=int(settings.code_sandbox_timeout_seconds or 20),
    )
    try:
        return {"status": "ok", **(await executor.capacity())}
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return {"status": "unavailable"})
        return {"status": "unavailable"}


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


@router.get("/observability")
async def operations_observability(
    _: User = Depends(require_operations),
):
    """Return bounded process-local security counters for operator review."""
    return {"scope": "process", "counters": snapshot()}


@router.get("/code-interpreter-capacity")
async def get_code_interpreter_capacity(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_operations),
):
    from app.services.code_interpreter_capacity_service import (
        code_interpreter_capacity_stats,
        get_code_interpreter_capacity_policy,
    )

    policy = await get_code_interpreter_capacity_policy(db)
    runtime = await code_interpreter_capacity_stats()
    return _capacity_payload(policy, runtime, await _sandbox_broker_capacity())


@router.patch("/code-interpreter-capacity")
async def patch_code_interpreter_capacity(
    body: CodeInterpreterCapacityPatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_operations_write),
):
    from app.services.code_interpreter_capacity_service import (
        code_interpreter_capacity_stats,
        set_code_interpreter_capacity_policy,
        sync_code_interpreter_capacity_policy,
    )

    await set_code_interpreter_capacity_policy(
        db,
        global_max=body.max_concurrent_turns,
        per_subject_max=body.max_per_subject,
        retry_after_seconds=body.retry_after_seconds,
    )
    await db.commit()
    policy = await sync_code_interpreter_capacity_policy(db)
    runtime = await code_interpreter_capacity_stats()
    return _capacity_payload(policy, runtime, await _sandbox_broker_capacity())
