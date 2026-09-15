"""Admin REST API: connections, models, keys, plans, users, dashboard, debug."""

import asyncio
import csv
import io
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, exists, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_bearer_token,
    require_api_keys,
    require_api_keys_write,
    require_connections,
    require_connections_write,
    require_dashboard,
    require_database,
    require_models,
    require_models_write,
    require_reports,
    require_role_catalog,
    require_storage,
    require_storage_write,
    require_super_admin,
    require_users,
    require_users_write,
    require_deleted_users,
    require_deleted_users_write,
)
from app.core.security import generate_api_key, hash_password
from app.database import get_db
from app.models.api_key import AlphaRouterApiKey
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.connection import Connection
from app.models.cost_accounting import UsageEvent
from app.models.media import MediaAsset
from app.models.agent_runtime import AgentRun
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel, ModelToolCompatibilityEvent
from app.models.user import User, UserGroup, UserRoleAssignment, user_group_members
from app.services import activity_service
from app.services.model_capabilities import (
    model_catalog_meta,
    model_kinds,
    model_media_flags,
    video_generation_capabilities,
)
from app.services.model_access_service import (
    bulk_set_access_type,
    get_model_access_detail,
    list_assignment_counts,
    set_model_access,
)
from app.services.code_interpreter_probe_service import probe_model_compatibility
from app.services.model_tool_compatibility_service import (
    compatibility_map_for_models,
    compatibility_payload,
    get_compatibility,
    get_or_create_compatibility,
    is_auto_router_model_id,
    is_code_interpreter_candidate,
    set_manual_override,
)
from app.services.system_default_models import (
    DEFAULT_MODEL_KIND_KEYS,
    DEFAULT_MODEL_KINDS,
    SystemDefaultModelError,
    clear_default_model,
    clear_defaults_if_ids,
    drop_unusable_defaults,
    get_all_default_model_ids,
    get_default_model_id,
    set_default_model,
)


from app.services.model_sync import (
    disable_models_for_connection,
    enable_models_for_connection,
    set_model_admin_enabled,
    sync_connection_models,
    sync_connection_with_flash,
)
from app.services.secret_crypto import decrypt_secret, encrypt_secret, mask_secret
from app.services.log_export_service import request_logs_to_export_dataframe, resolve_log_export_maps
from app.services.activity_pdf_service import ActivityPdfError, render_activity_page_pdf
from app.services.reports_service import export_activity_logs_workbook
from app.services.scheduler import refresh_chat_retention_cleanup_schedule, refresh_storage_cleanup_schedule
from app.services.db_monitor_service import collect_database_monitor
from app.services.client_ip import resolve_client_ip
from app.services.security_audit import log_security_event
from app.services.connection_audit import (
    connection_snapshot,
    fetch_connection_changelog,
    log_connection_created,
    log_connection_deleted,
    log_connection_status,
    log_connection_updated,
    touch_connection_modified,
)
from app.services.alpha_router_api_key_audit import (
    fetch_api_key_changelog,
    log_api_key_created,
    log_api_key_deleted,
    log_api_key_status,
    log_api_key_updated,
    touch_key_modified,
)
from app.services.alpha_router_api_key_service import (
    apply_expiration,
    compute_expires_at,
    key_to_dict,
    maybe_reset_key_period,
)
from app.services.api_key_connection_policy import (
    connection_brief,
    connection_policy_label,
    map_allowed_connections,
    replace_key_allowed_connections,
)
from app.services.api_key_model_policy import (
    list_picker_models,
    map_allowed_models,
    model_policy_label,
    replace_key_allowed_models,
)
from app.services.smtp_service import SmtpNotConfiguredError, SmtpSendError, send_email
from app.services.username_norm import normalize_username, username_taken_ci
from app.services.rbac import (
    USER_SLUG,
    actor_may_assign_roles,
    is_valid_role_slug,
    list_roles,
    normalize_role_slug,
    primary_role_slug,
    user_has_super_admin_access,
)
from app.services.user_role_service import (
    count_active_full_administrators,
    count_full_administrators,
    get_roles_map,
    get_user_role_slugs,
    primary_role_for_user,
    set_user_roles,
    user_has_full_administrator,
)


from app.services.storage_service import (
    clear_all_media,
    get_storage_settings,
    purge_expired_media,
    set_storage_settings,
    storage_stats,
)
from app.services.user_media_service import (
    MediaZipLimitError,
    _media_row_dict,
    build_media_zip_file,
    count_users_over_media_quota,
    delete_all_user_media,
    delete_user_media_ids,
    get_or_create_user_media_prefs,
    get_user_media_quota_bytes,
    get_user_media_quota_gb,
    list_user_media_filtered,
    prefs_to_dict,
    set_user_media_quota_gb,
    stream_media_zip,
    user_media_quota_summary,
)
from app.services.project_media_service import (
    count_projects_over_media_quota,
    get_project_media_quota_bytes,
    get_project_media_quota_gb,
    set_project_media_quota_gb,
)


async def clear_global_default_if_ids(db: AsyncSession, model_ids) -> None:
    """Clear every system default that points at one of these catalog rows.

    Kept under the original name so all seven call sites (model delete, disable,
    make-private, connection delete…) cover every kind of default automatically.
    """
    await clear_defaults_if_ids(db, model_ids)


async def drop_unusable_global_default(db: AsyncSession) -> None:
    """Drop any system default whose model is gone or no longer eligible."""
    await drop_unusable_defaults(db)


API_KEY_PAGE_SIZES = {10, 20, 30, 50}
router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _ensure_not_last_full_admin_removal(db: AsyncSession, user_id: int, new_slugs: list[str]) -> None:
    current = await get_user_role_slugs(db, user_id)
    if (
        user_has_super_admin_access(current)
        and not user_has_super_admin_access(new_slugs)
        and await count_full_administrators(db) <= 1
    ):
        raise HTTPException(400, detail="Cannot demote the last Full Administrator account")


async def _ensure_actor_may_assign_roles(
    db: AsyncSession,
    actor: User,
    new_slugs: list[str],
    *,
    previous_slugs: list[str] | None = None,
) -> None:
    """Reject Super Admin privilege changes from non–Super-Admin actors."""
    actor_slugs = await get_user_role_slugs(db, actor.id)
    if not actor_may_assign_roles(actor_slugs, new_slugs, previous_slugs):
        raise HTTPException(
            status_code=403,
            detail="Only Super Admin can grant, change, or revoke Super Admin access",
        )


@router.get("/roles")
async def list_rbac_roles(_: User = Depends(require_role_catalog)):
    return list_roles()


class ConnectionIn(BaseModel):
    name: str
    provider_type: str
    api_key: str
    base_url: str | None = None
    sync_interval_hours: int = 6


@router.get("/dashboard/top-users")
async def top_users(period: str = "month", db: AsyncSession = Depends(get_db), _: User = Depends(require_dashboard)):
    since = _period_start(period)
    q = (
        select(RequestLog.username, func.sum(RequestLog.total_cost_usd))
        .where(RequestLog.request_time >= since)
        .group_by(RequestLog.username)
        .order_by(func.sum(RequestLog.total_cost_usd).desc())
        .limit(10)
    )
    rows = (await db.execute(q)).all()
    return {"period": period, "items": [{"username": r[0], "cost_usd": float(r[1] or 0)} for r in rows]}


@router.post("/connections")
async def create_connection(
    body: ConnectionIn,
    sync_now: bool = False,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_connections_write),
):
    """Add connection to list immediately; model sync is optional (use Sync Now in table)."""
    base_url = await _validated_connection_base_url(body.base_url)
    provider = (body.provider_type or "").strip().lower()
    if not provider:
        raise HTTPException(400, detail="Provider is required")
    conn = Connection(
        name=body.name.strip(),
        provider_type=provider,
        api_key_encrypted=encrypt_secret(body.api_key),
        base_url=base_url,
        sync_interval_hours=body.sync_interval_hours,
    )
    db.add(conn)
    await db.flush()
    await log_connection_created(db, conn=conn, actor=admin)
    await db.refresh(conn)
    synced = 0
    sync_error = None
    if sync_now:
        try:
            synced = await sync_connection_models(db, conn, body.api_key)
        except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
            sync_error = str(exc)[:300]
    await db.commit()
    return {"id": conn.id, "synced": synced, "sync_error": sync_error}


@router.get("/connections")
async def list_connections(db: AsyncSession = Depends(get_db), _: User = Depends(require_connections)):
    rows = (await db.execute(select(Connection).order_by(Connection.id.desc()))).scalars().all()
    usage_map: dict[int, float] = {}
    try:
        usage_q = (
            select(
                UsageEvent.connection_id,
                func.coalesce(func.sum(UsageEvent.final_cost_usd), 0.0),
            )
            .where(UsageEvent.connection_id.is_not(None))
            .group_by(UsageEvent.connection_id)
        )
        usage_map = {r[0]: float(r[1]) for r in (await db.execute(usage_q)).all()}
    except Exception:  # noqa: BLE001 -- falls back to a safe default value
        usage_map = {}
    return [
        {
            "id": c.id,
            "name": c.name,
            "provider_type": c.provider_type,
            "base_url": c.base_url,
            "is_active": c.is_active,
            "sync_enabled": c.sync_enabled,
            "sync_interval_hours": c.sync_interval_hours,
            "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "api_key_masked": mask_secret(c.api_key_encrypted),
            "usage_usd": usage_map.get(c.id, 0.0),
        }
        for c in rows
    ]


@router.patch("/connections/{conn_id}/toggle")
async def toggle_connection(
    conn_id: int,
    enabled: bool,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_connections_write),
):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404)
    models_disabled = 0
    models_enabled = 0
    if conn.is_active != enabled:
        conn.is_active = enabled
        touch_connection_modified(conn)
        await log_connection_status(db, conn=conn, actor=admin, enabled=enabled)
        if enabled:
            models_enabled = await enable_models_for_connection(db, conn_id)
        else:
            models_disabled = await disable_models_for_connection(db, conn_id)
    await db.commit()
    return {
        "ok": True,
        "is_active": conn.is_active,
        "models_disabled": models_disabled,
        "models_enabled": models_enabled,
    }


@router.post("/connections/{conn_id}/sync")
async def sync_models(conn_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_connections_write)):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404)
    result = await sync_connection_with_flash(db, conn, decrypt_secret(conn.api_key_encrypted))
    await db.commit()
    return result


@router.get("/models")
async def list_admin_models(
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models),
):
    conn_count = (await db.execute(select(func.count()).select_from(Connection))).scalar() or 0
    if conn_count == 0:
        # Read-only: orphan rows are cleaned when the last connection is deleted.
        return []

    stmt = select(AIModel)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(AIModel.external_id).like(like),
                func.lower(AIModel.display_name).like(like),
            )
        )
    rows = (await db.execute(stmt)).scalars().all()
    counts = await list_assignment_counts(db, [m.id for m in rows])
    compatibility = await compatibility_map_for_models(db, rows)
    system_defaults = await get_all_default_model_ids(db)
    default_id = system_defaults.get("chat")
    return [
        {
            "id": m.id,
            "external_id": m.external_id,
            "display_name": m.display_name,
            "enabled": m.is_enabled,
            "is_system_default": default_id is not None and int(m.id) == int(default_id),
            "default_kinds": [
                key for key, value in system_defaults.items() if value is not None and int(value) == int(m.id)
            ],
            "admin_disabled": bool(m.admin_disabled),
            "access_type": (m.access_type or "public").strip().lower(),
            "assignment_counts": counts.get(m.id, {"users": 0, "groups": 0}),
            "input_cost_per_1k": m.input_cost_per_1k,
            "output_cost_per_1k": m.output_cost_per_1k,
            "total_cost_per_1k": (m.input_cost_per_1k or 0) + (m.output_cost_per_1k or 0),
            "provider": m.provider_type,
            **media,
            "kinds": model_kinds(
                external_id=m.external_id,
                is_image_model=media["is_image_model"],
                is_video_model=media["is_video_model"],
                pricing_raw=m.pricing_raw,
                provider_type=m.provider_type,
            ),
            **video_generation_capabilities(
                external_id=m.external_id or "",
                is_video_model=media["is_video_model"],
                pricing_raw=m.pricing_raw if media["is_video_model"] else None,
            ),
            "code_interpreter": compatibility_payload(
                compatibility.get((int(m.connection_id), m.external_id)),
                static_candidate=is_code_interpreter_candidate(m),
                auto_router=is_auto_router_model_id(m.external_id),
            ),
            "first_seen_at": f"{m.first_seen_at.isoformat()}Z" if m.first_seen_at else None,
            **model_catalog_meta(
                external_id=m.external_id,
                display_name=m.display_name,
                pricing_raw=m.pricing_raw,
                context_length=m.context_length,
            ),
        }
        for m in rows
        for media in [
            model_media_flags(
                external_id=m.external_id or "",
                is_image_model=bool(m.is_image_model),
                is_video_model=bool(getattr(m, "is_video_model", False)),
                pricing_raw=m.pricing_raw,
                provider_type=m.provider_type,
            )
        ]
    ]


class GlobalDefaultModelIn(BaseModel):
    model_id: int


@router.get("/models/default")
async def get_models_system_default(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models),
):
    model_id = await get_default_model_id(db, "chat")
    return {"model_id": model_id}


@router.put("/models/default")
async def put_models_chat_default(
    body: GlobalDefaultModelIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models_write),
):
    """Legacy chat-only alias; ``/models/defaults/chat`` is the general form."""
    try:
        model = await set_default_model(db, "chat", body.model_id)
    except SystemDefaultModelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return {"ok": True, "model_id": int(model.id)}


class SystemDefaultModelIn(BaseModel):
    """``model_id: null`` clears the default and restores the previous fallback."""

    model_id: int | None = None


@router.get("/models/defaults")
async def get_models_system_defaults(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models),
):
    """Current default per capability, plus what the picker should offer."""
    return {
        "defaults": await get_all_default_model_ids(db),
        "kinds": [
            {
                "key": entry.key,
                "label": entry.label,
                "catalog_kind": entry.catalog_kind,
                "requirement": entry.requirement,
            }
            for entry in (DEFAULT_MODEL_KINDS[k] for k in DEFAULT_MODEL_KIND_KEYS)
        ],
    }


@router.put("/models/defaults/{kind}")
async def put_models_default_for_kind(
    kind: str,
    body: SystemDefaultModelIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models_write),
):
    try:
        if body.model_id is None:
            await clear_default_model(db, kind)
            await db.commit()
            return {"ok": True, "kind": kind, "model_id": None}
        model = await set_default_model(db, kind, body.model_id)
    except SystemDefaultModelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return {"ok": True, "kind": kind, "model_id": int(model.id)}


class ModelCompatibilityOverrideIn(BaseModel):
    override: Literal["compatible", "incompatible", "auto"]


@router.get("/models/{model_id}/code-interpreter-compatibility")
async def get_model_code_interpreter_compatibility(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models),
):
    """Compatibility state plus recent probe/runtime evidence for one model."""
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(404)
    row = await get_compatibility(
        db,
        connection_id=model.connection_id,
        external_model_id=model.external_id,
    )
    events: list[dict] = []
    if row is not None:
        event_rows = (
            (
                await db.execute(
                    select(ModelToolCompatibilityEvent)
                    .where(ModelToolCompatibilityEvent.compatibility_id == row.id)
                    .order_by(ModelToolCompatibilityEvent.created_at.desc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )
        events = [
            {
                "id": event.id,
                "source": event.source,
                "success": bool(event.success),
                "reason_code": event.reason_code,
                "detail": event.detail,
                "requested_model_id": event.requested_model_id,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in event_rows
        ]
    return {
        "model_id": model.id,
        "external_id": model.external_id,
        "compatibility": compatibility_payload(
            row,
            static_candidate=is_code_interpreter_candidate(model),
            auto_router=is_auto_router_model_id(model.external_id),
        ),
        "events": events,
    }


@router.put("/models/{model_id}/code-interpreter-compatibility")
async def put_model_code_interpreter_compatibility(
    model_id: int,
    body: ModelCompatibilityOverrideIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_models_write),
):
    """Pin or release the automatic Code Interpreter compatibility decision."""
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(404)
    row = await get_or_create_compatibility(
        db,
        connection_id=model.connection_id,
        external_model_id=model.external_id,
        model_id=model.id,
    )
    try:
        await set_manual_override(
            db,
            row,
            None if body.override == "auto" else body.override,
            actor=actor.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return {
        "ok": True,
        "compatibility": compatibility_payload(
            row,
            static_candidate=is_code_interpreter_candidate(model),
            auto_router=is_auto_router_model_id(model.external_id),
        ),
    }


@router.post("/models/{model_id}/code-interpreter-probe")
async def run_model_code_interpreter_probe(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models_write),
):
    """Run one paid capability probe on demand and return the outcome."""
    model = await db.get(AIModel, model_id)
    if not model:
        raise HTTPException(404)
    if not is_code_interpreter_candidate(model):
        raise HTTPException(400, detail="Only enabled text models can be probed")
    try:
        result = await probe_model_compatibility(db, model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = await get_compatibility(
        db,
        connection_id=model.connection_id,
        external_model_id=model.external_id,
    )
    return {
        "ok": result.success,
        "reason_code": result.reason_code,
        "detail": result.detail,
        "selected_model_id": result.selected_model_id,
        "compatibility": compatibility_payload(
            row,
            static_candidate=True,
            auto_router=is_auto_router_model_id(model.external_id),
        ),
    }


@router.patch("/models/{model_id}/toggle")
async def toggle_model(
    model_id: int, enabled: bool, db: AsyncSession = Depends(get_db), _: User = Depends(require_models_write)
):
    m = await db.get(AIModel, model_id)
    if not m:
        raise HTTPException(404)
    await set_model_admin_enabled(db, m, enabled)
    if not enabled:
        await clear_global_default_if_ids(db, [model_id])
    await drop_unusable_global_default(db)
    await db.commit()
    return {"ok": True}


@router.get("/models/{model_id}/access")
async def get_model_access(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models),
):
    detail = await get_model_access_detail(db, model_id)
    if not detail:
        raise HTTPException(404)
    return detail


class ModelAccessIn(BaseModel):
    access_type: str
    user_ids: list[int] = []
    group_ids: list[int] = []


@router.put("/models/{model_id}/access")
async def put_model_access(
    model_id: int,
    body: ModelAccessIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models_write),
):
    m = await db.get(AIModel, model_id)
    if not m:
        raise HTTPException(404)
    try:
        await set_model_access(
            db,
            m,
            access_type=body.access_type,
            user_ids=body.user_ids,
            group_ids=body.group_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.access_type.strip().lower() == "private":
        await clear_global_default_if_ids(db, [model_id])
    await drop_unusable_global_default(db)
    await db.commit()
    detail = await get_model_access_detail(db, model_id)
    return {"ok": True, **(detail or {})}


class BulkModelsIn(BaseModel):
    ids: list[int]


@router.post("/models/bulk")
async def bulk_models(
    body: BulkModelsIn,
    action: str = Query(..., pattern="^(on|off|delete|public|private)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models_write),
):
    if not body.ids:
        raise HTTPException(status_code=400, detail="No models selected")
    ids = list(dict.fromkeys(body.ids))
    if action == "delete":
        await clear_global_default_if_ids(db, ids)
        result = await db.execute(delete(AIModel).where(AIModel.id.in_(ids)))
        await db.commit()
        return {"ok": True, "count": result.rowcount or 0}
    if action in ("public", "private"):
        count = await bulk_set_access_type(db, ids, action)
        if action == "private":
            await clear_global_default_if_ids(db, ids)
        await drop_unusable_global_default(db)
        await db.commit()
        return {"ok": True, "count": count}
    enabled = action == "on"
    rows = (await db.execute(select(AIModel).where(AIModel.id.in_(ids)))).scalars().all()
    for m in rows:
        await set_model_admin_enabled(db, m, enabled)
    if not enabled:
        await clear_global_default_if_ids(db, ids)
    await drop_unusable_global_default(db)
    await db.commit()
    return {"ok": True, "count": len(rows)}


class ApiKeyCreate(BaseModel):
    name: str
    owner_user_id: int
    credit_limit_usd: float = 0
    # Must be true when credit_limit_usd is 0: no silent blank cheques.
    unlimited_budget: bool = False
    reset_period: Literal["daily", "weekly", "monthly"] = "monthly"
    expiration_days: int | None = None
    restrict_connections: bool = False
    allowed_connection_ids: list[int] = []
    restrict_models: bool = False
    allowed_model_ids: list[int] = []


class ApiKeyPatch(BaseModel):
    name: str | None = None
    owner_user_id: int | None = None
    credit_limit_usd: float | None = None
    unlimited_budget: bool | None = None
    reset_period: Literal["daily", "weekly", "monthly"] | None = None
    expiration_days: int | None = None
    expiration_never: bool | None = None
    restrict_connections: bool | None = None
    allowed_connection_ids: list[int] | None = None
    restrict_models: bool | None = None
    allowed_model_ids: list[int] | None = None


@router.post("/api-keys")
async def create_alpha_router_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_api_keys_write),
):
    owner = await db.get(User, body.owner_user_id)
    if not owner:
        raise HTTPException(400, detail="Owner user not found")
    if body.credit_limit_usd < 0:
        raise HTTPException(400, detail="Credit limit must be >= 0")
    if body.credit_limit_usd <= 0 and not body.unlimited_budget:
        raise HTTPException(400, detail="Set a credit limit greater than 0, or explicitly mark the key as unlimited")
    raw, prefix, key_hash = generate_api_key()
    now = datetime.utcnow()
    expires_at = compute_expires_at(now, body.expiration_days)
    row = AlphaRouterApiKey(
        name=body.name.strip(),
        key_prefix=prefix,
        key_hash=key_hash,
        owner_user_id=body.owner_user_id,
        credit_limit_usd=float(body.credit_limit_usd),
        unlimited_budget=bool(body.unlimited_budget),
        reset_period=body.reset_period,
        expires_at=expires_at,
        period_started_at=now,
        period_used_usd=0.0,
        total_used_usd=0.0,
    )
    db.add(row)
    await db.flush()
    restrict = bool(body.restrict_connections)
    try:
        names = await replace_key_allowed_connections(
            db,
            row,
            restrict=restrict,
            connection_ids=body.allowed_connection_ids if restrict else [],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    restrict_models = bool(body.restrict_models)
    try:
        model_labels = await replace_key_allowed_models(
            db,
            row,
            restrict=restrict_models,
            model_ids=body.allowed_model_ids if restrict_models else [],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await log_api_key_created(
        db,
        key=row,
        actor=admin,
        owner=owner,
        allowed_connections_label=connection_policy_label(restrict, names),
        allowed_models_label=model_policy_label(restrict_models, model_labels),
    )
    await db.commit()
    await db.refresh(row)
    conn_payload = (await map_allowed_connections(db, [row.id])).get(int(row.id), [])
    model_payload = (await map_allowed_models(db, [row.id])).get(int(row.id), [])
    owner_info = {
        "email": owner.email,
        "username": owner.username,
        "display_name": owner.display_name,
    }
    return {
        "name": row.name,
        "api_key": raw,
        "url": f"{__import__('app.config', fromlist=['get_settings']).get_settings().api_public_url}/v1",
        "key": key_to_dict(
            row,
            owner_info,
            allowed_connections=conn_payload,
            allowed_models=model_payload,
        ),
        "owner_user_id": owner.id,
        "owner_email": owner.email,
    }


class ApiKeyEmailCredentialsIn(BaseModel):
    owner_user_id: int
    name: str
    api_key: str
    url: str
    copy_to_admin: bool = False


@router.post("/api-keys/email-credentials")
async def email_api_key_credentials(
    body: ApiKeyEmailCredentialsIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_api_keys_write),
):
    owner = await db.get(User, body.owner_user_id)
    if not owner or not (owner.email or "").strip():
        raise HTTPException(400, detail="Owner user or email not found")
    cc: list[str] | None = None
    if body.copy_to_admin:
        admin_email = (admin.email or "").strip()
        if not admin_email:
            raise HTTPException(400, detail="Your account has no email address for a copy")
        cc = [admin_email]
    name = body.name.strip() or "API key"
    subject = f"Your gateway API key: {name}"
    text = (
        f"Hello,\n\n"
        f"A new gateway API key has been created for you.\n\n"
        f"Name: {name}\n"
        f"API key: {body.api_key}\n"
        f"Base URL (OpenAI-compatible): {body.url}\n\n"
        f"Store this key securely. You will not be able to view it again in the admin panel.\n"
    )
    try:
        await send_email(db, to_address=owner.email, subject=subject, body_text=text, cc=cc)
    except SmtpNotConfiguredError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except SmtpSendError as exc:
        raise HTTPException(502, detail=f"Failed to send email: {exc}") from exc
    return {
        "ok": True,
        "to": owner.email,
        "cc": cc[0] if cc else None,
    }


class LocalUserIn(BaseModel):
    username: str
    email: str
    password: str
    display_name: str | None = None
    role: str = "user"
    company: str | None = None
    department: str | None = None
    office: str | None = None
    job_title: str | None = None
    reporting_to: str | None = None
    group_id: int | None = None
    plan_id: int | None = None
    no_plan: bool = False
    inherit_group_plan: bool = False


def _normalize_role(role: str) -> str:
    slug = normalize_role_slug(role)
    if not is_valid_role_slug(slug):
        raise HTTPException(400, detail="Invalid role")
    return slug


@router.post("/users")
async def create_local_user(
    body: LocalUserIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_users_write),
):
    raw_username = (body.username or "").strip()
    username = normalize_username(raw_username)
    if not username:
        raise HTTPException(400, "Username is required")
    if await username_taken_ci(db, username):
        raise HTTPException(400, "Username already exists")
    plan_selected = sum([body.no_plan, body.inherit_group_plan, body.plan_id is not None])
    if plan_selected > 1:
        raise HTTPException(400, detail="Specify only one of plan_id, no_plan, or inherit_group_plan")
    from app.services.password_policy import PasswordPolicyError, validate_password

    try:
        password = validate_password(body.password)
    except PasswordPolicyError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    new_slugs = [_normalize_role(body.role)]
    await _ensure_actor_may_assign_roles(db, actor, new_slugs)
    display_name = (body.display_name or "").strip() or raw_username
    user = User(
        username=username,
        email=body.email,
        display_name=display_name,
        hashed_password=hash_password(password),
        auth_provider="local",
        company=_clean_optional_str(body.company),
        department=_clean_optional_str(body.department),
        office=_clean_optional_str(body.office),
        job_title=_clean_optional_str(body.job_title),
        reporting_to=_clean_optional_str(body.reporting_to),
    )
    db.add(user)
    await db.flush()
    await set_user_roles(db, user, new_slugs)
    if body.group_id is not None:
        group = await db.get(UserGroup, body.group_id)
        if not group:
            raise HTTPException(404, detail="Group not found")
        if group.source != "local":
            raise HTTPException(400, detail="Only local groups can be assigned when creating a local user")
        await db.execute(insert(user_group_members).values(user_id=user.id, group_id=body.group_id))
    if body.inherit_group_plan:
        from app.services.plan_assignment_service import clear_user_plan_override

        await clear_user_plan_override(db, user.id)
    elif body.no_plan:
        from app.services.plan_assignment_service import upsert_user_no_plan

        await upsert_user_no_plan(db, user.id)
    elif body.plan_id is not None:
        from app.services.plan_assignment_service import upsert_user_plan

        await upsert_user_plan(db, user.id, body.plan_id)
    from app.services.budget_service import resolve_monthly_budget

    user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await db.commit()
    return {"id": user.id}


def _apply_user_list_filters(
    stmt,
    *,
    q: str | None,
    username: str | None,
    email: str | None,
    department: str | None,
    job_title: str | None,
    role: str | None,
    is_active: bool | None,
    group_id: int | None,
    plan_id: int | None = None,
    no_plan: bool = False,
    deleted_only: bool = False,
    active_only: bool = True,
):
    if deleted_only:
        stmt = stmt.where(User.deleted_at.is_not(None))
    elif active_only:
        stmt = stmt.where(User.deleted_at.is_(None))
    if username:
        like = f"%{username.strip()}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.display_name.ilike(like)))
    if email:
        stmt = stmt.where(User.email.ilike(f"%{email.strip()}%"))
    if department:
        stmt = stmt.where(User.department.ilike(f"%{department.strip()}%"))
    if job_title:
        stmt = stmt.where(User.job_title.ilike(f"%{job_title.strip()}%"))
    if role:
        slug = normalize_role_slug(role.strip())
        has_assignment = exists(
            select(UserRoleAssignment.user_id).where(
                UserRoleAssignment.user_id == User.id,
                UserRoleAssignment.role_slug == slug,
            )
        )
        if slug == USER_SLUG:
            # Default end users may have no assignment rows yet.
            has_any_assignment = exists(select(UserRoleAssignment.user_id).where(UserRoleAssignment.user_id == User.id))
            stmt = stmt.where(or_(~has_any_assignment, has_assignment))
        else:
            stmt = stmt.where(has_assignment)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if group_id is not None:
        stmt = stmt.where(
            exists(
                select(user_group_members.c.user_id).where(
                    user_group_members.c.user_id == User.id,
                    user_group_members.c.group_id == group_id,
                )
            )
        )
    has_user_plan_row = exists(select(PlanAssignment.id).where(PlanAssignment.user_id == User.id))
    if plan_id is not None:
        direct_assigned = exists(
            select(PlanAssignment.id).where(
                PlanAssignment.user_id == User.id,
                PlanAssignment.plan_id == plan_id,
            )
        )
        inherit_via_group = exists(
            select(user_group_members.c.user_id).where(
                user_group_members.c.user_id == User.id,
                exists(
                    select(PlanAssignment.id).where(
                        PlanAssignment.group_id == user_group_members.c.group_id,
                        PlanAssignment.plan_id == plan_id,
                    )
                ),
            )
        )
        inherit_via_department = exists(
            select(PlanAssignment.id).where(
                PlanAssignment.department.isnot(None),
                PlanAssignment.department == User.department,
                PlanAssignment.plan_id == plan_id,
            )
        )
        stmt = stmt.where(
            or_(
                direct_assigned,
                and_(~has_user_plan_row, or_(inherit_via_group, inherit_via_department)),
            )
        )
    elif no_plan:
        explicit_none = exists(
            select(PlanAssignment.id).where(
                PlanAssignment.user_id == User.id,
                PlanAssignment.plan_id.is_(None),
            )
        )
        inherit_via_group_any = exists(
            select(user_group_members.c.user_id).where(
                user_group_members.c.user_id == User.id,
                exists(
                    select(PlanAssignment.id).where(
                        PlanAssignment.group_id == user_group_members.c.group_id,
                        PlanAssignment.plan_id.isnot(None),
                    )
                ),
            )
        )
        inherit_via_department_any = exists(
            select(PlanAssignment.id).where(
                PlanAssignment.department.isnot(None),
                PlanAssignment.department == User.department,
                PlanAssignment.plan_id.isnot(None),
            )
        )
        stmt = stmt.where(
            or_(
                explicit_none,
                and_(~has_user_plan_row, ~inherit_via_group_any, ~inherit_via_department_any),
            )
        )
    if q and not any((username, email, department, job_title)):
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(like),
                User.email.ilike(like),
                User.display_name.ilike(like),
                User.department.ilike(like),
                User.job_title.ilike(like),
            )
        )
    return stmt


async def _query_owner_picker_users(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    q: str | None = None,
) -> list[User]:
    if user_id is not None:
        u = await db.get(User, user_id)
        return [u] if u else []
    term = (q or "").strip()
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.username).limit(25)
    if len(term) >= 2:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(like),
                User.email.ilike(like),
                User.display_name.ilike(like),
                User.department.ilike(like),
            )
        )
    return list((await db.execute(stmt)).scalars().all())


def _owner_picker_payload(users: list[User]) -> list[dict]:
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "display_name": u.display_name,
        }
        for u in users
    ]


def _effective_plan_id(user_id: int, plan_state: dict[int, dict], inherited_plans: dict[int, dict]) -> int | None:
    state = plan_state.get(user_id) or {}
    mode = state.get("user_plan_mode") or "inherit"
    if mode == "assigned":
        plan_id = state.get("user_plan_id")
        return int(plan_id) if plan_id is not None else None
    if mode == "none":
        return None
    inherited = inherited_plans.get(user_id) or {}
    plan_id = inherited.get("inherited_plan_id")
    return int(plan_id) if plan_id is not None else None


def _filter_users_by_effective_plan(
    users: list[User],
    *,
    plan_state: dict[int, dict],
    inherited_plans: dict[int, dict],
    plan_id: int | None,
    no_plan: bool,
) -> list[User]:
    if plan_id is None and not no_plan:
        return users
    matched: list[User] = []
    for user in users:
        effective_id = _effective_plan_id(user.id, plan_state, inherited_plans)
        if no_plan:
            if effective_id is None:
                matched.append(user)
        elif effective_id == plan_id:
            matched.append(user)
    return matched


def _admin_user_export_plan_name(row: dict) -> str:
    mode = row.get("user_plan_mode")
    if mode == "assigned" and row.get("user_plan_name"):
        return str(row["user_plan_name"])
    if mode == "inherit" and row.get("inherited_plan_name"):
        return str(row["inherited_plan_name"])
    return "No Plan"


def _admin_user_export_plan_source(row: dict) -> str:
    mode = row.get("user_plan_mode")
    if mode == "assigned":
        return "assigned"
    if mode == "none":
        return "none"
    source = row.get("inherited_plan_source")
    if source in ("group", "department"):
        return str(source)
    return "none"


def _admin_users_to_csv_bytes(rows: list[dict]) -> bytes:
    columns = [
        "Username",
        "Display Name",
        "Email",
        "Groups",
        "Department",
        "Office",
        "Job Title",
        "Company",
        "Report To",
        "Auth",
        "Roles",
        "User Plan",
        "Plan Source",
        "Budget Used USD",
        "Monthly Budget USD",
        "Status",
        "Last Login At",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        roles = row.get("roles") or []
        writer.writerow(
            {
                "Username": row.get("username") or "",
                "Display Name": row.get("display_name") or "",
                "Email": row.get("email") or "",
                "Groups": ", ".join(row.get("group_names") or []),
                "Department": row.get("department") or "",
                "Office": row.get("office") or "",
                "Job Title": row.get("job_title") or "",
                "Company": row.get("company") or "",
                "Report To": row.get("reporting_to") or "",
                "Auth": row.get("auth_provider") or "",
                "Roles": ", ".join(str(role) for role in roles),
                "User Plan": _admin_user_export_plan_name(row),
                "Plan Source": _admin_user_export_plan_source(row),
                "Budget Used USD": "" if row.get("budget_used_usd") is None else row.get("budget_used_usd"),
                "Monthly Budget USD": "" if row.get("monthly_budget_usd") is None else row.get("monthly_budget_usd"),
                "Status": "Active" if row.get("is_active") else "Deactive",
                "Last Login At": row.get("last_login_at") or "",
            }
        )
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


async def _list_admin_user_dicts(
    db: AsyncSession,
    *,
    q: str | None,
    username: str | None,
    email: str | None,
    department: str | None,
    job_title: str | None,
    role: str | None,
    is_active: bool | None,
    group_id: int | None,
    user_id: int | None,
    online: bool | None,
    picker: bool,
    plan_id: int | None,
    no_plan: bool,
) -> list[dict]:
    from app.services.presence_service import online_user_ids

    if picker and user_id is not None:
        users = await _query_owner_picker_users(db, user_id=user_id)
    elif picker:
        users = await _query_owner_picker_users(db, q=q)
    else:
        stmt = select(User).order_by(User.username)
        stmt = _apply_user_list_filters(
            stmt,
            q=q,
            username=username,
            email=email,
            department=department,
            job_title=job_title,
            role=role,
            is_active=is_active,
            group_id=group_id,
            plan_id=None if picker else plan_id,
            no_plan=False if picker else no_plan,
            active_only=True,
        )
        users = list((await db.execute(stmt)).scalars().all())
    # One Redis MGET. Narrow the list here so the plan/group/budget batches below
    # only run for rows that survive the filter. ``None`` means presence is
    # unavailable, in which case the filter is ignored rather than returning an
    # empty table that looks like a bug.
    online_ids = None if picker else await online_user_ids([u.id for u in users])
    if online and online_ids is not None:
        users = [u for u in users if u.id in online_ids and bool(u.is_active)]
    user_ids = [u.id for u in users]
    plan_state = await _build_user_plan_state_map(db, user_ids)
    from app.services.budget_service import resolve_inherited_plans_batch, resolve_monthly_budgets_batch

    inherited_plans = await resolve_inherited_plans_batch(db, users)
    if not picker and (plan_id is not None or no_plan):
        users = _filter_users_by_effective_plan(
            users,
            plan_state=plan_state,
            inherited_plans=inherited_plans,
            plan_id=plan_id,
            no_plan=no_plan,
        )
        user_ids = [u.id for u in users]
    groups_map: dict[int, list[str]] = {uid: [] for uid in user_ids}
    if user_ids:
        group_rows = (
            await db.execute(
                select(user_group_members.c.user_id, UserGroup.name)
                .join(UserGroup, UserGroup.id == user_group_members.c.group_id)
                .where(user_group_members.c.user_id.in_(user_ids))
                .order_by(UserGroup.name)
            )
        ).all()
        for uid, gname in group_rows:
            if uid is not None:
                groups_map.setdefault(int(uid), []).append(str(gname))
    roles_map = await get_roles_map(db, user_ids)
    budgets = await resolve_monthly_budgets_batch(db, users)
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "display_name": u.display_name,
            "auth_provider": u.auth_provider,
            "role": primary_role_slug(roles_map.get(u.id, ["user"])),
            "roles": roles_map.get(u.id, ["user"]),
            "is_active": bool(u.is_active),
            "group_names": groups_map.get(u.id, []),
            "company": u.company,
            "department": u.department,
            "job_title": u.job_title,
            "office": u.office,
            "reporting_to": u.reporting_to,
            "monthly_budget_usd": budgets.get(u.id, 0.0),
            "budget_used_usd": u.budget_used_usd,
            "budget_reserved_usd": u.budget_reserved_usd,
            "totp_enabled": bool(u.totp_enabled) and (u.auth_provider or "local") == "local",
            **{
                **plan_state.get(
                    u.id,
                    {"user_plan_mode": "inherit", "user_plan_id": None, "user_plan_name": None},
                ),
                **(
                    inherited_plans.get(u.id, {})
                    if plan_state.get(u.id, {}).get("user_plan_mode") == "inherit"
                    else {
                        "inherited_plan_id": None,
                        "inherited_plan_name": None,
                        "inherited_plan_source": None,
                    }
                ),
            },
            "deleted_at": u.deleted_at.isoformat() if u.deleted_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "online": (None if online_ids is None else (u.id in online_ids and bool(u.is_active))),
        }
        for u in users
    ]


@router.get("/users")
async def list_users(
    q: str | None = Query(None),
    username: str | None = Query(None),
    email: str | None = Query(None),
    department: str | None = Query(None),
    job_title: str | None = Query(None),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    group_id: int | None = Query(None),
    plan_id: int | None = Query(None, description="Effective budget plan (direct or inherited)"),
    no_plan: bool = Query(False, description="Users with no effective budget plan"),
    user_id: int | None = Query(None),
    online: bool | None = Query(None, description="Keep only users online right now"),
    picker: bool = Query(False, description="Owner picker: search-only, no full list"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users),
):
    if plan_id is not None and no_plan:
        raise HTTPException(400, detail="Specify only one of plan_id or no_plan")
    return await _list_admin_user_dicts(
        db,
        q=q,
        username=username,
        email=email,
        department=department,
        job_title=job_title,
        role=role,
        is_active=is_active,
        group_id=group_id,
        user_id=user_id,
        online=online,
        picker=picker,
        plan_id=plan_id,
        no_plan=no_plan,
    )


@router.get("/users/export")
async def export_users(
    q: str | None = Query(None),
    username: str | None = Query(None),
    email: str | None = Query(None),
    department: str | None = Query(None),
    job_title: str | None = Query(None),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    group_id: int | None = Query(None),
    plan_id: int | None = Query(None, description="Effective budget plan (direct or inherited)"),
    no_plan: bool = Query(False, description="Users with no effective budget plan"),
    online: bool | None = Query(None, description="Keep only users online right now"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users),
):
    if plan_id is not None and no_plan:
        raise HTTPException(400, detail="Specify only one of plan_id or no_plan")
    rows = await _list_admin_user_dicts(
        db,
        q=q,
        username=username,
        email=email,
        department=department,
        job_title=job_title,
        role=role,
        is_active=is_active,
        group_id=group_id,
        user_id=None,
        online=online,
        picker=False,
        plan_id=plan_id,
        no_plan=no_plan,
    )
    content = _admin_users_to_csv_bytes(rows)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"alpharouter-users-{stamp}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/deleted-users")
async def list_deleted_users(
    q: str | None = Query(None),
    username: str | None = Query(None),
    email: str | None = Query(None),
    department: str | None = Query(None),
    job_title: str | None = Query(None),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_deleted_users),
):
    stmt = select(User).order_by(User.deleted_at.desc(), User.username)
    stmt = _apply_user_list_filters(
        stmt,
        q=q,
        username=username,
        email=email,
        department=department,
        job_title=job_title,
        role=role,
        is_active=is_active,
        group_id=None,
        deleted_only=True,
        active_only=False,
    )
    users = (await db.execute(stmt)).scalars().all()
    user_ids = [u.id for u in users]
    plan_map: dict[int, tuple[int | None, str | None]] = {}
    if user_ids:
        plan_rows = (
            await db.execute(
                select(PlanAssignment.user_id, PlanAssignment.plan_id, BudgetPlan.name)
                .join(BudgetPlan, BudgetPlan.id == PlanAssignment.plan_id)
                .where(PlanAssignment.user_id.in_(user_ids), PlanAssignment.user_id.is_not(None))
            )
        ).all()
        for uid, pid, pname in plan_rows:
            if uid is not None:
                plan_map[int(uid)] = (int(pid), str(pname))
    roles_map = await get_roles_map(db, user_ids)
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "display_name": u.display_name,
            "auth_provider": u.auth_provider,
            "role": primary_role_slug(roles_map.get(u.id, ["user"])),
            "roles": roles_map.get(u.id, ["user"]),
            "is_active": bool(u.is_active),
            "company": u.company,
            "department": u.department,
            "job_title": u.job_title,
            "office": u.office,
            "reporting_to": u.reporting_to,
            "deleted_at": u.deleted_at.isoformat() if u.deleted_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "user_plan_id": plan_map.get(u.id, (None, None))[0],
            "user_plan_name": plan_map.get(u.id, (None, None))[1],
        }
        for u in users
    ]


class ConnectionPatch(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    sync_interval_hours: int | None = None
    is_active: bool | None = None


@router.patch("/connections/{conn_id}")
async def update_connection(
    conn_id: int,
    body: ConnectionPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_connections_write),
):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404)
    before = connection_snapshot(conn)
    patches: dict[str, object] = {}
    if body.name is not None:
        conn.name = body.name.strip()
        patches["name"] = conn.name
    if body.provider_type is not None:
        provider = body.provider_type.strip().lower()
        if not provider:
            raise HTTPException(400, detail="Provider is required")
        conn.provider_type = provider
        patches["provider_type"] = conn.provider_type
    if body.api_key:
        conn.api_key_encrypted = encrypt_secret(body.api_key)
    if body.base_url is not None:
        conn.base_url = await _validated_connection_base_url(body.base_url)
        patches["base_url"] = conn.base_url or ""
    if body.sync_interval_hours is not None:
        conn.sync_interval_hours = body.sync_interval_hours
        patches["sync_interval_hours"] = conn.sync_interval_hours
    if body.is_active is not None and conn.is_active != body.is_active:
        conn.is_active = body.is_active
        patches["is_active"] = conn.is_active
        if conn.is_active:
            await enable_models_for_connection(db, conn_id)
        else:
            await disable_models_for_connection(db, conn_id)
            disabled_ids = (
                (await db.execute(select(AIModel.id).where(AIModel.connection_id == conn_id))).scalars().all()
            )
            await clear_global_default_if_ids(db, list(disabled_ids))
    if patches:
        touch_connection_modified(conn)
        await log_connection_updated(db, conn=conn, actor=admin, before=before, after_patches=patches)
    await db.commit()
    return {"ok": True}


@router.delete("/connections/{conn_id}")
async def delete_connection(
    conn_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_connections_write),
):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404)
    # Explicit cleanup for DBs/environments where FK cascade may be disabled.
    catalog_ids = (await db.execute(select(AIModel.id).where(AIModel.connection_id == conn_id))).scalars().all()
    await log_connection_deleted(db, conn=conn, actor=admin, actor_ip=_client_ip(request), model_count=len(catalog_ids))
    await clear_global_default_if_ids(db, list(catalog_ids))
    await db.execute(delete(AIModel).where(AIModel.connection_id == conn_id))
    await db.delete(conn)
    remaining = (await db.execute(select(func.count()).select_from(Connection))).scalar() or 0
    if remaining == 0:
        await db.execute(delete(AIModel))
    await db.commit()
    return {"ok": True}


@router.get("/api-keys/owner-users")
async def list_api_key_owner_users(
    q: str | None = Query(None),
    user_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_keys),
):
    """Minimal user list for the API Key owner picker (api_keys menu access only)."""
    users = await _query_owner_picker_users(db, user_id=user_id, q=q)
    return _owner_picker_payload(users)


@router.get("/api-keys/connection-options")
async def list_api_key_connection_options(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_keys),
):
    """Connection picker for API key allowlists (api_keys menu access only)."""
    rows = (await db.execute(select(Connection).order_by(Connection.name.asc(), Connection.id.asc()))).scalars().all()
    return {"items": [connection_brief(c) for c in rows]}


@router.get("/api-keys/model-options")
async def list_api_key_model_options(
    owner_user_id: int = Query(..., ge=1),
    connection_id: list[int] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_keys),
):
    """Model picker for API key allowlists (filtered by owner ACL)."""
    owner = await db.get(User, owner_user_id)
    if not owner:
        raise HTTPException(400, detail="Owner user not found")
    items = await list_picker_models(
        db,
        owner_user_id=owner_user_id,
        connection_ids=connection_id,
    )
    return {"items": items}


@router.get("/api-keys")
async def list_alpha_router_keys(
    q: str | None = Query(None, description="Search key name"),
    owner: str | None = Query(None, description="Search owner email, username, or display name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_keys),
):
    if page_size not in API_KEY_PAGE_SIZES:
        raise HTTPException(400, detail=f"page_size must be one of {sorted(API_KEY_PAGE_SIZES)}")

    stmt = select(AlphaRouterApiKey)
    if q:
        stmt = stmt.where(AlphaRouterApiKey.name.ilike(f"%{q.strip()}%"))
    if owner:
        needle = f"%{owner.strip()}%"
        stmt = stmt.join(User, AlphaRouterApiKey.owner_user_id == User.id).where(
            or_(
                User.email.ilike(needle),
                User.username.ilike(needle),
                User.display_name.ilike(needle),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await db.execute(count_stmt)).scalar() or 0)
    total_pages = max(1, (total + page_size - 1) // page_size) if total else 1
    page = min(page, total_pages)

    rows = (
        (
            await db.execute(
                stmt.order_by(AlphaRouterApiKey.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    owner_ids = {k.owner_user_id for k in rows if k.owner_user_id}
    owners: dict[int, User] = {}
    if owner_ids:
        owner_rows = (await db.execute(select(User).where(User.id.in_(owner_ids)))).scalars().all()
        owners = {u.id: u for u in owner_rows}

    conn_map = await map_allowed_connections(db, [k.id for k in rows])
    model_map = await map_allowed_models(db, [k.id for k in rows])

    items = []
    for k in rows:
        u = owners.get(k.owner_user_id) if k.owner_user_id else None
        owner_info = {"email": u.email, "username": u.username, "display_name": u.display_name} if u else None
        apply_expiration(k)
        await maybe_reset_key_period(db, k)
        items.append(
            key_to_dict(
                k,
                owner_info,
                allowed_connections=conn_map.get(int(k.id), []),
                allowed_models=model_map.get(int(k.id), []),
            )
        )
    await db.commit()
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.patch("/api-keys/{key_id}/toggle")
async def toggle_alpha_router_key(
    key_id: int,
    enabled: bool,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_api_keys_write),
):
    k = await db.get(AlphaRouterApiKey, key_id)
    if not k:
        raise HTTPException(404)
    if k.is_active != enabled:
        k.is_active = enabled
        touch_key_modified(k)
        await log_api_key_status(db, key=k, actor=admin, enabled=enabled)
    await db.commit()
    return {"ok": True}


@router.patch("/api-keys/{key_id}")
async def patch_alpha_router_key(
    key_id: int,
    body: ApiKeyPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_api_keys_write),
):
    k = await db.get(AlphaRouterApiKey, key_id)
    if not k:
        raise HTTPException(404)

    before_conns = (await map_allowed_connections(db, [k.id])).get(int(k.id), [])
    before_models = (await map_allowed_models(db, [k.id])).get(int(k.id), [])
    before = {
        "name": k.name,
        "owner_user_id": k.owner_user_id,
        "credit_limit_usd": k.credit_limit_usd,
        "reset_period": k.reset_period,
        "expires_at": k.expires_at,
        "allowed_connections": connection_policy_label(
            bool(k.restrict_connections),
            [c["name"] for c in before_conns],
        ),
        "allowed_models": model_policy_label(
            bool(k.restrict_models),
            [
                f"{m['display_name']} ({m['connection_name']})"
                if m.get("connection_name")
                else str(m.get("display_name") or m.get("external_id") or m["id"])
                for m in before_models
            ],
        ),
    }
    patches: dict[str, object] = {}

    if body.name is not None:
        k.name = body.name.strip()
        patches["name"] = k.name
    if body.owner_user_id is not None:
        owner = await db.get(User, body.owner_user_id)
        if not owner:
            raise HTTPException(400, detail="Owner user not found")
        k.owner_user_id = body.owner_user_id
        patches["owner_user_id"] = body.owner_user_id
    if body.credit_limit_usd is not None:
        if body.credit_limit_usd < 0:
            raise HTTPException(400, detail="Credit limit must be >= 0")
        k.credit_limit_usd = float(body.credit_limit_usd)
        patches["credit_limit_usd"] = k.credit_limit_usd
    if body.unlimited_budget is not None:
        k.unlimited_budget = bool(body.unlimited_budget)
        patches["unlimited_budget"] = k.unlimited_budget
    if float(k.credit_limit_usd or 0) <= 0 and not bool(k.unlimited_budget):
        raise HTTPException(400, detail="Set a credit limit greater than 0, or explicitly mark the key as unlimited")
    if body.reset_period is not None:
        k.reset_period = body.reset_period
        patches["reset_period"] = k.reset_period
    if body.expiration_never:
        k.expires_at = None
        patches["expires_at"] = None
    elif body.expiration_days is not None:
        if body.expiration_days <= 0:
            k.expires_at = None
            patches["expires_at"] = None
        else:
            k.expires_at = compute_expires_at(k.created_at or datetime.utcnow(), body.expiration_days)
            patches["expires_at"] = k.expires_at

    if body.restrict_connections is not None or body.allowed_connection_ids is not None:
        restrict = (
            bool(body.restrict_connections) if body.restrict_connections is not None else bool(k.restrict_connections)
        )
        ids = (
            body.allowed_connection_ids
            if body.allowed_connection_ids is not None
            else [int(c["id"]) for c in before_conns]
        )
        try:
            names = await replace_key_allowed_connections(
                db,
                k,
                restrict=restrict,
                connection_ids=ids if restrict else [],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        patches["allowed_connections"] = connection_policy_label(restrict, names)

    if body.restrict_models is not None or body.allowed_model_ids is not None:
        restrict_models = bool(body.restrict_models) if body.restrict_models is not None else bool(k.restrict_models)
        model_ids = (
            body.allowed_model_ids if body.allowed_model_ids is not None else [int(m["id"]) for m in before_models]
        )
        try:
            model_labels = await replace_key_allowed_models(
                db,
                k,
                restrict=restrict_models,
                model_ids=model_ids if restrict_models else [],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        patches["allowed_models"] = model_policy_label(restrict_models, model_labels)

    if patches:
        touch_key_modified(k)
        await log_api_key_updated(db, key=k, actor=admin, before=before, after_patches=patches)
    await db.commit()
    return {"ok": True}


@router.delete("/api-keys/{key_id}")
async def delete_alpha_router_key(
    key_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_api_keys_write),
):
    k = await db.get(AlphaRouterApiKey, key_id)
    if not k:
        raise HTTPException(404)
    await log_api_key_deleted(db, key=k, actor=admin, actor_ip=_client_ip(request))
    await db.delete(k)
    await db.commit()
    return {"ok": True}


@router.post("/api-keys/bulk")
async def bulk_alpha_router_keys(
    body: BulkModelsIn,
    action: str = Query(..., pattern="^(on|off|delete)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_api_keys_write),
):
    if not body.ids:
        raise HTTPException(status_code=400, detail="No API keys selected")
    ids = list(dict.fromkeys(body.ids))
    if action == "delete":
        result = await db.execute(delete(AlphaRouterApiKey).where(AlphaRouterApiKey.id.in_(ids)))
        await db.commit()
        return {"ok": True, "count": result.rowcount or 0}
    enabled = action == "on"
    rows = (await db.execute(select(AlphaRouterApiKey).where(AlphaRouterApiKey.id.in_(ids)))).scalars().all()
    changed = 0
    for k in rows:
        if k.is_active == enabled:
            continue
        k.is_active = enabled
        touch_key_modified(k)
        await log_api_key_status(db, key=k, actor=admin, enabled=enabled)
        changed += 1
    await db.commit()
    return {"ok": True, "count": changed}


def _clean_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s if s else None


async def _build_user_plan_state_map(db: AsyncSession, user_ids: list[int]) -> dict[int, dict]:
    from app.services.plan_assignment_service import USER_PLAN_ASSIGNED, USER_PLAN_INHERIT, USER_PLAN_NONE

    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(PlanAssignment.user_id, PlanAssignment.plan_id, BudgetPlan.name)
            .outerjoin(BudgetPlan, BudgetPlan.id == PlanAssignment.plan_id)
            .where(PlanAssignment.user_id.in_(user_ids), PlanAssignment.user_id.isnot(None))
        )
    ).all()
    out: dict[int, dict] = {}
    for uid, plan_id, plan_name in rows:
        if uid is None:
            continue
        user_id = int(uid)
        if plan_id is None:
            out[user_id] = {
                "user_plan_mode": USER_PLAN_NONE,
                "user_plan_id": None,
                "user_plan_name": None,
            }
        else:
            out[user_id] = {
                "user_plan_mode": USER_PLAN_ASSIGNED,
                "user_plan_id": int(plan_id),
                "user_plan_name": str(plan_name) if plan_name else None,
            }
    for user_id in user_ids:
        out.setdefault(
            user_id,
            {
                "user_plan_mode": USER_PLAN_INHERIT,
                "user_plan_id": None,
                "user_plan_name": None,
            },
        )
    return out


def _user_admin_dict(user: User, roles: list[str], monthly_budget_usd: float | None = None) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "auth_provider": user.auth_provider,
        "role": primary_role_slug(roles),
        "roles": roles,
        "is_active": bool(user.is_active),
        "company": user.company,
        "department": user.department,
        "job_title": user.job_title,
        "office": user.office,
        "reporting_to": user.reporting_to,
        "monthly_budget_usd": monthly_budget_usd if monthly_budget_usd is not None else user.monthly_budget_usd,
        "budget_used_usd": user.budget_used_usd,
        "budget_reserved_usd": user.budget_reserved_usd,
        "totp_enabled": bool(user.totp_enabled) and (user.auth_provider or "local") == "local",
    }


class UserAdminPatch(BaseModel):
    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    role: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    company: str | None = None
    department: str | None = None
    office: str | None = None
    job_title: str | None = None
    reporting_to: str | None = None


class ResetPasswordIn(BaseModel):
    password: str


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    body: UserAdminPatch,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_users_write),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    if body.username is not None:
        username = normalize_username(body.username)
        if not username:
            raise HTTPException(400, "Username is required")
        if await username_taken_ci(db, username, exclude_user_id=user_id):
            raise HTTPException(400, "Username already taken")
        user.username = username
    if body.email is not None:
        email = _clean_optional_str(body.email)
        if email:
            clash = (await db.execute(select(User).where(User.email == email, User.id != user_id))).scalars().first()
            if clash:
                raise HTTPException(400, "Email already in use")
        user.email = email
    if body.display_name is not None:
        user.display_name = _clean_optional_str(body.display_name)
    if body.roles is not None:
        new_slugs = [_normalize_role(s) for s in body.roles] if body.roles else ["user"]
        previous = await get_user_role_slugs(db, user.id)
        await _ensure_actor_may_assign_roles(db, actor, new_slugs, previous_slugs=previous)
        await _ensure_not_last_full_admin_removal(db, user.id, new_slugs)
        saved_roles = await set_user_roles(db, user, new_slugs)
    elif body.role is not None:
        new_role = _normalize_role(body.role)
        previous = await get_user_role_slugs(db, user.id)
        await _ensure_actor_may_assign_roles(db, actor, [new_role], previous_slugs=previous)
        await _ensure_not_last_full_admin_removal(db, user.id, [new_role])
        saved_roles = await set_user_roles(db, user, [new_role])
    else:
        saved_roles = await get_user_role_slugs(db, user.id)
    if body.company is not None:
        user.company = _clean_optional_str(body.company)
    if body.department is not None:
        user.department = _clean_optional_str(body.department)
    if body.office is not None:
        user.office = _clean_optional_str(body.office)
    if body.job_title is not None:
        user.job_title = _clean_optional_str(body.job_title)
    if body.reporting_to is not None:
        user.reporting_to = _clean_optional_str(body.reporting_to)
    if body.is_active is not None and user.is_active != body.is_active:
        if (
            not body.is_active
            and await user_has_full_administrator(db, user.id)
            and await count_active_full_administrators(db) <= 1
        ):
            raise HTTPException(400, detail="Cannot disable the last active Full Administrator account")
        user.is_active = body.is_active
        # Disabling a user revokes their active sessions immediately so a
        # disabled account cannot keep making (even read-only) requests on
        # an already-issued token. Re-enabling does not bump (no new token).
        if not body.is_active:
            user.token_version = int(user.token_version or 0) + 1
    from app.services.budget_service import resolve_monthly_budget

    user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await db.commit()
    await db.refresh(user)
    from app.services.budget_service import resolve_monthly_budget

    resolved_budget = await resolve_monthly_budget(db, user)
    return _user_admin_dict(user, saved_roles, resolved_budget)


@router.post("/users/{user_id}/reset-password")
async def reset_local_user_password(
    user_id: int,
    body: ResetPasswordIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    if user.auth_provider != "local":
        raise HTTPException(400, detail="Password reset is only available for local users")
    from app.services.password_policy import PasswordPolicyError, validate_password

    try:
        pwd = validate_password(body.password)
    except PasswordPolicyError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    user.hashed_password = hash_password(pwd)
    # Revoke all existing sessions: a password reset must invalidate any
    # previously-issued JWT (including any stolen ones).
    user.token_version = int(user.token_version or 0) + 1
    await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/disable-2fa")
async def admin_disable_user_2fa(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    """Super Admin recovery: clear TOTP so the user can sign in and re-enroll."""
    user = await db.get(User, user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(404, detail="User not found")
    if (user.auth_provider or "local") != "local":
        raise HTTPException(400, detail="2FA disable is only available for local users")
    if not user.totp_enabled:
        raise HTTPException(400, detail="Two-factor authentication is not enabled for this user")

    user.totp_enabled = False
    user.totp_secret_encrypted = None
    user.totp_backup_codes_hashed = None
    # Force re-login after MFA recovery.
    user.token_version = int(user.token_version or 0) + 1
    await db.commit()

    from app.services.totp_service import audit

    audit(
        "2fa_admin_disabled",
        username=user.username,
        detail=f"by={actor.username}",
    )
    return {"ok": True, "totp_enabled": False}


class UsersBulkIn(BaseModel):
    user_ids: list[int]
    role: str | None = None
    is_active: bool | None = None
    group_id: int | None = None
    group_action: Literal["add", "remove"] | None = None
    department: str | None = None
    office: str | None = None
    plan_id: int | None = None
    no_plan: bool = False
    inherit_group_plan: bool = False


@router.post("/users/bulk")
async def bulk_update_users(  # noqa: C901 -- Phase 4 split; complexity must not grow
    body: UsersBulkIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_users_write),
):
    if not body.user_ids:
        raise HTTPException(400, detail="No users selected")
    users = (await db.execute(select(User).where(User.id.in_(body.user_ids)))).scalars().all()
    found_ids = {u.id for u in users}
    missing = [uid for uid in body.user_ids if uid not in found_ids]
    if missing:
        raise HTTPException(404, detail=f"Users not found: {missing[:5]}")

    changed = 0

    if body.role is not None:
        new_role = _normalize_role(body.role)
        new_slugs = [new_role]
        if not user_has_super_admin_access(new_slugs):
            demote_count = 0
            for u in users:
                cur = await get_user_role_slugs(db, u.id)
                if user_has_super_admin_access(cur):
                    demote_count += 1
            if demote_count and await count_full_administrators(db) - demote_count < 1:
                raise HTTPException(400, detail="Cannot demote the last Full Administrator account")
        for u in users:
            cur = await get_user_role_slugs(db, u.id)
            if cur != new_slugs:
                await _ensure_actor_may_assign_roles(db, actor, new_slugs, previous_slugs=cur)
                await set_user_roles(db, u, new_slugs)
                changed += 1

    if body.is_active is not None:
        if body.is_active is False:
            to_disable_active_admins = 0
            for u in users:
                if u.is_active and await user_has_full_administrator(db, u.id):
                    to_disable_active_admins += 1
            if to_disable_active_admins and await count_active_full_administrators(db) <= to_disable_active_admins:
                raise HTTPException(400, detail="Cannot disable the last active Full Administrator account")
        for u in users:
            if u.is_active != body.is_active:
                u.is_active = body.is_active
                if not body.is_active:
                    u.token_version = int(u.token_version or 0) + 1
                changed += 1

    if body.group_id and body.group_action:
        group = await db.get(UserGroup, body.group_id)
        if not group:
            raise HTTPException(404, detail="Group not found")
        if body.group_action == "add":
            for uid in body.user_ids:
                exists_row = (
                    await db.execute(
                        select(user_group_members.c.user_id).where(
                            user_group_members.c.user_id == uid,
                            user_group_members.c.group_id == body.group_id,
                        )
                    )
                ).first()
                if not exists_row:
                    await db.execute(insert(user_group_members).values(user_id=uid, group_id=body.group_id))
                    changed += 1
        elif body.group_action == "remove":
            await db.execute(
                delete(user_group_members).where(
                    user_group_members.c.user_id.in_(body.user_ids),
                    user_group_members.c.group_id == body.group_id,
                )
            )
            changed += 1

    dept = _clean_optional_str(body.department) if body.department is not None else None
    office = _clean_optional_str(body.office) if body.office is not None else None
    for u in users:
        if dept is not None:
            u.department = dept
            changed += 1
        if office is not None:
            u.office = office
            changed += 1

    if body.no_plan or body.inherit_group_plan or body.plan_id is not None:
        from app.services.budget_service import resolve_monthly_budget
        from app.services.plan_assignment_service import (
            clear_user_plan_override,
            upsert_user_no_plan,
            upsert_user_plan,
        )

        for u in users:
            if body.inherit_group_plan:
                await clear_user_plan_override(db, u.id)
                u.monthly_budget_usd = await resolve_monthly_budget(db, u)
                changed += 1
            elif body.no_plan:
                await upsert_user_no_plan(db, u.id)
                u.monthly_budget_usd = await resolve_monthly_budget(db, u)
                changed += 1
            elif body.plan_id is not None:
                await upsert_user_plan(db, u.id, body.plan_id)
                u.monthly_budget_usd = await resolve_monthly_budget(db, u)
                changed += 1

    await db.commit()
    return {"ok": True, "count": len(body.user_ids), "changed": changed}


@router.delete("/users/{user_id}")
async def delete_local_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    from app.services.user_lifecycle_service import soft_delete_user

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    if user.deleted_at is not None:
        raise HTTPException(400, detail="User is already in Deleted Users")
    if await user_has_full_administrator(db, user.id) and await count_full_administrators(db) <= 1:
        raise HTTPException(400, detail="Cannot delete the last Full Administrator account")
    await soft_delete_user(db, user)
    await db.commit()
    return {"ok": True, "soft_deleted": True}


class UsersPermanentDeleteIn(BaseModel):
    user_ids: list[int]


@router.post("/users/{user_id}/permanently-delete")
async def permanently_delete_user_endpoint(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_deleted_users_write),
):
    from app.services.user_lifecycle_service import permanently_delete_user

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    if user.deleted_at is None:
        raise HTTPException(400, detail="User must be in Deleted Users before permanent deletion")
    try:
        await permanently_delete_user(db, user)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    await db.commit()
    return {"ok": True}


@router.post("/deleted-users/bulk-permanently-delete")
async def bulk_permanently_delete_users(
    body: UsersPermanentDeleteIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_deleted_users_write),
):
    from app.services.user_lifecycle_service import permanently_delete_user

    if not body.user_ids:
        raise HTTPException(400, detail="No users selected")
    users = (await db.execute(select(User).where(User.id.in_(body.user_ids)))).scalars().all()
    deleted = 0
    for user in users:
        if user.deleted_at is None:
            continue
        try:
            await permanently_delete_user(db, user)
            deleted += 1
        except ValueError:
            continue
    await db.commit()
    return {"ok": True, "deleted": deleted}


@router.get("/user-api-keys")
async def list_user_api_keys(db: AsyncSession = Depends(get_db), _: User = Depends(require_users)):
    from app.models.api_key import UserApiKey

    rows = (
        await db.execute(
            select(UserApiKey, User).join(User, UserApiKey.user_id == User.id).order_by(UserApiKey.created_at.desc())
        )
    ).all()
    roles_map = await get_roles_map(db, [u.id for _, u in rows])
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.key_prefix,
            "is_active": k.is_active,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "user_id": u.id,
            "username": u.username,
            "role": primary_role_slug(roles_map.get(u.id, ["user"])),
            "email": u.email,
            "monthly_budget_usd": u.monthly_budget_usd,
            "budget_used_usd": u.budget_used_usd,
        }
        for k, u in rows
    ]


@router.delete("/user-api-keys/{key_id}")
async def delete_user_api_key(
    key_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_users_write),
):
    from app.models.api_key import UserApiKey

    k = await db.get(UserApiKey, key_id)
    if not k:
        raise HTTPException(404)
    await log_security_event(
        db,
        actor=admin,
        actor_ip=_client_ip(request),
        action="user_api_key_deleted",
        resource_type="user_api_key",
        resource_id=str(k.id),
        detail={"user_id": k.user_id, "name": getattr(k, "name", None)},
    )
    await db.delete(k)
    await db.commit()
    return {"ok": True}


@router.get("/dashboard/error-rates")
async def model_error_rates(
    period: str = "month", db: AsyncSession = Depends(get_db), _: User = Depends(require_dashboard)
):
    since = _period_start(period)
    total_q = (
        select(RequestLog.model_id, func.count().label("total"))
        .where(RequestLog.request_time >= since)
        .group_by(RequestLog.model_id)
    )
    err_q = (
        select(RequestLog.model_id, func.count().label("errors"))
        .where(RequestLog.request_time >= since, RequestLog.success == False)  # noqa: E712
        .group_by(RequestLog.model_id)
    )
    totals = {r[0]: r[1] for r in (await db.execute(total_q)).all()}
    errors = {r[0]: r[1] for r in (await db.execute(err_q)).all()}
    items = []
    for model_id, total in totals.items():
        err = errors.get(model_id, 0)
        rate = (err / total * 100) if total else 0
        items.append({"model_id": model_id, "error_rate_pct": round(rate, 2), "errors": err, "total": total})
    items.sort(key=lambda x: x["error_rate_pct"], reverse=True)
    return {"period": period, "items": items[:10]}


class UserPlanIn(BaseModel):
    plan_id: int | None = None
    no_plan: bool = False
    inherit_group_plan: bool = False


@router.post("/users/{user_id}/budget-reset")
async def reset_user_budget(user_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_users_write)):
    from app.services.budget_service import resolve_monthly_budget
    from app.models.budget_reservation import BudgetReservation

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    reset_at = datetime.utcnow()
    user.budget_used_usd = 0.0
    user.budget_reserved_usd = 0.0
    user.budget_period_start = reset_at
    await db.execute(
        update(BudgetReservation)
        .where(
            BudgetReservation.subject_type == "user",
            BudgetReservation.subject_id == user_id,
            BudgetReservation.status == "held",
        )
        .values(status="released", settled_at=reset_at)
    )
    user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await db.flush()
    return {"ok": True, "budget_used_usd": 0.0}


@router.patch("/users/{user_id}/plan")
async def set_user_plan(
    user_id: int,
    body: UserPlanIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    from app.services.budget_service import resolve_monthly_budget
    from app.services.plan_assignment_service import (
        clear_user_plan_override,
        get_user_direct_assignment,
        upsert_user_no_plan,
        upsert_user_plan,
        user_plan_mode,
    )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)

    selected = sum([body.no_plan, body.inherit_group_plan, body.plan_id is not None])
    if selected > 1:
        raise HTTPException(400, detail="Specify only one of plan_id, no_plan, or inherit_group_plan")

    if body.inherit_group_plan:
        await clear_user_plan_override(db, user_id)
    elif body.no_plan:
        await upsert_user_no_plan(db, user_id)
    elif body.plan_id is not None:
        await upsert_user_plan(db, user_id, body.plan_id)

    user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await db.commit()
    assignment = await get_user_direct_assignment(db, user_id)
    mode = user_plan_mode(assignment)
    return {
        "monthly_budget_usd": user.monthly_budget_usd,
        "user_plan_mode": mode,
        "user_plan_id": assignment.plan_id if assignment and assignment.plan_id is not None else None,
    }


def _period_start(period: str) -> datetime:
    now = datetime.utcnow()
    if period == "day":
        return now - timedelta(days=1)
    if period == "week":
        return now - timedelta(days=7)
    return datetime(now.year, now.month, 1)


async def _fetch_logs_since(
    db: AsyncSession,
    since: datetime,
    *,
    user_id: int | None = None,
    user_ids: list[int] | None = None,
    alpha_router_api_key_id: int | None = None,
    user_api_key_id: int | None = None,
    connection_id: int | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
) -> list[RequestLog]:
    q = select(RequestLog).where(RequestLog.request_time >= since)
    if user_id is not None:
        q = q.where(RequestLog.user_id == user_id)
    elif user_ids is not None:
        if not user_ids:
            return []
        q = q.where(RequestLog.user_id.in_(user_ids))
    if alpha_router_api_key_id is not None:
        q = q.where(RequestLog.alpha_router_api_key_id == alpha_router_api_key_id)
    if user_api_key_id is not None:
        if user_api_key_id < 0:
            return []
        q = q.where(RequestLog.user_api_key_id == user_api_key_id)
    if connection_id is not None:
        model_ids = (
            (await db.execute(select(AIModel.external_id).where(AIModel.connection_id == connection_id)))
            .scalars()
            .all()
        )
        if not model_ids:
            return []
        q = q.where(RequestLog.model_id.in_(list(model_ids)))
    if agent_id is not None:
        q = q.where(
            or_(
                RequestLog.id.in_(
                    select(AgentRun.request_log_id).where(
                        AgentRun.agent_id == agent_id,
                        AgentRun.request_log_id.is_not(None),
                    )
                ),
                RequestLog.usage_operation_id.in_(
                    select(AgentRun.usage_operation_id).where(
                        AgentRun.agent_id == agent_id,
                        AgentRun.usage_operation_id.is_not(None),
                    )
                ),
            )
        )
    if project_id is not None:
        q = q.where(RequestLog.project_id == project_id)
    return (await db.execute(q.order_by(RequestLog.request_time.asc()))).scalars().all()


def _activity_query_filters(
    *,
    model_id: str | None,
    username: str | None,
    app: str | None,
    response_status: str | None,
    api_key_id: int | None = None,
    user_api_key_id: int | None = None,
) -> dict:
    return {
        "model_id": (model_id or "").strip() or None,
        "username": (username or "").strip() or None,
        "app": (app or "").strip() or None,
        "response_status": response_status if response_status in ("success", "fail") else None,
        "alpha_router_api_key_id": (api_key_id if api_key_id and api_key_id > 0 else None),
        "user_api_key_id": user_api_key_id,
    }


async def _period_api_key_filter_options(db: AsyncSession, rows: list) -> list[dict]:
    """API keys that appear in the selected activity period."""
    key_ids = sorted(
        {int(row.alpha_router_api_key_id) for row in rows if getattr(row, "alpha_router_api_key_id", None)}
    )
    if not key_ids:
        return []
    key_rows = (
        await db.execute(
            select(
                AlphaRouterApiKey.id,
                AlphaRouterApiKey.name,
                AlphaRouterApiKey.key_prefix,
            ).where(AlphaRouterApiKey.id.in_(key_ids))
        )
    ).all()
    by_id = {int(kid): (name, prefix) for kid, name, prefix in key_rows}
    out: list[dict] = []
    for kid in key_ids:
        name, prefix = by_id.get(kid, (f"API key #{kid}", ""))
        name_s = (name or f"API key #{kid}").strip()
        prefix_s = (prefix or "").strip()
        out.append(
            {
                "key": str(kid),
                "label": f"{name_s} {prefix_s}".strip(),
                "name": name_s,
                "prefix": prefix_s,
            }
        )
    out.sort(key=lambda item: str(item.get("name") or item["key"]).lower())
    return out


def activity_explore_opts(
    explore_metric: str | None = Query(None, max_length=32),
    explore_group: str | None = Query(None, max_length=32),
    explore_subgroup: str | None = Query(None, max_length=32),
    explore_rollup: str | None = Query(None, max_length=16),
    explore_top_mode: str | None = Query(None, pattern="^(top|bottom)$"),
    explore_top_n: int | None = Query(None, ge=1, le=30),
    explore_rank_by: str | None = Query(None, pattern="^(metric|requests)$"),
    explore_show_other: bool | None = Query(None),
    explore_cumulative: bool | None = Query(None),
    explore_chart_type: str | None = Query(None, pattern="^(bar|line|area)$"),
) -> dict:
    """Shared Explore query params for every Activity dashboard scope."""
    return {
        "metric": explore_metric or "total_usage",
        "group": explore_group or "model",
        "subgroup": explore_subgroup,
        "rollup": explore_rollup or "daily",
        "top_mode": explore_top_mode or "top",
        "top_n": explore_top_n or 10,
        "rank_by": explore_rank_by or "metric",
        "show_other": True if explore_show_other is None else explore_show_other,
        "cumulative": False if explore_cumulative is None else explore_cumulative,
        "chart_type": explore_chart_type or "bar",
    }


async def _activity_options_and_meta(db: AsyncSession, options_rows: list, group_by: str) -> tuple[dict, dict]:
    options = activity_service.filter_options(options_rows, group_by)
    options["available_api_keys"] = await _period_api_key_filter_options(db, options_rows)
    options["group_by"] = group_by
    api_key_meta = {str(item["key"]): item for item in options["available_api_keys"] if item.get("key") is not None}
    return options, api_key_meta


def _period_prev_since(period: str, now: datetime) -> tuple[datetime, datetime]:
    since = activity_service.activity_period_start(period, now)
    span = now - since
    return since, since - span


async def _load_activity_context(
    db: AsyncSession,
    *,
    period: str,
    prompts_period: str | None = None,
    group_by: str,
    timezone: str,
    filters: dict,
    user_id: int | None = None,
    user_ids: list[int] | None = None,
    alpha_router_api_key_id: int | None = None,
    connection_id: int | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
) -> tuple[list, list, list, list, datetime, datetime, list, list, datetime]:
    now = datetime.utcnow()
    prompts_period = prompts_period or period
    since, prev_since = _period_prev_since(period, now)
    since_prompts, prev_since_prompts = _period_prev_since(prompts_period, now)
    heatmap_since = now - timedelta(days=activity_service.HEATMAP_DAYS)
    since_all = min(prev_since, prev_since_prompts, heatmap_since, since, since_prompts)

    all_rows = await _fetch_logs_since(
        db,
        since_all,
        user_id=user_id,
        user_ids=user_ids,
        alpha_router_api_key_id=alpha_router_api_key_id,
        connection_id=connection_id,
        agent_id=agent_id,
        project_id=project_id,
    )
    period_rows = [r for r in all_rows if (r.request_time or now) >= since]
    options_rows = period_rows
    filtered = activity_service.apply_activity_filters(period_rows, **filters)
    prev_rows = [
        r
        for r in activity_service.apply_activity_filters(all_rows, **filters)
        if prev_since <= (r.request_time or now) < since
    ]
    prompts_period_rows = [r for r in all_rows if (r.request_time or now) >= since_prompts]
    prompts_filtered = activity_service.apply_activity_filters(prompts_period_rows, **filters)
    prompts_prev_rows = [
        r
        for r in activity_service.apply_activity_filters(all_rows, **filters)
        if prev_since_prompts <= (r.request_time or now) < since_prompts
    ]
    heatmap_rows = [
        r
        for r in activity_service.apply_activity_filters(all_rows, **filters)
        if (r.request_time or now) >= heatmap_since
    ]
    return (
        filtered,
        prev_rows,
        heatmap_rows,
        options_rows,
        since,
        now,
        prompts_filtered,
        prompts_prev_rows,
        since_prompts,
    )


async def _build_scoped_activity(
    db: AsyncSession,
    *,
    period: str,
    prompts_period: str | None,
    timezone: str,
    filters: dict,
    explore: dict,
    group_by: str = "model",
    user_id: int | None = None,
    user_ids: list[int] | None = None,
    alpha_router_api_key_id: int | None = None,
    connection_id: int | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
) -> tuple[dict, dict, dict]:
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"
    (
        rows,
        prev_rows,
        heatmap_rows,
        options_rows,
        since,
        now,
        prompts_rows,
        prompts_prev_rows,
        since_prompts,
    ) = await _load_activity_context(
        db,
        period=period,
        prompts_period=pp,
        group_by=group_by,
        timezone=timezone,
        filters=filters,
        user_id=user_id,
        user_ids=user_ids,
        alpha_router_api_key_id=alpha_router_api_key_id,
        connection_id=connection_id,
        agent_id=agent_id,
        project_id=project_id,
    )
    options, api_key_meta = await _activity_options_and_meta(db, options_rows, group_by)
    payload = activity_service.build_activity_payload(
        rows,
        period=period,
        since=since,
        group_by=group_by,
        timezone=timezone,
        now=now,
        prev_rows=prev_rows,
        heatmap_rows=heatmap_rows,
        api_key_meta=api_key_meta,
        explore=explore,
    )
    prompts_card = activity_service.build_prompts_card(
        prompts_rows,
        period=pp,
        since=since_prompts,
        group_by=group_by,
        timezone=timezone,
        now=now,
        prev_rows=prompts_prev_rows,
        heatmap_rows=heatmap_rows,
    )
    return payload, options, prompts_card


async def _prepare_activity_export(
    db: AsyncSession,
    *,
    period: str,
    prompts_period: str | None,
    group_by: str,
    timezone: str,
    filters: dict,
    user_id: int | None = None,
    user_ids: list[int] | None = None,
    alpha_router_api_key_id: int | None = None,
    connection_id: int | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
) -> tuple[list, dict, dict, dict, datetime, datetime]:
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"
    (
        rows,
        prev_rows,
        heatmap_rows,
        _,
        since,
        now,
        prompts_rows,
        prompts_prev_rows,
        since_prompts,
    ) = await _load_activity_context(
        db,
        period=period,
        prompts_period=pp,
        group_by=group_by,
        timezone=timezone,
        filters=filters,
        user_id=user_id,
        user_ids=user_ids,
        alpha_router_api_key_id=alpha_router_api_key_id,
        connection_id=connection_id,
        agent_id=agent_id,
        project_id=project_id,
    )
    payload = activity_service.build_activity_payload(
        rows,
        period=period,
        since=since,
        group_by=group_by,
        timezone=timezone,
        now=now,
        prev_rows=prev_rows,
        heatmap_rows=heatmap_rows,
    )
    prompts_card = activity_service.build_prompts_card(
        prompts_rows,
        period=pp,
        since=since_prompts,
        group_by=group_by,
        timezone=timezone,
        now=now,
        prev_rows=prompts_prev_rows,
        heatmap_rows=heatmap_rows,
    )
    return rows, payload, prompts_card, filters, since, now


async def _activity_export_response(
    db: AsyncSession,
    *,
    format: str,
    filename_stem: str,
    scope: str,
    jwt_token: str,
    user_role: str,
    period: str,
    prompts_period: str | None,
    group_by: str,
    timezone: str,
    filters: dict,
    user_id: int | None = None,
    user_ids: list[int] | None = None,
    group_id: int | None = None,
    alpha_router_api_key_id: int | None = None,
    connection_id: int | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
) -> Response:
    if format == "pdf":
        try:
            content = await render_activity_page_pdf(
                scope=scope,
                user_role=user_role,
                jwt_token=jwt_token,
                period=period,
                prompts_period=prompts_period,
                timezone=timezone,
                group_by=group_by,
                model_id=filters.get("model_id"),
                username=filters.get("username"),
                app=filters.get("app"),
                response_status=filters.get("response_status"),
                user_id=user_id,
                group_id=group_id,
                connection_id=connection_id,
                api_key_id=alpha_router_api_key_id,
                agent_id=agent_id,
                project_id=project_id,
            )
        except ActivityPdfError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        name = f"{filename_stem}.pdf"
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    rows, _, _, filters, _, _ = await _prepare_activity_export(
        db,
        period=period,
        prompts_period=prompts_period,
        group_by=group_by,
        timezone=timezone,
        filters=filters,
        user_id=user_id,
        user_ids=user_ids,
        alpha_router_api_key_id=alpha_router_api_key_id,
        connection_id=connection_id,
        agent_id=agent_id,
        project_id=project_id,
    )
    provider_map, key_map, user_key_map = await resolve_log_export_maps(db, rows)
    df = request_logs_to_export_dataframe(
        rows,
        tz_mode=timezone,
        provider_map=provider_map,
        key_map=key_map,
        user_key_map=user_key_map,
    )
    content, media, ext_name = export_activity_logs_workbook(df)
    ext = ext_name.rsplit(".", 1)[-1]
    name = f"{filename_stem}.{ext}"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/dashboard/activity")
async def dashboard_activity(
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    group_by: str = Query("model", pattern="^(model|app|user)$"),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    model_id: str | None = Query(None, max_length=256),
    username: str | None = Query(None, max_length=128),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    api_key_id: int | None = Query(None, ge=1),
    explore: dict = Depends(activity_explore_opts),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_dashboard),
):
    filters = _activity_query_filters(
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
        api_key_id=api_key_id,
    )
    payload, options, prompts_card = await _build_scoped_activity(
        db,
        period=period,
        prompts_period=prompts_period,
        timezone=timezone,
        filters=filters,
        explore=explore,
        group_by=group_by,
    )
    return {
        **payload,
        **options,
        "prompts": prompts_card,
        "scope": "service",
        "filters": filters,
    }


@router.get("/dashboard/activity/export")
async def dashboard_activity_export(
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    group_by: str = Query("model", pattern="^(model|app|user)$"),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    model_id: str | None = Query(None, max_length=256),
    username: str | None = Query(None, max_length=128),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    api_key_id: int | None = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_dashboard),
    jwt_token: str = Depends(get_bearer_token),
):
    filters = _activity_query_filters(
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
        api_key_id=api_key_id,
    )
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-activity-{period}-{group_by}",
        scope="service",
        jwt_token=jwt_token,
        user_role=await primary_role_for_user(db, admin.id),
        period=period,
        prompts_period=prompts_period,
        group_by=group_by,
        timezone=timezone,
        filters=filters,
    )


@router.get("/project-usage")
async def project_usage_overview(
    period: str = Query("month", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_reports),
):
    from app.services.project_billing_service import list_projects_usage_overview

    now = datetime.utcnow()
    since = activity_service.activity_period_start(period, now)
    projects = await list_projects_usage_overview(db, since, now)
    return {"period": period, "start": since.isoformat() + "Z", "end": now.isoformat() + "Z", "projects": projects}


@router.get("/users/{user_id}/activity")
async def user_activity(
    user_id: int,
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    explore: dict = Depends(activity_explore_opts),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, detail="User not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=app, response_status=response_status)
    payload, options, prompts_card = await _build_scoped_activity(
        db,
        period=period,
        prompts_period=prompts_period,
        timezone=timezone,
        filters=filters,
        explore=explore,
        user_id=user_id,
    )
    return {
        **payload,
        **options,
        "prompts": prompts_card,
        "user": {"id": user.id, "username": user.username, "display_name": user.display_name},
        "scope": "user",
        "model_id": filters["model_id"],
        "filters": filters,
    }


@router.get("/api-keys/{key_id}/activity")
async def api_key_activity(
    key_id: int,
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    explore: dict = Depends(activity_explore_opts),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_keys),
):
    key = await db.get(AlphaRouterApiKey, key_id)
    if not key:
        raise HTTPException(404, detail="API key not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=app, response_status=response_status)
    payload, options, prompts_card = await _build_scoped_activity(
        db,
        period=period,
        prompts_period=prompts_period,
        timezone=timezone,
        filters=filters,
        explore=explore,
        alpha_router_api_key_id=key_id,
    )
    changelog = await fetch_api_key_changelog(db, key_id)
    return {
        **payload,
        **options,
        "prompts": prompts_card,
        "api_key": {"id": key.id, "name": key.name, "prefix": key.key_prefix},
        "scope": "api_key",
        "model_id": filters["model_id"],
        "filters": filters,
        "changelog": changelog,
    }


@router.get("/api-keys/{key_id}/activity/export")
async def api_key_activity_export(
    key_id: int,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_api_keys),
    jwt_token: str = Depends(get_bearer_token),
):
    key = await db.get(AlphaRouterApiKey, key_id)
    if not key:
        raise HTTPException(404, detail="API key not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=app, response_status=response_status)
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-api-key-{key_id}-activity-{period}",
        scope="api_key",
        jwt_token=jwt_token,
        user_role=await primary_role_for_user(db, admin.id),
        period=period,
        prompts_period=prompts_period,
        group_by="model",
        timezone=timezone,
        filters=filters,
        alpha_router_api_key_id=key_id,
    )


def _parse_changelog_date(raw: str | None) -> date | None:
    if not raw or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError as exc:
        raise HTTPException(400, detail="Invalid date; use YYYY-MM-DD") from exc


@router.get("/api-keys/{key_id}/changelog")
async def api_key_changelog(
    key_id: int,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_keys),
):
    key = await db.get(AlphaRouterApiKey, key_id)
    if not key:
        raise HTTPException(404, detail="API key not found")
    fd = _parse_changelog_date(from_date)
    td = _parse_changelog_date(to_date)
    if fd and td and fd > td:
        raise HTTPException(400, detail="'from' must be on or before 'to'")
    return {
        "items": await fetch_api_key_changelog(db, key_id, from_date=fd, to_date=td),
    }


@router.get("/connections/{conn_id}/activity")
async def connection_activity(
    conn_id: int,
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    username: str | None = Query(None, max_length=128),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    api_key_id: int | None = Query(None, ge=1),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    explore: dict = Depends(activity_explore_opts),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_connections),
):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404, detail="Connection not found")
    filters = _activity_query_filters(
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
        api_key_id=api_key_id,
    )
    payload, options, prompts_card = await _build_scoped_activity(
        db,
        period=period,
        prompts_period=prompts_period,
        timezone=timezone,
        filters=filters,
        explore=explore,
        connection_id=conn_id,
    )
    changelog = await fetch_connection_changelog(db, conn_id)
    return {
        **payload,
        **options,
        "prompts": prompts_card,
        "connection": {
            "id": conn.id,
            "name": conn.name,
            "provider_type": conn.provider_type,
            "base_url": conn.base_url,
            "is_active": conn.is_active,
        },
        "scope": "connection",
        "model_id": filters["model_id"],
        "filters": filters,
        "changelog": changelog,
    }


@router.get("/connections/{conn_id}/activity/export")
async def connection_activity_export(
    conn_id: int,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    username: str | None = Query(None, max_length=128),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    api_key_id: int | None = Query(None, ge=1),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_connections),
    jwt_token: str = Depends(get_bearer_token),
):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404, detail="Connection not found")
    filters = _activity_query_filters(
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
        api_key_id=api_key_id,
    )
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-connection-{conn_id}-activity-{period}",
        scope="connection",
        jwt_token=jwt_token,
        user_role=await primary_role_for_user(db, admin.id),
        period=period,
        prompts_period=prompts_period,
        group_by="model",
        timezone=timezone,
        filters=filters,
        connection_id=conn_id,
    )


@router.get("/connections/{conn_id}/changelog")
async def connection_changelog(
    conn_id: int,
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_connections),
):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404, detail="Connection not found")
    fd = _parse_changelog_date(from_date)
    td = _parse_changelog_date(to_date)
    if fd and td and fd > td:
        raise HTTPException(400, detail="'from' must be on or before 'to'")
    return {
        "items": await fetch_connection_changelog(db, conn_id, from_date=fd, to_date=td),
    }


@router.get("/users/{user_id}/activity/export")
async def user_activity_export(
    user_id: int,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    app: str | None = Query(None, max_length=64),
    response_status: str | None = Query(None, pattern="^(success|fail)$"),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_users),
    jwt_token: str = Depends(get_bearer_token),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, detail="User not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=app, response_status=response_status)
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-user-{user_id}-activity-{period}",
        scope="user",
        jwt_token=jwt_token,
        user_role=await primary_role_for_user(db, admin.id),
        period=period,
        prompts_period=prompts_period,
        group_by="model",
        timezone=timezone,
        filters=filters,
        user_id=user_id,
    )


class StorageSettingsPatch(BaseModel):
    retention_days: int | None = None
    clear_schedule_enabled: bool | None = None
    clear_schedule_hour: int | None = None
    clear_schedule_minute: int | None = None
    user_media_quota_gb: int | None = None
    project_media_quota_gb: int | None = None
    max_upload_file_mb: int | None = None
    max_chat_attachments_total_mb: int | None = None
    max_media_zip_download_mb: int | None = None
    max_chat_attachments_count: int | None = None
    max_code_interpreter_workspace_files: int | None = None
    max_code_interpreter_workspace_total_mb: int | None = None


class ChatRetentionSettingsPatch(BaseModel):
    retention_enabled: bool | None = None
    retention_days: int | None = None
    clear_schedule_enabled: bool | None = None
    clear_schedule_hour: int | None = None
    clear_schedule_minute: int | None = None


@router.get("/storage")
async def get_storage_overview(db: AsyncSession = Depends(get_db), _: User = Depends(require_storage)):
    from app.services.retention_policy_service import chat_retention_stats, get_chat_retention_settings

    stats = await storage_stats(db)
    by_kind_rows = (
        await db.execute(
            select(
                MediaAsset.kind, func.count(MediaAsset.id), func.coalesce(func.sum(MediaAsset.size_bytes), 0)
            ).group_by(MediaAsset.kind)
        )
    ).all()
    stats["by_kind"] = [{"kind": r[0], "count": int(r[1] or 0), "size_bytes": int(r[2] or 0)} for r in by_kind_rows]
    stats["chat"] = {
        "stats": await chat_retention_stats(db),
        "settings": await get_chat_retention_settings(db),
    }
    from app.services.log_detail_retention_service import get_raw_payload_retention

    # Raw provider responses stored behind API Logs: the third thing this page
    # governs, alongside media files and chat history.
    stats["api_logs"] = await get_raw_payload_retention(db)
    quota_gb = await get_user_media_quota_gb(db)
    stats["settings"]["user_media_quota_gb"] = quota_gb
    stats["settings"]["user_media_quota_bytes"] = await get_user_media_quota_bytes(db)
    project_quota_gb = await get_project_media_quota_gb(db)
    stats["settings"]["project_media_quota_gb"] = project_quota_gb
    stats["settings"]["project_media_quota_bytes"] = await get_project_media_quota_bytes(db)
    from app.services.transfer_limits_service import get_transfer_limits, transfer_limits_public_view

    stats["settings"].update(transfer_limits_public_view(await get_transfer_limits(db)))
    stats["users_over_quota"] = await count_users_over_media_quota(db)
    stats["projects_over_quota"] = await count_projects_over_media_quota(db)
    return stats


@router.patch("/storage/settings")
async def patch_storage_settings(
    body: StorageSettingsPatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_storage_write),
):
    settings = await set_storage_settings(
        db,
        retention_days=body.retention_days,
        clear_schedule_enabled=body.clear_schedule_enabled,
        clear_schedule_hour=body.clear_schedule_hour,
        clear_schedule_minute=body.clear_schedule_minute,
    )
    if body.user_media_quota_gb is not None:
        quota_gb = await set_user_media_quota_gb(db, body.user_media_quota_gb)
        settings = {
            **settings,
            "user_media_quota_gb": quota_gb,
            "user_media_quota_bytes": quota_gb * 1024 * 1024 * 1024,
        }
    if body.project_media_quota_gb is not None:
        project_quota_gb = await set_project_media_quota_gb(db, body.project_media_quota_gb)
        settings = {
            **settings,
            "project_media_quota_gb": project_quota_gb,
            "project_media_quota_bytes": project_quota_gb * 1024 * 1024 * 1024,
        }
    transfer_fields = (
        body.max_upload_file_mb is not None
        or body.max_chat_attachments_total_mb is not None
        or body.max_media_zip_download_mb is not None
        or body.max_chat_attachments_count is not None
        or body.max_code_interpreter_workspace_files is not None
        or body.max_code_interpreter_workspace_total_mb is not None
    )
    if transfer_fields:
        from app.services.transfer_limits_service import set_transfer_limits, transfer_limits_public_view

        try:
            transfer = await set_transfer_limits(
                db,
                max_upload_file_mb=body.max_upload_file_mb,
                max_chat_attachments_total_mb=body.max_chat_attachments_total_mb,
                max_media_zip_download_mb=body.max_media_zip_download_mb,
                max_chat_attachments_count=body.max_chat_attachments_count,
                max_code_interpreter_workspace_files=body.max_code_interpreter_workspace_files,
                max_code_interpreter_workspace_total_mb=body.max_code_interpreter_workspace_total_mb,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        settings = {**settings, **transfer_limits_public_view(transfer)}
    await db.commit()
    edge_sync = None
    if transfer_fields:
        from app.services.tls_edge_service import sync_edge_body_limit

        # Fire-and-queue only: never await edge nginx apply (avoids admin Save timeouts).
        try:
            edge_sync = await sync_edge_body_limit(db)
        except Exception as exc:  # noqa: BLE001 -- error text is surfaced to the caller
            edge_sync = {
                "attempted": True,
                "queued": False,
                "applied": False,
                "reason": "sync_failed",
                "error": str(exc),
            }
    await refresh_storage_cleanup_schedule()
    payload: dict = {"ok": True, "settings": settings}
    if edge_sync is not None:
        payload["edge_sync"] = edge_sync
    return payload


class ApiLogRetentionSettingsPatch(BaseModel):
    retention_days: int = Field(..., ge=1, le=365)


@router.patch("/storage/api-log-settings")
async def patch_api_log_retention_settings(
    body: ApiLogRetentionSettingsPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_storage_write),
):
    """How long the raw provider responses behind API Logs are kept.

    Saving applies the new window at once — an operator who shortens it expects
    what falls outside to be gone now, not at the next nightly run — so the
    purge is part of this call and lands in the security audit with it.
    """
    from app.services.client_ip import resolve_client_ip
    from app.services.log_detail_retention_service import (
        get_raw_payload_retention,
        purge_expired_raw_payloads,
        set_raw_payload_retention_days,
    )
    from app.services.security_audit import log_security_event

    saved = await set_raw_payload_retention_days(db, body.retention_days)
    purged = await purge_expired_raw_payloads(db, days=saved["retention_days"])
    await log_security_event(
        db,
        actor=admin,
        actor_ip=resolve_client_ip(request),
        action="api_logs_raw_payload_retention_changed",
        resource_type="request_log",
        detail={"retention_days": saved["retention_days"], **purged},
    )
    await db.commit()
    return {"ok": True, "api_logs": await get_raw_payload_retention(db), "purged": purged}


@router.patch("/storage/chat-settings")
async def patch_chat_retention_settings(
    body: ChatRetentionSettingsPatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_storage_write),
):
    from app.services.retention_policy_service import set_chat_retention_settings

    settings = await set_chat_retention_settings(
        db,
        retention_enabled=body.retention_enabled,
        retention_days=body.retention_days,
        clear_schedule_enabled=body.clear_schedule_enabled,
        clear_schedule_hour=body.clear_schedule_hour,
        clear_schedule_minute=body.clear_schedule_minute,
    )
    await db.commit()
    await refresh_chat_retention_cleanup_schedule()
    return {"ok": True, "settings": settings}


@router.post("/storage/purge-expired-chat")
async def admin_purge_expired_chat(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_storage_write),
):
    from app.services.retention_policy_service import get_chat_retention_settings, purge_expired_chat_messages

    settings = await get_chat_retention_settings(db)
    if not settings["retention_enabled"]:
        raise HTTPException(status_code=400, detail="Chat retention policy is disabled.")
    result = await purge_expired_chat_messages(db)
    await db.commit()
    return {"ok": True, **result}


async def _validated_connection_base_url(raw: str | None) -> str | None:
    """A provider base_url is fetched server-side with the connection's API key.

    Without a check an admin-level account (or a CSRF'd admin) could point a
    connection at http://169.254.169.254/ or an internal service and have
    Alpharouter POST the credentialed model-sync/completion requests there.
    ALLOW_SSRF_PRIVATE_RANGES=true keeps internal, self-hosted providers working.
    """
    from app.services.ssrf_guard import SSRFBlockedError, assert_url_safe

    value = (raw or "").strip() or None
    if value is None:
        return None
    if not value.lower().startswith(("http://", "https://")):
        raise HTTPException(400, detail="base_url must start with http:// or https://")
    try:
        # assert_url_safe resolves DNS synchronously; keep it off the event loop.
        await asyncio.to_thread(assert_url_safe, value)
    except SSRFBlockedError as exc:
        raise HTTPException(
            400,
            detail=(
                "base_url points at a private, loopback or metadata address. "
                "Set ALLOW_SSRF_PRIVATE_RANGES=true only for a trusted internal provider."
            ),
        ) from exc
    return value


def _client_ip(request: Request) -> str | None:
    try:
        return resolve_client_ip(request)
    except Exception:  # noqa: BLE001 -- external/optional dependency; falls back (return request.client.host if request.cl)
        return request.client.host if request.client else None


class DestructiveConfirmIn(BaseModel):
    """Server-side typed confirmation for irreversible, platform-wide deletes."""

    confirm: str = ""


CLEAR_ALL_MEDIA_PHRASE = "DELETE ALL MEDIA"


@router.post("/storage/clear-cache")
async def admin_clear_storage_cache(
    body: DestructiveConfirmIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_storage_write),
    _: User = Depends(require_super_admin),
):
    """Delete every media asset. Super Admin, typed phrase, audited before the delete."""
    if body.confirm.strip() != CLEAR_ALL_MEDIA_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f'Type "{CLEAR_ALL_MEDIA_PHRASE}" in confirm to delete all media.',
        )
    from app.models.media import MediaAsset

    count, total_bytes = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(MediaAsset.size_bytes), 0)).select_from(MediaAsset)
        )
    ).one()
    await log_security_event(
        db,
        actor=admin,
        actor_ip=_client_ip(request),
        action="media_cleared_all",
        resource_type="storage",
        detail={"asset_count": int(count or 0), "total_bytes": int(total_bytes or 0)},
    )
    result = await clear_all_media(db)
    await db.commit()
    return {"ok": True, **result}


@router.post("/storage/purge-expired")
async def admin_purge_expired_storage(db: AsyncSession = Depends(get_db), _: User = Depends(require_storage_write)):
    settings = await get_storage_settings(db)
    result = await purge_expired_media(db, retention_days=int(settings["retention_days"]))
    return {"ok": True, **result}


@router.get("/database/monitor")
async def admin_database_monitor(db: AsyncSession = Depends(get_db), _: User = Depends(require_database)):
    """Read-only SQLite / PostgreSQL health and table row counts."""
    return await collect_database_monitor(db)


class AdminUserMediaBulkDeleteIn(BaseModel):
    ids: list[int] = []


class AdminUserMediaDownloadZipIn(BaseModel):
    ids: list[int] = []


class AdminUserMediaScheduleIn(BaseModel):
    cleanup_enabled: bool | None = None
    cleanup_retention_days: int | None = None
    cleanup_hour: int | None = None
    cleanup_minute: int | None = None


async def _admin_media_target_user(db: AsyncSession, user_id: int) -> User:
    row = await db.get(User, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return row


@router.get("/users/{user_id}/media/quota")
async def admin_user_media_quota(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users),
):
    target = await _admin_media_target_user(db, user_id)
    await purge_expired_media(db)
    summary = await user_media_quota_summary(db, target.id)
    return {
        **summary,
        "user_id": target.id,
        "username": target.username,
        "display_name": target.display_name,
    }


@router.get("/users/{user_id}/media")
async def admin_user_media_list(
    user_id: int,
    q: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users),
):
    target = await _admin_media_target_user(db, user_id)
    await purge_expired_media(db)
    rows, total = await list_user_media_filtered(
        db,
        target.id,
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
        "user_id": target.id,
        "username": target.username,
        "display_name": target.display_name,
    }


@router.get("/users/{user_id}/media/schedule")
async def admin_user_media_schedule_get(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users),
):
    target = await _admin_media_target_user(db, user_id)
    prefs = await get_or_create_user_media_prefs(db, target.id)
    return prefs_to_dict(prefs)


@router.patch("/users/{user_id}/media/schedule")
async def admin_user_media_schedule_patch(
    user_id: int,
    body: AdminUserMediaScheduleIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    target = await _admin_media_target_user(db, user_id)
    prefs = await get_or_create_user_media_prefs(db, target.id)
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


@router.post("/users/{user_id}/media/download-zip")
async def admin_user_media_download_zip(
    user_id: int,
    body: AdminUserMediaDownloadZipIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    target = await _admin_media_target_user(db, user_id)
    try:
        path, _packed = await build_media_zip_file(db, target.id, body.ids)
    except MediaZipLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    safe_user = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (target.username or "user"))
    filename = f"alpha-router-media-{safe_user}-{stamp}.zip"
    return StreamingResponse(
        stream_media_zip(path),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/users/{user_id}/media/bulk-delete")
async def admin_user_media_bulk_delete(
    user_id: int,
    body: AdminUserMediaBulkDeleteIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    target = await _admin_media_target_user(db, user_id)
    removed = await delete_user_media_ids(db, target.id, body.ids)
    return {"ok": True, "removed": removed}


@router.delete("/users/{user_id}/media/all")
async def admin_user_media_delete_all(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    target = await _admin_media_target_user(db, user_id)
    removed = await delete_all_user_media(db, target.id)
    return {"ok": True, "removed": removed}


@router.delete("/users/{user_id}/media/{asset_id}")
async def admin_user_media_delete_one(
    user_id: int,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    target = await _admin_media_target_user(db, user_id)
    removed = await delete_user_media_ids(db, target.id, [asset_id])
    if not removed:
        raise HTTPException(status_code=404, detail="Media not found")
    return {"ok": True}
