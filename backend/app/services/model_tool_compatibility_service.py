"""Persistent, evidence-based model compatibility for optional chat tools."""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_catalog import (
    AIModel,
    ModelToolCompatibility,
    ModelToolCompatibilityEvent,
)
from app.services.model_capabilities import model_kinds

CODE_INTERPRETER_TOOL = "code_interpreter"
PROBE_VERSION = "v1"

STATUS_UNKNOWN = "unknown"
STATUS_PROBING = "probing"
STATUS_COMPATIBLE = "compatible"
STATUS_DEGRADED = "degraded"
STATUS_INCOMPATIBLE = "incompatible"

OVERRIDE_COMPATIBLE = "compatible"
OVERRIDE_INCOMPATIBLE = "incompatible"

_HARD_FAILURE_REASONS = {
    "malformed_function_call",
    "tool_call_error",
    "no_python_block",
    "invalid_python_block",
    "empty_content",
    "sandbox_protocol_error",
}
_TRANSIENT_FAILURE_REASONS = {
    "authentication_error",
    "provider_rate_limit",
    "provider_timeout",
    "provider_unavailable",
}
# Unclassified upstream errors prove nothing about tool support, so a single one
# must never hide a model. Repeats still fall through to the degraded path.
_INCONCLUSIVE_FAILURE_REASONS = {"provider_error"}
_INCONCLUSIVE_FAILURE_LIMIT = 3
# Stable "this model cannot serve interactive chat" conditions (batch-only
# models, retired ids, no routable provider). Re-checked rarely to save cost.
_UNAVAILABLE_FAILURE_REASON = "model_unavailable"


def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


def is_auto_router_model_id(model_id: str | None) -> bool:
    normalized = (model_id or "").strip().lower().lstrip("~")
    return normalized in {"auto", "auto-beta"} or normalized.endswith(("/auto", "/auto-beta"))


def is_code_interpreter_candidate(model: AIModel) -> bool:
    """Cheap static pre-filter; active probes remain the source of truth.

    Everything about the model's kind goes through ``model_kinds``. This used to
    short-circuit on the raw ``is_image_model`` column and then call
    ``model_kinds`` without ``provider_type`` and without ``is_video_model``,
    which quietly disabled the authoritative-catalog path: a row still carrying
    a guess from an older sync excluded that model from probing for good, and a
    video model was judged as if it were a chat model.
    """
    if not model.is_enabled or model.admin_disabled:
        return False
    kinds = model_kinds(
        external_id=model.external_id,
        is_image_model=bool(model.is_image_model),
        is_video_model=bool(getattr(model, "is_video_model", False)),
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )
    if "image" in kinds or "video" in kinds:
        return False
    return "text" in kinds


def effective_status(
    row: ModelToolCompatibility | None,
    *,
    now: datetime.datetime | None = None,
) -> str:
    if row is None:
        return STATUS_UNKNOWN
    if row.manual_override == OVERRIDE_COMPATIBLE:
        return STATUS_COMPATIBLE
    if row.manual_override == OVERRIDE_INCOMPATIBLE:
        return STATUS_INCOMPATIBLE
    current = now or utcnow()
    if row.quarantine_until and row.quarantine_until > current:
        return STATUS_DEGRADED
    if row.status == STATUS_PROBING:
        return STATUS_UNKNOWN
    return row.status or STATUS_UNKNOWN


def is_verified_compatible(row: ModelToolCompatibility | None) -> bool:
    return effective_status(row) == STATUS_COMPATIBLE


def compatibility_payload(
    row: ModelToolCompatibility | None,
    *,
    static_candidate: bool = True,
    auto_router: bool = False,
) -> dict[str, Any]:
    status = effective_status(row) if static_candidate else STATUS_INCOMPATIBLE
    if auto_router and static_candidate:
        # Auto routers are constrained per request instead of being hidden.
        status = STATUS_COMPATIBLE if status == STATUS_COMPATIBLE else STATUS_UNKNOWN
    if not static_candidate:
        reason_code = "unsupported_model_kind"
        reason_detail = "This model is not a text chat model."
    else:
        reason_code = row.reason_code if row is not None else None
        reason_detail = row.reason_detail if row is not None else None
    return {
        "status": status,
        "compatible": status == STATUS_COMPATIBLE,
        # Blocked models are hidden in chat; unknown models stay usable so the
        # picker keeps working for newly released models.
        "selectable": status in {STATUS_COMPATIBLE, STATUS_UNKNOWN},
        "auto_router": auto_router,
        "verified": row is not None and row.status not in {STATUS_UNKNOWN, STATUS_PROBING},
        "score": round(float(row.score), 4) if row is not None else None,
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "manual_override": row.manual_override if row is not None else None,
        "last_probe_at": row.last_probe_at.isoformat() if row and row.last_probe_at else None,
        "last_success_at": row.last_success_at.isoformat() if row and row.last_success_at else None,
        "last_failure_at": row.last_failure_at.isoformat() if row and row.last_failure_at else None,
        "next_probe_at": row.next_probe_at.isoformat() if row and row.next_probe_at else None,
        "quarantine_until": (row.quarantine_until.isoformat() if row and row.quarantine_until else None),
    }


async def get_compatibility(
    db: AsyncSession,
    *,
    connection_id: int,
    external_model_id: str,
    tool: str = CODE_INTERPRETER_TOOL,
) -> ModelToolCompatibility | None:
    return (
        await db.execute(
            select(ModelToolCompatibility).where(
                ModelToolCompatibility.connection_id == connection_id,
                ModelToolCompatibility.external_model_id == external_model_id,
                ModelToolCompatibility.tool == tool,
            )
        )
    ).scalar_one_or_none()


async def get_or_create_compatibility(
    db: AsyncSession,
    *,
    connection_id: int,
    external_model_id: str,
    model_id: int | None = None,
    tool: str = CODE_INTERPRETER_TOOL,
) -> ModelToolCompatibility:
    existing = await get_compatibility(
        db,
        connection_id=connection_id,
        external_model_id=external_model_id,
        tool=tool,
    )
    if existing is not None:
        if model_id is not None and existing.model_id != model_id:
            existing.model_id = model_id
        return existing

    row = ModelToolCompatibility(
        connection_id=connection_id,
        model_id=model_id,
        external_model_id=external_model_id[:512],
        tool=tool[:64],
        status=STATUS_UNKNOWN,
        score=0.5,
        probe_version=PROBE_VERSION,
        next_probe_at=utcnow(),
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        return row
    except IntegrityError:
        return (
            await db.execute(
                select(ModelToolCompatibility).where(
                    ModelToolCompatibility.connection_id == connection_id,
                    ModelToolCompatibility.external_model_id == external_model_id,
                    ModelToolCompatibility.tool == tool,
                )
            )
        ).scalar_one()


async def ensure_model_compatibility_rows(
    db: AsyncSession,
    models: Iterable[AIModel],
) -> int:
    """Register newly synced text models without guessing compatibility."""
    created = 0
    for model in models:
        if not is_code_interpreter_candidate(model):
            continue
        existing = await get_compatibility(
            db,
            connection_id=model.connection_id,
            external_model_id=model.external_id,
        )
        if existing is None:
            await get_or_create_compatibility(
                db,
                connection_id=model.connection_id,
                external_model_id=model.external_id,
                model_id=model.id,
            )
            created += 1
        elif existing.model_id != model.id:
            existing.model_id = model.id
    return created


async def ensure_all_model_compatibility_rows(db: AsyncSession) -> int:
    models = (
        (
            await db.execute(
                select(AIModel).where(
                    AIModel.is_enabled.is_(True),
                    AIModel.admin_disabled.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    return await ensure_model_compatibility_rows(db, models)


async def compatibility_map_for_models(
    db: AsyncSession,
    models: Iterable[AIModel],
) -> dict[tuple[int, str], ModelToolCompatibility]:
    items = list(models)
    connection_ids = {int(model.connection_id) for model in items}
    if not connection_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(ModelToolCompatibility).where(
                    ModelToolCompatibility.connection_id.in_(connection_ids),
                    ModelToolCompatibility.tool == CODE_INTERPRETER_TOOL,
                )
            )
        )
        .scalars()
        .all()
    )
    return {(int(row.connection_id), row.external_model_id): row for row in rows}


def classify_failure_reason(error: str | None) -> str:
    value = (error or "").lower()
    if "malformed_function_call" in value or "malformed function call" in value:
        return "malformed_function_call"
    if "function call" in value or "tool call" in value:
        return "tool_call_error"
    if "rate limit" in value or "status code: 429" in value:
        return "provider_rate_limit"
    if "timeout" in value or "timed out" in value:
        return "provider_timeout"
    if "authentication" in value or "status code: 401" in value:
        return "authentication_error"
    if "status code: 503" in value or "temporarily unavailable" in value:
        return "provider_unavailable"
    if (
        "status code: 404" in value
        or "notfounderror" in value
        or "only available via" in value
        or "no endpoints found" in value
        or "no allowed providers" in value
        or "is not a valid model" in value
    ):
        return _UNAVAILABLE_FAILURE_REASON
    if "unavailable" in value:
        return "provider_unavailable"
    if "no usable content" in value or "empty" in value:
        return "empty_content"
    return "provider_error"


async def record_compatibility_result(
    db: AsyncSession,
    *,
    connection_id: int,
    external_model_id: str,
    success: bool,
    source: str,
    model_id: int | None = None,
    reason_code: str | None = None,
    detail: str | None = None,
    requested_model_id: str | None = None,
    upstream_request_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> ModelToolCompatibility:
    """Apply one strong probe/runtime observation to score and circuit state."""
    row = await get_or_create_compatibility(
        db,
        connection_id=connection_id,
        external_model_id=external_model_id,
        model_id=model_id,
    )
    now = utcnow()
    row.probe_version = PROBE_VERSION
    if source == "probe":
        row.last_probe_at = now

    if success:
        row.total_successes = int(row.total_successes or 0) + 1
        row.consecutive_successes = int(row.consecutive_successes or 0) + 1
        row.consecutive_failures = 0
        row.last_success_at = now
        row.reason_code = None
        row.reason_detail = None
        row.quarantine_until = None
        row.score = min(1.0, max(float(row.score or 0.5), 0.5) + 0.35)
        row.status = STATUS_COMPATIBLE
        row.next_probe_at = now + datetime.timedelta(days=7)
    else:
        code = reason_code or classify_failure_reason(detail)
        row.total_failures = int(row.total_failures or 0) + 1
        row.consecutive_failures = int(row.consecutive_failures or 0) + 1
        row.consecutive_successes = 0
        row.last_failure_at = now
        row.reason_code = code[:64]
        row.reason_detail = (detail or "")[:1000] or None
        transient = code in _TRANSIENT_FAILURE_REASONS
        hard = code in _HARD_FAILURE_REASONS
        unavailable = code == _UNAVAILABLE_FAILURE_REASON
        inconclusive = (
            code in _INCONCLUSIVE_FAILURE_REASONS and int(row.consecutive_failures) < _INCONCLUSIVE_FAILURE_LIMIT
        )
        penalty = 0.1 if (transient or inconclusive) else (0.45 if hard else 0.25)
        row.score = max(0.0, float(row.score or 0.5) - penalty)
        if transient or inconclusive:
            # Never hide a model on evidence that is not about tool support; a
            # previously verified model also keeps its verification.
            row.status = STATUS_COMPATIBLE if int(row.total_successes or 0) > 0 else STATUS_UNKNOWN
            row.quarantine_until = None
            row.next_probe_at = now + datetime.timedelta(hours=1)
        elif unavailable:
            # Stable provider-side unavailability: block, but re-check rarely.
            row.status = STATUS_INCOMPATIBLE
            row.quarantine_until = None
            row.next_probe_at = now + datetime.timedelta(days=7)
        elif source == "probe":
            # A failed probe is direct evidence, so the state is reported as
            # incompatible instead of a time-boxed quarantine. `next_probe_at`
            # still allows automatic recovery later.
            row.status = STATUS_INCOMPATIBLE
            row.quarantine_until = None
            row.next_probe_at = now + datetime.timedelta(hours=24)
        elif hard or row.consecutive_failures >= 2:
            row.status = STATUS_DEGRADED
            row.quarantine_until = now + datetime.timedelta(hours=24 if hard else 6)
            row.next_probe_at = row.quarantine_until
        else:
            row.status = STATUS_DEGRADED
            row.quarantine_until = now + datetime.timedelta(minutes=30)
            row.next_probe_at = row.quarantine_until

    row.evidence_json = json.dumps(evidence, ensure_ascii=False)[:8000] if evidence else None
    row.updated_at = now
    db.add(
        ModelToolCompatibilityEvent(
            compatibility=row,
            source=source[:24],
            success=success,
            reason_code=(reason_code or (None if success else row.reason_code)),
            detail=(detail or "")[:2000] or None,
            requested_model_id=(requested_model_id or "")[:512] or None,
            upstream_request_id=(upstream_request_id or "")[:255] or None,
            evidence_json=(json.dumps(evidence, ensure_ascii=False)[:8000] if evidence else None),
        )
    )
    await db.flush()
    return row


async def set_manual_override(
    db: AsyncSession,
    row: ModelToolCompatibility,
    override: str | None,
    *,
    actor: str | None = None,
) -> ModelToolCompatibility:
    if override not in {None, OVERRIDE_COMPATIBLE, OVERRIDE_INCOMPATIBLE}:
        raise ValueError("Invalid compatibility override")
    previous = row.manual_override
    row.manual_override = override
    row.updated_at = utcnow()
    if previous != override:
        # An override silently outranks every measurement, so who changed it is
        # kept alongside the probe evidence it overrides.
        if override == OVERRIDE_COMPATIBLE:
            reason_code = "admin_force_allow"
            action = "Pinned as compatible"
        elif override == OVERRIDE_INCOMPATIBLE:
            reason_code = "admin_force_block"
            action = "Pinned as incompatible"
        else:
            reason_code = "admin_auto"
            action = "Restored automatic detection"
        db.add(
            ModelToolCompatibilityEvent(
                compatibility=row,
                source="admin",
                success=override != OVERRIDE_INCOMPATIBLE,
                reason_code=reason_code,
                detail=f"{action} by {actor or 'an administrator'}.",
                requested_model_id=row.external_model_id[:512],
            )
        )
    await db.flush()
    return row


async def mark_probe_started(db: AsyncSession, row: ModelToolCompatibility) -> None:
    if effective_status(row) != STATUS_COMPATIBLE:
        row.status = STATUS_PROBING
    row.last_probe_at = utcnow()
    row.next_probe_at = utcnow() + datetime.timedelta(minutes=20)
    await db.flush()


async def assert_code_interpreter_model_available(
    db: AsyncSession,
    model: AIModel,
) -> None:
    """Block known-bad fixed models; unknown models remain API-compatible."""
    if not is_code_interpreter_candidate(model):
        raise HTTPException(
            status_code=409,
            detail="The selected model is not a text model and cannot use Code Interpreter.",
        )
    if is_auto_router_model_id(model.external_id):
        return
    row = await get_compatibility(
        db,
        connection_id=model.connection_id,
        external_model_id=model.external_id,
    )
    if effective_status(row) in {STATUS_DEGRADED, STATUS_INCOMPATIBLE}:
        reason = row.reason_detail if row is not None else None
        raise HTTPException(
            status_code=409,
            detail=(
                "The selected model is temporarily unavailable for Code Interpreter"
                + (f": {reason}" if reason else ".")
            ),
        )


async def openrouter_auto_plugin(
    db: AsyncSession,
    *,
    connection_id: int,
    requested_model_id: str,
) -> dict[str, Any]:
    """Build adaptive OpenRouter constraints from evidence, never vendor names."""
    rows = (
        (
            await db.execute(
                select(ModelToolCompatibility).where(
                    ModelToolCompatibility.connection_id == connection_id,
                    ModelToolCompatibility.tool == CODE_INTERPRETER_TOOL,
                    ModelToolCompatibility.external_model_id != requested_model_id,
                )
            )
        )
        .scalars()
        .all()
    )
    compatible: list[str] = []
    excluded: list[str] = []
    for row in rows:
        if is_auto_router_model_id(row.external_model_id):
            continue
        status = effective_status(row)
        if status == STATUS_COMPATIBLE:
            compatible.append(row.external_model_id)
        elif status in {STATUS_DEGRADED, STATUS_INCOMPATIBLE}:
            excluded.append(row.external_model_id)

    normalized = requested_model_id.strip().lower().lstrip("~")
    plugin_id = "auto-beta-router" if normalized in {"auto-beta", "openrouter/auto-beta"} else "auto-router"
    plugin: dict[str, Any] = {"id": plugin_id}
    # Once a verified pool exists, unknown future models cannot silently enter it.
    if compatible:
        plugin["allowed_models"] = sorted(set(compatible))
    if excluded:
        plugin["excluded_models"] = sorted(set(excluded))
    return plugin


async def prune_compatibility_events(
    db: AsyncSession,
    *,
    retention_days: int = 90,
) -> int:
    result = await db.execute(
        delete(ModelToolCompatibilityEvent).where(
            ModelToolCompatibilityEvent.created_at < utcnow() - datetime.timedelta(days=max(7, retention_days))
        )
    )
    return int(result.rowcount or 0)
