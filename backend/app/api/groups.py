"""Groups: local, LDAP, and Keycloak."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import _activity_export_response, _activity_query_filters
from app.api.deps import get_bearer_token, require_groups, require_groups_write
from app.services.rbac import is_admin_panel_role
from app.database import get_db
from app.models.budget import PlanAssignment
from app.models.user import User, UserGroup, user_group_members
from app.services import activity_service
from app.services.auth_config import get_provider_config
from app.services.keycloak_sync import fetch_keycloak_groups
from app.services.ldap_auth import fetch_ldap_groups

router = APIRouter(prefix="/api/admin/groups", tags=["groups"])


class GroupIn(BaseModel):
    name: str
    description: str | None = None
    plan_id: int | None = None


class GroupUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    plan_id: int | None = None
    clear_plan: bool = False


class PlanAssignGroup(BaseModel):
    plan_id: int | None = None
    clear_plan: bool = False


def _clean_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s if s else None


async def _ensure_unique_local_group_name(
    db: AsyncSession, name: str, *, exclude_id: int | None = None
) -> None:
    stmt = select(UserGroup).where(UserGroup.source == "local", UserGroup.name == name)
    if exclude_id is not None:
        stmt = stmt.where(UserGroup.id != exclude_id)
    if (await db.execute(stmt)).scalars().first():
        raise HTTPException(400, detail="A local group with this name already exists")


@router.get("")
async def list_groups(
    q: str | None = None,
    source: str | None = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_groups),
):
    stmt = select(UserGroup).order_by(UserGroup.source, UserGroup.name)
    if source:
        stmt = stmt.where(UserGroup.source == source)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(UserGroup.name.ilike(like), UserGroup.description.ilike(like)))
    groups = (await db.execute(stmt)).scalars().all()
    result = []
    for g in groups:
        pa = (
            await db.execute(select(PlanAssignment).where(PlanAssignment.group_id == g.id))
        ).scalars().first()
        result.append(
            {
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "source": g.source,
                "external_id": g.external_id,
                "plan_id": pa.plan_id if pa else None,
            }
        )
    return result


@router.post("")
async def create_local_group(body: GroupIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_groups_write)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, detail="Name is required")
    await _ensure_unique_local_group_name(db, name)
    g = UserGroup(
        name=name,
        description=_clean_optional_str(body.description),
        source="local",
    )
    db.add(g)
    await db.flush()
    if body.plan_id is not None:
        from app.services.plan_assignment_service import assign_plan_to_group_members

        await assign_plan_to_group_members(db, body.plan_id, g.id)
    await db.commit()
    await db.refresh(g)
    return {"id": g.id}


@router.post("/sync/ldap")
async def sync_ldap_groups(db: AsyncSession = Depends(get_db), _: User = Depends(require_groups_write)):
    cfg = await get_provider_config(db, "ldap")
    if not cfg.get("enabled"):
        raise HTTPException(400, "LDAP is not enabled")
    try:
        items = await asyncio.to_thread(fetch_ldap_groups, cfg)
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    count = 0
    for item in items:
        existing = (
            await db.execute(
                select(UserGroup).where(
                    UserGroup.source == "ldap",
                    UserGroup.external_id == item["external_id"],
                )
            )
        ).scalars().first()
        if existing:
            existing.name = item["name"]
            existing.description = item.get("description")
        else:
            db.add(
                UserGroup(
                    name=item["name"],
                    description=item.get("description"),
                    source="ldap",
                    external_id=item["external_id"],
                )
            )
            count += 1
    await db.commit()
    return {"synced_new": count, "total": len(items)}


@router.post("/sync/keycloak")
async def sync_keycloak_groups(db: AsyncSession = Depends(get_db), _: User = Depends(require_groups_write)):
    cfg = await get_provider_config(db, "keycloak")
    if not cfg.get("enabled"):
        raise HTTPException(400, "Keycloak is not enabled")
    items = await fetch_keycloak_groups(cfg)
    count = 0
    for item in items:
        existing = (
            await db.execute(
                select(UserGroup).where(
                    UserGroup.source == "keycloak",
                    UserGroup.external_id == item["external_id"],
                )
            )
        ).scalars().first()
        if existing:
            existing.name = item["name"]
            existing.description = item.get("description")
        else:
            db.add(
                UserGroup(
                    name=item["name"],
                    description=item.get("description"),
                    source="keycloak",
                    external_id=item["external_id"],
                )
            )
            count += 1
    await db.commit()
    return {"synced_new": count, "total": len(items)}


@router.patch("/{group_id}/plan")
async def assign_plan_to_group(
    group_id: int,
    body: PlanAssignGroup,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_groups_write),
):
    from app.services.plan_assignment_service import assign_plan_to_group_members, clear_group_plan

    if body.clear_plan and body.plan_id is not None:
        raise HTTPException(400, detail="Specify only one of plan_id or clear_plan")
    if body.clear_plan:
        result = await clear_group_plan(db, group_id)
    elif body.plan_id is not None:
        result = await assign_plan_to_group_members(db, body.plan_id, group_id)
    else:
        raise HTTPException(400, detail="plan_id or clear_plan is required")
    await db.commit()
    return {"ok": True, **result}


@router.patch("/{group_id}")
async def update_local_group(
    group_id: int,
    body: GroupUpdateIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_groups_write),
):
    from app.services.plan_assignment_service import assign_plan_to_group_members, clear_group_plan

    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(404, detail="Group not found")
    if group.source != "local":
        raise HTTPException(403, detail="Only local groups can be edited")

    if body.clear_plan and body.plan_id is not None:
        raise HTTPException(400, detail="Specify only one of plan_id or clear_plan")

    has_meta = body.name is not None or body.description is not None
    has_plan = body.plan_id is not None or body.clear_plan
    if not has_meta and not has_plan:
        raise HTTPException(400, detail="No changes provided")

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, detail="Name is required")
        await _ensure_unique_local_group_name(db, name, exclude_id=group_id)
        group.name = name
    if body.description is not None:
        group.description = _clean_optional_str(body.description)

    if body.clear_plan:
        await clear_group_plan(db, group_id)
    elif body.plan_id is not None:
        await assign_plan_to_group_members(db, body.plan_id, group_id)

    await db.commit()
    await db.refresh(group)
    pa = (
        await db.execute(select(PlanAssignment).where(PlanAssignment.group_id == group.id))
    ).scalars().first()
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "source": group.source,
        "plan_id": pa.plan_id if pa else None,
    }


async def _group_member_ids(db: AsyncSession, group_id: int) -> list[int]:
    rows = (
        await db.execute(select(user_group_members.c.user_id).where(user_group_members.c.group_id == group_id))
    ).all()
    return [int(r[0]) for r in rows if r[0] is not None]


@router.get("/{group_id}/activity")
async def group_activity(
    group_id: int,
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_groups),
):
    from app.api.admin import _activity_query_filters, _load_activity_context

    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(404, detail="Group not found")
    member_ids = await _group_member_ids(db, group_id)
    pp = prompts_period or ("day" if period not in ("day", "week", "month") else period)
    if pp not in ("day", "week", "month"):
        pp = "week"
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
        user_ids=member_ids,
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
        "group": {
            "id": group.id,
            "name": group.name,
            "member_count": len(member_ids),
        },
        "scope": "group",
        "model_id": filters["model_id"],
        "filters": filters,
    }


@router.get("/{group_id}/activity/export")
async def group_activity_export(
    group_id: int,
    format: str = Query("csv", pattern="^(csv|pdf)$"),
    period: str = Query("day", pattern=activity_service.ACTIVITY_PERIOD_PATTERN),
    prompts_period: str | None = Query(None, pattern=activity_service.PROMPTS_PERIOD_PATTERN),
    model_id: str | None = Query(None, max_length=256),
    timezone: str = Query("local", pattern="^(local|utc)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_groups),
    jwt_token: str = Depends(get_bearer_token),
):
    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(404, detail="Group not found")
    member_ids = await _group_member_ids(db, group_id)
    filters = _activity_query_filters(model_id=model_id, username=None, app=None, response_status=None)
    return await _activity_export_response(
        db,
        format=format,
        filename_stem=f"nitro-group-{group_id}-activity-{period}",
        scope="group",
        jwt_token=jwt_token,
        user_role=admin.role,
        period=period,
        prompts_period=prompts_period,
        group_by="model",
        timezone=timezone,
        filters=filters,
        user_ids=member_ids,
        group_id=group_id,
    )


@router.post("/{group_id}/disable-members")
async def disable_group_members(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_groups_write),
):
    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(404, detail="Group not found")
    member_ids = await _group_member_ids(db, group_id)
    if not member_ids:
        return {"ok": True, "disabled": 0, "skipped_admins": 0}
    users = (await db.execute(select(User).where(User.id.in_(member_ids)))).scalars().all()
    disabled = 0
    skipped_admins = 0
    for u in users:
        if is_admin_panel_role(u.role):
            skipped_admins += 1
            continue
        if u.is_active:
            u.is_active = False
            disabled += 1
    await db.commit()
    return {"ok": True, "disabled": disabled, "skipped_admins": skipped_admins}


class GroupsBulkIn(BaseModel):
    group_ids: list[int]
    action: Literal["assign_plan", "delete", "disable_members"]
    plan_id: int | None = None


@router.post("/bulk")
async def bulk_update_groups(
    body: GroupsBulkIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_groups_write),
):
    if not body.group_ids:
        raise HTTPException(400, detail="No groups selected")
    groups = (await db.execute(select(UserGroup).where(UserGroup.id.in_(body.group_ids)))).scalars().all()
    if len(groups) != len(set(body.group_ids)):
        raise HTTPException(404, detail="One or more groups not found")

    if body.action == "assign_plan":
        if not body.plan_id:
            raise HTTPException(400, detail="plan_id is required")
        from app.services.plan_assignment_service import assign_plan_to_group_members

        assigned = 0
        for group in groups:
            await assign_plan_to_group_members(db, body.plan_id, group.id)
            assigned += 1
        await db.commit()
        return {"ok": True, "groups": assigned}

    if body.action == "disable_members":
        disabled_total = 0
        skipped_admins = 0
        for group in groups:
            member_ids = await _group_member_ids(db, group.id)
            if not member_ids:
                continue
            users = (await db.execute(select(User).where(User.id.in_(member_ids)))).scalars().all()
            for u in users:
                if is_admin_panel_role(u.role):
                    skipped_admins += 1
                    continue
                if u.is_active:
                    u.is_active = False
                    disabled_total += 1
        await db.commit()
        return {"ok": True, "disabled": disabled_total, "skipped_admins": skipped_admins}

    if body.action == "delete":
        deleted = 0
        for group in groups:
            await db.execute(delete(PlanAssignment).where(PlanAssignment.group_id == group.id))
            await db.execute(delete(user_group_members).where(user_group_members.c.group_id == group.id))
            await db.delete(group)
            deleted += 1
        await db.commit()
        return {"ok": True, "deleted": deleted}

    raise HTTPException(400, detail="Unknown bulk action")


@router.delete("/{group_id}")
async def delete_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_groups_write),
):
    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(404, detail="Group not found")
    await db.execute(delete(PlanAssignment).where(PlanAssignment.group_id == group_id))
    await db.execute(delete(user_group_members).where(user_group_members.c.group_id == group_id))
    await db.delete(group)
    await db.commit()
    return {"ok": True}
