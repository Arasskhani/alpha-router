"""Feature Access: the admin page that turns the web Chat, Projects, creating projects, personal API
keys or the browser extension off for some people.

Under Chat experience, behind the same menu as Chat Tools: like a tool ACL it
decides who may use a part of the chat, and the same administrators keep it.

Every change is recorded with :func:`app.services.security_audit.log_security_event`
(``feature_access_rule_added`` / ``feature_access_rule_changed`` /
``feature_access_rule_removed``), so it shows in Admin Logs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import _owner_picker_payload, _query_owner_picker_users
from app.api.deps import require_chat_tools, require_chat_tools_write
from app.database import get_db
from app.models.feature_access import FEATURES, FeatureAccessRule
from app.models.user import User, UserGroup, user_group_members
from app.services.client_ip import resolve_client_ip
from app.services.feature_access_service import (
    FEATURE_TITLES,
    decide_all,
    normalize_department,
    validate_feature,
)
from app.services.security_audit import log_security_event

router = APIRouter(prefix="/api/admin/feature-access", tags=["feature-access"])


class RuleIn(BaseModel):
    feature: str = Field(pattern=r"^(chat|projects|project_create|api_keys|extension)$")
    target_type: str = Field(pattern=r"^(user|group|department)$")
    target: int | str
    effect: str = Field(default="deny", pattern=r"^(allow|deny)$")
    note: str | None = Field(default=None, max_length=500)


def _target_type(rule: FeatureAccessRule) -> str:
    if rule.user_id is not None:
        return "user"
    if rule.group_id is not None:
        return "group"
    return "department"


def _user_label(user: User | None, user_id: int) -> str:
    if user is None:
        return f"User #{user_id}"
    return str(user.display_name or user.username or user.email or f"User #{user_id}")


async def _rule_view(db: AsyncSession, rule: FeatureAccessRule) -> dict[str, Any]:
    kind = _target_type(rule)
    target: int | str
    sub: str | None = None
    if kind == "user":
        target = int(rule.user_id)
        found = await db.get(User, target)
        label = _user_label(found, target)
        sub = str(found.email or found.username) if found is not None else None
    elif kind == "group":
        target = int(rule.group_id)
        group = await db.get(UserGroup, target)
        label = str(group.name) if group is not None else f"Group #{target}"
    else:
        target = str(rule.department)
        label = target
    by = await db.get(User, int(rule.created_by_user_id)) if rule.created_by_user_id is not None else None
    return {
        "id": int(rule.id),
        "feature": str(rule.feature),
        "target_type": kind,
        "target": target,
        "label": label,
        "sublabel": sub,
        "effect": str(rule.effect),
        "note": rule.note,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "created_by": str(by.username) if by is not None else None,
    }


def _audit_view(view: dict[str, Any]) -> dict[str, Any]:
    """What goes in the trail: the decision, not row ids."""
    return {
        "feature": view["feature"],
        "target": f"{view['target_type']}:{view['target']}",
        "label": view["label"],
        "effect": view["effect"],
    }


@router.get("")
async def feature_access_overview(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_chat_tools),
) -> dict[str, Any]:
    """Every governed section with its rules, users first, then groups, then departments."""
    rows = (await db.execute(select(FeatureAccessRule).order_by(FeatureAccessRule.id))).scalars().all()
    order = {"user": 0, "group": 1, "department": 2}
    features: list[dict[str, Any]] = []
    for key in FEATURES:
        views = [await _rule_view(db, rule) for rule in rows if rule.feature == key]
        views.sort(key=lambda view: (order[view["target_type"]], str(view["label"]).casefold()))
        features.append(
            {
                "key": key,
                "title": FEATURE_TITLES[key],
                "rules": views,
                "deny_count": sum(1 for view in views if view["effect"] == "deny"),
                "allow_count": sum(1 for view in views if view["effect"] == "allow"),
            }
        )
    return {"features": features}


async def _resolve_target(db: AsyncSession, body: RuleIn) -> dict[str, Any]:
    if body.target_type in ("user", "group"):
        try:
            target_id = int(body.target)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Choose a user or group from the list.") from None
        if body.target_type == "user":
            found = await db.get(User, target_id)
            if found is None or found.deleted_at is not None:
                raise HTTPException(status_code=400, detail="That user does not exist.")
            return {"user_id": target_id}
        if await db.get(UserGroup, target_id) is None:
            raise HTTPException(status_code=400, detail="That group does not exist.")
        return {"group_id": target_id}
    department = " ".join(str(body.target or "").split())
    if not department:
        raise HTTPException(status_code=400, detail="Enter a department.")
    if len(department) > 255:
        raise HTTPException(status_code=400, detail="A department name is at most 255 characters.")
    return {"department": department}


async def _existing(db: AsyncSession, feature: str, target: dict[str, Any]) -> FeatureAccessRule | None:
    stmt = select(FeatureAccessRule).where(FeatureAccessRule.feature == feature)
    if "user_id" in target:
        stmt = stmt.where(FeatureAccessRule.user_id == target["user_id"])
    elif "group_id" in target:
        stmt = stmt.where(FeatureAccessRule.group_id == target["group_id"])
    else:
        rows = (await db.execute(stmt.where(FeatureAccessRule.department.is_not(None)))).scalars().all()
        wanted = normalize_department(target["department"])
        return next((row for row in rows if normalize_department(str(row.department)) == wanted), None)
    return (await db.execute(stmt)).scalar_one_or_none()


@router.post("/rules")
async def save_feature_access_rule(
    body: RuleIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_chat_tools_write),
) -> dict[str, Any]:
    """Add a rule, or change the effect and note of the one this subject already has."""
    if body.effect == "allow" and body.target_type != "user":
        raise HTTPException(
            status_code=400,
            detail="Allow is for one person. A section is open unless a rule closes it, so a group or "
            "department allow would change nothing.",
        )
    feature = validate_feature(body.feature)
    target = await _resolve_target(db, body)
    note = (body.note or "").strip() or None
    rule = await _existing(db, feature, target)
    before = _audit_view(await _rule_view(db, rule)) if rule is not None else None
    if rule is None:
        rule = FeatureAccessRule(feature=feature, effect=body.effect, note=note, created_by_user_id=actor.id, **target)
        db.add(rule)
        response.status_code = 201
    else:
        if str(rule.effect) == body.effect and (rule.note or None) == note:
            # Saved as it was: nothing changed, so nothing goes in the trail.
            return await _rule_view(db, rule)
        rule.effect = body.effect  # type: ignore[assignment]
        rule.note = note  # type: ignore[assignment]
    try:
        await db.flush()
    except IntegrityError:
        # Another administrator saved a rule for the same subject a moment ago.
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Someone saved a rule for this subject just now. Refresh the page and try again.",
        ) from None
    view = await _rule_view(db, rule)
    await log_security_event(
        db,
        actor=actor,
        actor_ip=resolve_client_ip(request),
        action="feature_access_rule_added" if before is None else "feature_access_rule_changed",
        resource_type="feature_access",
        resource_id=feature,
        detail={"before": before, "after": _audit_view(view)},
    )
    await db.commit()
    return view


@router.delete("/rules/{rule_id}")
async def remove_feature_access_rule(
    rule_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_chat_tools_write),
) -> dict[str, Any]:
    rule = await db.get(FeatureAccessRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    view = await _rule_view(db, rule)
    await db.delete(rule)
    await log_security_event(
        db,
        actor=actor,
        actor_ip=resolve_client_ip(request),
        action="feature_access_rule_removed",
        resource_type="feature_access",
        resource_id=view["feature"],
        detail={"before": _audit_view(view)},
    )
    await db.commit()
    return {"ok": True}


@router.get("/check")
async def check_feature_access(
    user_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_chat_tools),
) -> dict[str, Any]:
    """What one person gets, and which rule decided it."""
    found = await db.get(User, user_id)
    if found is None or found.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found.")
    decisions = await decide_all(db, found)
    return {
        "user": {
            "id": int(found.id),
            "label": _user_label(found, int(found.id)),
            "department": found.department,
        },
        "features": [decisions[key].as_dict() | {"title": FEATURE_TITLES[key]} for key in FEATURES],
    }


@router.get("/user-options")
async def feature_access_user_options(
    q: str | None = Query(None, max_length=200),
    user_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_chat_tools),
) -> list[dict[str, Any]]:
    """The user picker: recent users, or those matching ``q``."""
    return _owner_picker_payload(await _query_owner_picker_users(db, user_id=user_id, q=q))


@router.get("/options")
async def feature_access_target_options(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_chat_tools),
) -> dict[str, Any]:
    """The groups and departments a rule can name, with how many people each holds."""
    members = (
        select(user_group_members.c.group_id, func.count().label("n"))
        .group_by(user_group_members.c.group_id)
        .subquery()
    )
    group_rows = (
        await db.execute(
            select(UserGroup.id, UserGroup.name, UserGroup.source, members.c.n)
            .outerjoin(members, members.c.group_id == UserGroup.id)
            .order_by(UserGroup.name)
        )
    ).all()
    dept_rows = (
        await db.execute(
            select(User.department, func.count())
            .where(User.department.is_not(None), User.department != "", User.deleted_at.is_(None))
            .group_by(User.department)
        )
    ).all()
    departments: dict[str, dict[str, Any]] = {}
    for name, count in dept_rows:
        clean = " ".join(str(name).split())
        key = normalize_department(clean)
        if not key:
            continue
        entry = departments.setdefault(key, {"name": clean, "user_count": 0})
        entry["user_count"] += int(count)
    return {
        "groups": [
            {
                "id": int(row.id),
                "name": str(row.name),
                "source": str(row.source or "local"),
                "member_count": int(row.n or 0),
            }
            for row in group_rows
        ],
        "departments": sorted(departments.values(), key=lambda entry: str(entry["name"]).casefold()),
    }
