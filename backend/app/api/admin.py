"""Admin REST API: connections, models, keys, plans, users, dashboard, debug."""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, exists, func, insert, or_, select, update
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
    require_role_catalog,
    require_storage,
    require_storage_write,
    require_users,
    require_users_write,
    require_deleted_users,
    require_deleted_users_write,
)
from app.core.security import generate_api_key, generate_api_key_for_user, hash_password
from app.database import get_db
from app.models.api_key import AlphaRouterApiKey
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.connection import Connection
from app.models.media import MediaAsset
from app.models.logging import RequestLog
from app.models.model_catalog import AIModel
from app.models.user import User, UserGroup, user_group_members
from app.services import activity_service
from app.services.model_capabilities import model_catalog_meta, model_kinds
from app.services.model_sync import (
    disable_models_for_connection,
    enable_models_for_connection,
    sync_connection_models,
    sync_connection_with_flash,
)
from app.services.secret_crypto import decrypt_secret, encrypt_secret, mask_secret
from app.services.log_export_service import request_logs_to_export_dataframe, resolve_log_export_maps
from app.services.activity_pdf_service import ActivityPdfError, render_activity_page_pdf
from app.services.reports_service import export_activity_logs_workbook
from app.services.scheduler import refresh_chat_retention_cleanup_schedule, refresh_storage_cleanup_schedule
from app.services.db_monitor_service import collect_database_monitor
from app.services.connection_audit import (
    connection_snapshot,
    fetch_connection_changelog,
    log_connection_created,
    log_connection_status,
    log_connection_updated,
    touch_connection_modified,
)
from app.services.alpha_router_api_key_audit import (
    fetch_api_key_changelog,
    log_api_key_created,
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
from app.services.smtp_service import SmtpNotConfiguredError, SmtpSendError, send_email
from app.services.rbac import (
    FULL_ADMIN_SLUG,
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
    set_user_roles,
    user_has_full_administrator,
)

API_KEY_PAGE_SIZES = {10, 20, 30, 50}
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

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _ensure_not_last_full_admin_removal(db: AsyncSession, user_id: int, new_slugs: list[str]) -> None:
    current = await get_user_role_slugs(db, user_id)
    if user_has_super_admin_access(current) and not user_has_super_admin_access(new_slugs):
        if await count_full_administrators(db) <= 1:
            raise HTTPException(400, detail="Cannot demote the last Full Administrator account")


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
    base_url = (body.base_url or "").strip() or None
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
        except Exception as exc:
            sync_error = str(exc)[:300]
    await db.commit()
    return {"id": conn.id, "synced": synced, "sync_error": sync_error}


@router.get("/connections")
async def list_connections(db: AsyncSession = Depends(get_db), _: User = Depends(require_connections)):
    rows = (await db.execute(select(Connection).order_by(Connection.id.desc()))).scalars().all()
    usage_map: dict[int, float] = {}
    try:
        usage_q = (
            select(AIModel.connection_id, func.coalesce(func.sum(RequestLog.total_cost_usd), 0.0))
            .select_from(RequestLog)
            .join(AIModel, RequestLog.model_id == AIModel.external_id)
            .group_by(AIModel.connection_id)
        )
        usage_map = {r[0]: float(r[1]) for r in (await db.execute(usage_q)).all()}
    except Exception:
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
        await db.execute(delete(AIModel))
        await db.commit()
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
    return [
        {
            "id": m.id,
            "external_id": m.external_id,
            "display_name": m.display_name,
            "enabled": m.is_enabled,
            "input_cost_per_1k": m.input_cost_per_1k,
            "output_cost_per_1k": m.output_cost_per_1k,
            "total_cost_per_1k": (m.input_cost_per_1k or 0) + (m.output_cost_per_1k or 0),
            "provider": m.provider_type,
            "is_image_model": bool(m.is_image_model),
            "kinds": model_kinds(
                external_id=m.external_id,
                is_image_model=bool(m.is_image_model),
                pricing_raw=m.pricing_raw,
            ),
            **model_catalog_meta(
                external_id=m.external_id,
                display_name=m.display_name,
                pricing_raw=m.pricing_raw,
                context_length=m.context_length,
            ),
        }
        for m in rows
    ]


@router.patch("/models/{model_id}/toggle")
async def toggle_model(model_id: int, enabled: bool, db: AsyncSession = Depends(get_db), _: User = Depends(require_models_write)):
    m = await db.get(AIModel, model_id)
    if not m:
        raise HTTPException(404)
    m.is_enabled = enabled
    await db.commit()
    return {"ok": True}


class BulkModelsIn(BaseModel):
    ids: list[int]


@router.post("/models/bulk")
async def bulk_models(
    body: BulkModelsIn,
    action: str = Query(..., pattern="^(on|off|delete)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_models_write),
):
    if not body.ids:
        raise HTTPException(status_code=400, detail="No models selected")
    ids = list(dict.fromkeys(body.ids))
    if action == "delete":
        result = await db.execute(delete(AIModel).where(AIModel.id.in_(ids)))
        await db.commit()
        return {"ok": True, "count": result.rowcount or 0}
    enabled = action == "on"
    rows = (await db.execute(select(AIModel).where(AIModel.id.in_(ids)))).scalars().all()
    for m in rows:
        m.is_enabled = enabled
    await db.commit()
    return {"ok": True, "count": len(rows)}


class ApiKeyCreate(BaseModel):
    name: str
    owner_user_id: int
    credit_limit_usd: float = 0
    reset_period: Literal["daily", "weekly", "monthly"] = "monthly"
    expiration_days: int | None = None


class ApiKeyPatch(BaseModel):
    name: str | None = None
    owner_user_id: int | None = None
    credit_limit_usd: float | None = None
    reset_period: Literal["daily", "weekly", "monthly"] | None = None
    expiration_days: int | None = None
    expiration_never: bool | None = None


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
    raw, prefix, key_hash = generate_api_key()
    now = datetime.utcnow()
    expires_at = compute_expires_at(now, body.expiration_days)
    row = AlphaRouterApiKey(
        name=body.name.strip(),
        key_prefix=prefix,
        key_hash=key_hash,
        owner_user_id=body.owner_user_id,
        credit_limit_usd=float(body.credit_limit_usd),
        reset_period=body.reset_period,
        expires_at=expires_at,
        period_started_at=now,
        period_used_usd=0.0,
        total_used_usd=0.0,
    )
    db.add(row)
    await db.flush()
    await log_api_key_created(db, key=row, actor=admin, owner=owner)
    await db.commit()
    await db.refresh(row)
    return {
        "name": row.name,
        "api_key": raw,
        "url": f"{__import__('app.config', fromlist=['get_settings']).get_settings().api_public_url}/v1",
        "key": key_to_dict(row, {"email": owner.email, "username": owner.username, "display_name": owner.display_name}),
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
    department: str | None = None
    job_title: str | None = None
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
async def create_local_user(body: LocalUserIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_users_write)):
    exists = (await db.execute(select(User).where(User.username == body.username))).scalars().first()
    if exists:
        raise HTTPException(400, "Username already exists")
    plan_selected = sum([body.no_plan, body.inherit_group_plan, body.plan_id is not None])
    if plan_selected > 1:
        raise HTTPException(400, detail="Specify only one of plan_id, no_plan, or inherit_group_plan")
    from app.services.password_policy import PasswordPolicyError, validate_password

    try:
        password = validate_password(body.password)
    except PasswordPolicyError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    user = User(
        username=body.username,
        email=body.email,
        display_name=body.display_name or body.username,
        hashed_password=hash_password(password),
        role=_normalize_role(body.role),
        auth_provider="local",
        department=body.department,
        job_title=body.job_title,
    )
    db.add(user)
    await db.flush()
    await set_user_roles(db, user, [_normalize_role(body.role)])
    if body.group_id is not None:
        group = await db.get(UserGroup, body.group_id)
        if not group:
            raise HTTPException(404, detail="Group not found")
        if group.source != "local":
            raise HTTPException(400, detail="Only local groups can be assigned when creating a local user")
        await db.execute(
            insert(user_group_members).values(user_id=user.id, group_id=body.group_id)
        )
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
        stmt = stmt.where(User.role == role.strip().lower())
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
    user_id: int | None = Query(None),
    picker: bool = Query(False, description="Owner picker: search-only, no full list"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users),
):
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
            active_only=True,
        )
        users = (await db.execute(stmt)).scalars().all()
    user_ids = [u.id for u in users]
    plan_state = await _build_user_plan_state_map(db, user_ids)
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
    from app.services.budget_service import resolve_inherited_plans_batch, resolve_monthly_budgets_batch

    budgets = await resolve_monthly_budgets_batch(db, users)
    inherited_plans = await resolve_inherited_plans_batch(db, users)
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
            "department": u.department,
            "job_title": u.job_title,
            "office": u.office,
            "reporting_to": u.reporting_to,
            "monthly_budget_usd": budgets.get(u.id, 0.0),
            "budget_used_usd": u.budget_used_usd,
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
        }
        for u in users
    ]


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
        conn.base_url = (body.base_url or "").strip() or None
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
    if patches:
        touch_connection_modified(conn)
        await log_connection_updated(db, conn=conn, actor=admin, before=before, after_patches=patches)
    await db.commit()
    return {"ok": True}


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_connections_write)):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404)
    # Explicit cleanup for DBs/environments where FK cascade may be disabled.
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
        await db.execute(
            stmt.order_by(AlphaRouterApiKey.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    owner_ids = {k.owner_user_id for k in rows if k.owner_user_id}
    owners: dict[int, User] = {}
    if owner_ids:
        owner_rows = (await db.execute(select(User).where(User.id.in_(owner_ids)))).scalars().all()
        owners = {u.id: u for u in owner_rows}

    items = []
    for k in rows:
        u = owners.get(k.owner_user_id) if k.owner_user_id else None
        owner_info = (
            {"email": u.email, "username": u.username, "display_name": u.display_name} if u else None
        )
        apply_expiration(k)
        await maybe_reset_key_period(db, k)
        items.append(key_to_dict(k, owner_info))
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

    before = {
        "name": k.name,
        "owner_user_id": k.owner_user_id,
        "credit_limit_usd": k.credit_limit_usd,
        "reset_period": k.reset_period,
        "expires_at": k.expires_at,
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

    if patches:
        touch_key_modified(k)
        await log_api_key_updated(db, key=k, actor=admin, before=before, after_patches=patches)
    await db.commit()
    return {"ok": True}


@router.delete("/api-keys/{key_id}")
async def delete_alpha_router_key(key_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_api_keys_write)):
    k = await db.get(AlphaRouterApiKey, key_id)
    if not k:
        raise HTTPException(404)
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
        "department": user.department,
        "job_title": user.job_title,
        "office": user.office,
        "reporting_to": user.reporting_to,
        "monthly_budget_usd": monthly_budget_usd if monthly_budget_usd is not None else user.monthly_budget_usd,
        "budget_used_usd": user.budget_used_usd,
    }


class UserAdminPatch(BaseModel):
    username: str | None = None
    email: str | None = None
    display_name: str | None = None
    role: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
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
    _: User = Depends(require_users_write),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    if body.username is not None:
        clash = (
            await db.execute(select(User).where(User.username == body.username, User.id != user_id))
        ).scalars().first()
        if clash:
            raise HTTPException(400, "Username already taken")
        user.username = body.username.strip()
    if body.email is not None:
        email = _clean_optional_str(body.email)
        if email:
            clash = (
                await db.execute(select(User).where(User.email == email, User.id != user_id))
            ).scalars().first()
            if clash:
                raise HTTPException(400, "Email already in use")
        user.email = email
    if body.display_name is not None:
        user.display_name = _clean_optional_str(body.display_name)
    if body.roles is not None:
        new_slugs = [_normalize_role(s) for s in body.roles] if body.roles else ["user"]
        await _ensure_not_last_full_admin_removal(db, user.id, new_slugs)
        saved_roles = await set_user_roles(db, user, new_slugs)
    elif body.role is not None:
        new_role = _normalize_role(body.role)
        await _ensure_not_last_full_admin_removal(db, user.id, [new_role])
        saved_roles = await set_user_roles(db, user, [new_role])
    else:
        saved_roles = await get_user_role_slugs(db, user.id)
    if body.department is not None:
        user.department = _clean_optional_str(body.department)
    if body.office is not None:
        user.office = _clean_optional_str(body.office)
    if body.job_title is not None:
        user.job_title = _clean_optional_str(body.job_title)
    if body.reporting_to is not None:
        user.reporting_to = _clean_optional_str(body.reporting_to)
    if body.is_active is not None and user.is_active != body.is_active:
        if not body.is_active and await user_has_full_administrator(db, user.id):
            if await count_active_full_administrators(db) <= 1:
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
async def bulk_update_users(
    body: UsersBulkIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
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
                    await db.execute(
                        insert(user_group_members).values(user_id=uid, group_id=body.group_id)
                    )
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
    if await user_has_full_administrator(db, user.id):
        if await count_full_administrators(db) <= 1:
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
            select(UserApiKey, User)
            .join(User, UserApiKey.user_id == User.id)
            .order_by(UserApiKey.created_at.desc())
        )
    ).all()
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.key_prefix,
            "is_active": k.is_active,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "user_id": u.id,
            "username": u.username,
            "role": u.role,
            "email": u.email,
            "monthly_budget_usd": u.monthly_budget_usd,
            "budget_used_usd": u.budget_used_usd,
        }
        for k, u in rows
    ]


@router.delete("/user-api-keys/{key_id}")
async def delete_user_api_key(key_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_users_write)):
    from app.models.api_key import UserApiKey

    k = await db.get(UserApiKey, key_id)
    if not k:
        raise HTTPException(404)
    await db.delete(k)
    await db.commit()
    return {"ok": True}


@router.get("/dashboard/error-rates")
async def model_error_rates(period: str = "month", db: AsyncSession = Depends(get_db), _: User = Depends(require_dashboard)):
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
    user.budget_used_usd = 0.0
    user.budget_reserved_usd = 0.0
    await db.execute(
        update(BudgetReservation)
        .where(
            BudgetReservation.subject_type == "user",
            BudgetReservation.subject_id == user_id,
            BudgetReservation.status == "held",
        )
        .values(status="released", settled_at=datetime.utcnow())
    )
    user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await db.flush()
    return {"ok": True, "budget_used_usd": 0.0}


@router.post("/users/{user_id}/api-keys")
async def create_user_api_key_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users_write),
):
    from app.config import get_settings
    from app.models.api_key import UserApiKey

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    email_local = (user.email or user.username or "user").split("@")[0]
    raw, prefix, key_hash = generate_api_key_for_user(email_local)
    db.add(
        UserApiKey(
            user_id=user.id,
            name=f"{email_local}-key",
            key_prefix=prefix,
            key_hash=key_hash,
        )
    )
    await db.flush()
    s = get_settings()
    return {"api_key": raw, "url": f"{s.api_public_url}/v1", "prefix": prefix}


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
    connection_id: int | None = None,
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
    if connection_id is not None:
        model_ids = (
            await db.execute(select(AIModel.external_id).where(AIModel.connection_id == connection_id))
        ).scalars().all()
        if not model_ids:
            return []
        q = q.where(RequestLog.model_id.in_(list(model_ids)))
    return (await db.execute(q.order_by(RequestLog.request_time.asc()))).scalars().all()


def _activity_query_filters(
    *,
    model_id: str | None,
    username: str | None,
    app: str | None,
    response_status: str | None,
) -> dict:
    return {
        "model_id": (model_id or "").strip() or None,
        "username": (username or "").strip() or None,
        "app": (app or "").strip() or None,
        "response_status": response_status if response_status in ("success", "fail") else None,
    }


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
    )
    provider_map, key_map = await resolve_log_export_maps(db, rows)
    df = request_logs_to_export_dataframe(
        rows,
        tz_mode=timezone,
        provider_map=provider_map,
        key_map=key_map,
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
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_dashboard),
):
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"
    filters = _activity_query_filters(
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
    )
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
    )
    options = activity_service.filter_options(options_rows, group_by)
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
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_dashboard),
    jwt_token: str = Depends(get_bearer_token),
):
    filters = _activity_query_filters(
        model_id=model_id,
        username=username,
        app=app,
        response_status=response_status,
    )
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-activity-{period}-{group_by}",
        scope="service",
        jwt_token=jwt_token,
        user_role=admin.role,
        period=period,
        prompts_period=prompts_period,
        group_by=group_by,
        timezone=timezone,
        filters=filters,
    )


@router.get("/users/{user_id}/activity")
async def user_activity(
    user_id: int,
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_users),
):
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, detail="User not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
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
        group_by="model",
        timezone=timezone,
        filters=filters,
        user_id=user_id,
    )
    options = activity_service.filter_options(options_rows, "model")
    payload = activity_service.build_activity_payload(
        rows,
        period=period,
        since=since,
        group_by="model",
        timezone=timezone,
        now=now,
        prev_rows=prev_rows,
        heatmap_rows=heatmap_rows,
    )
    prompts_card = activity_service.build_prompts_card(
        prompts_rows,
        period=pp,
        since=since_prompts,
        group_by="model",
        timezone=timezone,
        now=now,
        prev_rows=prompts_prev_rows,
        heatmap_rows=heatmap_rows,
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
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_api_keys),
):
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"
    key = await db.get(AlphaRouterApiKey, key_id)
    if not key:
        raise HTTPException(404, detail="API key not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
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
        group_by="model",
        timezone=timezone,
        filters=filters,
        alpha_router_api_key_id=key_id,
    )
    options = activity_service.filter_options(options_rows, "model")
    payload = activity_service.build_activity_payload(
        rows,
        period=period,
        since=since,
        group_by="model",
        timezone=timezone,
        now=now,
        prev_rows=prev_rows,
        heatmap_rows=heatmap_rows,
    )
    prompts_card = activity_service.build_prompts_card(
        prompts_rows,
        period=pp,
        since=since_prompts,
        group_by="model",
        timezone=timezone,
        now=now,
        prev_rows=prompts_prev_rows,
        heatmap_rows=heatmap_rows,
    )
    changelog = await fetch_api_key_changelog(db, key_id)  # full log on activity payload
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
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_api_keys),
    jwt_token: str = Depends(get_bearer_token),
):
    key = await db.get(AlphaRouterApiKey, key_id)
    if not key:
        raise HTTPException(404, detail="API key not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-api-key-{key_id}-activity-{period}",
        scope="api_key",
        jwt_token=jwt_token,
        user_role=admin.role,
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
    except ValueError:
        raise HTTPException(400, detail="Invalid date; use YYYY-MM-DD")


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
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_connections),
):
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404, detail="Connection not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
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
        group_by="model",
        timezone=timezone,
        filters=filters,
        connection_id=conn_id,
    )
    options = activity_service.filter_options(options_rows, "model")
    payload = activity_service.build_activity_payload(
        rows,
        period=period,
        since=since,
        group_by="model",
        timezone=timezone,
        now=now,
        prev_rows=prev_rows,
        heatmap_rows=heatmap_rows,
    )
    prompts_card = activity_service.build_prompts_card(
        prompts_rows,
        period=pp,
        since=since_prompts,
        group_by="model",
        timezone=timezone,
        now=now,
        prev_rows=prompts_prev_rows,
        heatmap_rows=heatmap_rows,
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
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_connections),
    jwt_token: str = Depends(get_bearer_token),
):
    conn = await db.get(Connection, conn_id)
    if not conn:
        raise HTTPException(404, detail="Connection not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-connection-{conn_id}-activity-{period}",
        scope="connection",
        jwt_token=jwt_token,
        user_role=admin.role,
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
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_users),
    jwt_token: str = Depends(get_bearer_token),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, detail="User not found")
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"alpha-router-user-{user_id}-activity-{period}",
        scope="user",
        jwt_token=jwt_token,
        user_role=admin.role,
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
            select(MediaAsset.kind, func.count(MediaAsset.id), func.coalesce(func.sum(MediaAsset.size_bytes), 0))
            .group_by(MediaAsset.kind)
        )
    ).all()
    stats["by_kind"] = [
        {"kind": r[0], "count": int(r[1] or 0), "size_bytes": int(r[2] or 0)}
        for r in by_kind_rows
    ]
    stats["chat"] = {
        "stats": await chat_retention_stats(db),
        "settings": await get_chat_retention_settings(db),
    }
    quota_gb = await get_user_media_quota_gb(db)
    stats["settings"]["user_media_quota_gb"] = quota_gb
    stats["settings"]["user_media_quota_bytes"] = await get_user_media_quota_bytes(db)
    stats["users_over_quota"] = await count_users_over_media_quota(db)
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
        settings = {**settings, "user_media_quota_gb": quota_gb, "user_media_quota_bytes": quota_gb * 1024 * 1024 * 1024}
    await db.commit()
    await refresh_storage_cleanup_schedule()
    return {"ok": True, "settings": settings}


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


@router.post("/storage/clear-cache")
async def admin_clear_storage_cache(db: AsyncSession = Depends(get_db), _: User = Depends(require_storage_write)):
    result = await clear_all_media(db)
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
