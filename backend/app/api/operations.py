"""Admin Operations dashboard (replaces legacy Debug latency UI)."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operations, require_operations_write
from app.database import get_db
from app.models.user import User
from app.services.observability import snapshot
from app.services.operations_service import get_operations_dashboard

router = APIRouter(prefix="/api/admin/operations", tags=["operations"])


class CodeInterpreterCapacityPatch(BaseModel):
    max_concurrent_turns: int | None = Field(default=None, ge=1)
    max_per_subject: int | None = Field(default=None, ge=1)
    retry_after_seconds: int | None = Field(default=None, ge=1, le=300)
    #: The off switch. Optional like the rest, so throwing it during an incident
    #: does not mean restating three ceilings from a page the operator may not
    #: have open.
    enabled: bool | None = None


def _effective_capacity(policy: dict, runtime: dict, broker: dict) -> dict:
    """The ceiling a turn actually meets, across both admission gates.

    Two independent semaphores guard the same resource. The application holds a
    leased semaphore in Redis (``CODE_INTERPRETER_CAPACITY_GLOBAL_MAX``, tunable
    at runtime from this page); the broker holds an ``asyncio.Semaphore`` of its
    own (``SANDBOX_MAX_CONCURRENT``, fixed at deploy). Nothing ties the two
    numbers together, so the smaller one decides - and a page that reports only
    the application's ceiling tells the operator "200 available" while the
    broker is refusing everything past 50.
    """
    app_limit = int(runtime["limit"])
    broker_limit: int | None = None
    if broker.get("status") == "ok" and broker.get("max_concurrent") is not None:
        broker_limit = int(broker["max_concurrent"])
    limit = app_limit if broker_limit is None else min(app_limit, broker_limit)
    if broker_limit is None:
        limited_by = "app"
    elif broker_limit < app_limit:
        limited_by = "broker"
    elif broker_limit > app_limit:
        limited_by = "app"
    else:
        limited_by = "both"
    active = int(runtime["active"])
    return {
        "max_concurrent_turns": limit,
        "available": max(0, limit - active),
        "utilization_percent": round((active / max(1, limit)) * 100, 1),
        "limited_by": limited_by,
        #: True when the two gates disagree, which is the state worth showing:
        #: the operational limit on this page is not the one being enforced.
        "mismatch": broker_limit is not None and broker_limit != app_limit,
        "app_max_concurrent_turns": app_limit,
        "broker_max_concurrent": broker_limit,
    }


def _capacity_payload(policy: dict, runtime: dict, broker: dict) -> dict:
    return {
        "settings": {
            "max_concurrent_turns": int(policy["global_max"]),
            "max_per_subject": int(policy["per_subject_max"]),
            "retry_after_seconds": int(policy["retry_after_seconds"]),
            "lease_ttl_seconds": int(policy["lease_ttl_seconds"]),
            "heartbeat_seconds": int(policy["heartbeat_seconds"]),
            "hard_max_concurrent_turns": int(policy["hard_global_max"]),
            "enabled": bool(policy.get("enabled", 1)),
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
        "effective": _effective_capacity(policy, runtime, broker),
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
        enabled=body.enabled,
    )
    await db.commit()
    policy = await sync_code_interpreter_capacity_policy(db)
    runtime = await code_interpreter_capacity_stats()
    return _capacity_payload(policy, runtime, await _sandbox_broker_capacity())

class CodeInterpreterWorkspacePatch(BaseModel):
    """The two limits that bound what a turn may carry into the sandbox."""

    max_workspace_files: int = Field(ge=1, le=1000)
    max_workspace_total_mb: int = Field(ge=1, le=1024)


async def _code_interpreter_settings_payload(db: AsyncSession) -> dict:
    """Everything that governs Code Interpreter, in one answer.

    The three families were spread over three pages and two permissions: the
    concurrency policy on Operations, the workspace limits on Storage
    Management, and the deployment ceilings nowhere at all. An operator tuning
    this feature had to know which page held which half.
    """
    from app.config import get_settings
    from app.services.code_interpreter_capacity_service import (
        code_interpreter_capacity_stats,
        get_code_interpreter_capacity_policy,
    )
    from app.services.transfer_limits_service import get_transfer_limits

    settings = get_settings()
    policy = await get_code_interpreter_capacity_policy(db)
    limits = await get_transfer_limits(db)
    broker = await _sandbox_broker_capacity()
    try:
        runtime = await code_interpreter_capacity_stats()
    except Exception:  # noqa: BLE001 -- the settings page must open during a Redis outage
        runtime = {"active": 0, "limit": policy["global_max"], "available": policy["global_max"]}

    return {
        "policy": {
            "enabled": bool(policy["enabled"]),
            "max_concurrent_turns": policy["global_max"],
            "max_per_subject": policy["per_subject_max"],
            "retry_after_seconds": policy["retry_after_seconds"],
        },
        "workspace": {
            "max_workspace_files": int(limits["max_code_interpreter_workspace_files"]),
            "max_workspace_total_mb": int(limits["max_code_interpreter_workspace_total_mb"]),
        },
        #: Read-only here on purpose: each one is fixed when the containers are
        #: built, and naming the variable is the only useful thing this page can
        #: say about it.
        "deployment": {
            "hard_max_concurrent_turns": {
                "value": policy["hard_global_max"],
                "env": "CODE_INTERPRETER_CAPACITY_GLOBAL_MAX",
            },
            "lease_ttl_seconds": {
                "value": policy["lease_ttl_seconds"],
                "env": "CODE_INTERPRETER_CAPACITY_LEASE_TTL_SECONDS",
            },
            "heartbeat_seconds": {
                "value": policy["heartbeat_seconds"],
                "env": "CODE_INTERPRETER_CAPACITY_HEARTBEAT_SECONDS",
            },
            "execution_timeout_seconds": {
                "value": int(settings.code_sandbox_timeout_seconds or 20),
                "env": "CODE_SANDBOX_TIMEOUT_SECONDS",
            },
            "broker_max_concurrent": {
                "value": broker.get("max_concurrent") if broker.get("status") == "ok" else None,
                "env": "SANDBOX_MAX_CONCURRENT",
            },
        },
        "effective": _effective_capacity(policy, runtime, broker),
        "broker": broker,
    }


@router.get("/code-interpreter-settings")
async def get_code_interpreter_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_operations),
) -> dict:
    return await _code_interpreter_settings_payload(db)


@router.patch("/code-interpreter-workspace")
async def patch_code_interpreter_workspace(
    body: CodeInterpreterWorkspacePatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_operations_write),
) -> dict:
    """The workspace ceilings, from the page that owns Code Interpreter.

    The same two values are still writable from Storage Management, which is
    where they used to live alone; both paths clamp through
    ``set_transfer_limits`` and both are audited, so whichever an operator uses
    the trail reads the same.
    """
    from app.services.client_ip import resolve_client_ip
    from app.services.security_audit import log_security_event
    from app.services.transfer_limits_service import get_transfer_limits, set_transfer_limits

    before = await get_transfer_limits(db)
    try:
        after = await set_transfer_limits(
            db,
            max_code_interpreter_workspace_files=body.max_workspace_files,
            max_code_interpreter_workspace_total_mb=body.max_workspace_total_mb,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    keys = ("max_code_interpreter_workspace_files", "max_code_interpreter_workspace_total_mb")
    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action="code_interpreter_workspace_changed",
        resource_type="code_interpreter",
        detail={
            "before": {key: before.get(key) for key in keys},
            "after": {key: after.get(key) for key in keys},
        },
    )
    await db.commit()
    return await _code_interpreter_settings_payload(db)
