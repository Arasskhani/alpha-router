"""Budget plans CRUD and assignments."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_plans, require_plans_write
from app.database import get_db
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.user import User, UserGroup
from app.services.plan_assignment_service import (
    assign_plan_to_group_members,
    upsert_user_plan,
)

router = APIRouter(prefix="/api/admin/plans", tags=["plans"])


class PlanIn(BaseModel):
    name: str
    monthly_budget_usd: float


class PlanPatch(BaseModel):
    name: str | None = None
    monthly_budget_usd: float | None = None


class AssignIn(BaseModel):
    plan_id: int
    user_id: int | None = None
    group_id: int | None = None
    department: str | None = None


class AssignUsersIn(BaseModel):
    plan_id: int
    user_ids: list[int]


class AssignDepartmentIn(BaseModel):
    plan_id: int
    department: str


@router.post("")
async def create_plan(body: PlanIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_plans_write)):
    plan = BudgetPlan(
        name=body.name,
        monthly_budget_usd=body.monthly_budget_usd,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return {"id": plan.id}


@router.get("")
async def list_plans(db: AsyncSession = Depends(get_db), _: User = Depends(require_plans)):
    plans = (await db.execute(select(BudgetPlan).order_by(BudgetPlan.name))).scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "monthly_budget_usd": p.monthly_budget_usd,
        }
        for p in plans
    ]


@router.get("/departments")
async def list_departments(db: AsyncSession = Depends(get_db), _: User = Depends(require_plans)):
    """Distinct department names from users and plan assignments, with user counts."""
    user_rows = (
        await db.execute(
            select(User.department, func.count())
            .where(User.department.isnot(None), User.department != "")
            .group_by(User.department)
        )
    ).all()
    by_name: dict[str, int] = {}
    for dept, count in user_rows:
        if dept is None:
            continue
        name = str(dept).strip()
        if not name:
            continue
        by_name[name] = by_name.get(name, 0) + int(count)

    assign_rows = (
        await db.execute(
            select(PlanAssignment.department)
            .where(PlanAssignment.department.isnot(None), PlanAssignment.department != "")
            .distinct()
        )
    ).all()
    for (dept,) in assign_rows:
        if dept is None:
            continue
        name = str(dept).strip()
        if not name:
            continue
        by_name.setdefault(name, 0)

    return [{"name": name, "user_count": count} for name, count in sorted(by_name.items(), key=lambda x: x[0].lower())]


@router.get("/{plan_id}/members")
async def plan_members(plan_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_plans)):

    plan = await db.get(BudgetPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    assigns = (await db.execute(select(PlanAssignment).where(PlanAssignment.plan_id == plan_id))).scalars().all()

    user_ids = {a.user_id for a in assigns if a.user_id}
    group_ids = {a.group_id for a in assigns if a.group_id}
    users_by_id: dict[int, User] = {}
    groups_by_id: dict[int, UserGroup] = {}
    if user_ids:
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        users_by_id = {u.id: u for u in users}
    if group_ids:
        groups = (await db.execute(select(UserGroup).where(UserGroup.id.in_(group_ids)))).scalars().all()
        groups_by_id = {g.id: g for g in groups}

    member_counts: dict[int, int] = {}
    if group_ids:
        from app.services.group_membership import live_member_counts_stmt

        count_rows = (await db.execute(live_member_counts_stmt(group_ids))).all()
        member_counts = {int(gid): int(cnt) for gid, cnt in count_rows}

    users_out = []
    groups_out = []
    departments_out: list[str] = []
    for a in assigns:
        if a.user_id and a.plan_id and a.user_id in users_by_id:
            u = users_by_id[a.user_id]
            users_out.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "email": u.email,
                }
            )
        elif a.group_id and a.group_id in groups_by_id:
            g = groups_by_id[a.group_id]
            groups_out.append(
                {
                    "id": g.id,
                    "name": g.name,
                    "source": g.source,
                    "member_count": member_counts.get(g.id, 0),
                }
            )
        elif a.department:
            departments_out.append(a.department)

    users_out.sort(key=lambda x: (x.get("display_name") or x["username"]).lower())
    groups_out.sort(key=lambda x: x["name"].lower())
    departments_out.sort()

    return {
        "plan": {"id": plan.id, "name": plan.name, "monthly_budget_usd": plan.monthly_budget_usd},
        "users": users_out,
        "groups": groups_out,
        "departments": departments_out,
    }


@router.post("/assign")
async def assign_plan(body: AssignIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_plans_write)):
    if body.group_id and not body.user_id and not body.department:
        result = await assign_plan_to_group_members(db, body.plan_id, body.group_id)
        await db.commit()
        return {"ok": True, **result}
    if body.user_id and not body.group_id and not body.department:
        await upsert_user_plan(db, body.user_id, body.plan_id)
        await db.commit()
        return {"ok": True}
    if body.department and not body.user_id and not body.group_id:
        existing = (
            (
                await db.execute(
                    select(PlanAssignment).where(
                        PlanAssignment.plan_id == body.plan_id,
                        PlanAssignment.department == body.department,
                    )
                )
            )
            .scalars()
            .first()
        )
        if not existing:
            db.add(PlanAssignment(plan_id=body.plan_id, department=body.department))
        await db.commit()
        return {"ok": True}
    raise HTTPException(400, "Specify exactly one of user_id, group_id, or department")


@router.post("/assign-users")
async def assign_users(body: AssignUsersIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_plans_write)):
    for uid in body.user_ids:
        await upsert_user_plan(db, uid, body.plan_id)
    await db.commit()
    return {"ok": True, "count": len(body.user_ids)}


@router.post("/assign-department")
async def assign_department(
    body: AssignDepartmentIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_plans_write),
):
    existing = (
        (
            await db.execute(
                select(PlanAssignment).where(
                    PlanAssignment.plan_id == body.plan_id,
                    PlanAssignment.department == body.department,
                )
            )
        )
        .scalars()
        .first()
    )
    if existing:
        return {"ok": True}
    db.add(PlanAssignment(plan_id=body.plan_id, department=body.department))
    await db.commit()
    return {"ok": True}


@router.delete("/{plan_id}")
async def delete_plan(plan_id: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_plans_write)):
    plan = await db.get(BudgetPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    await db.execute(delete(PlanAssignment).where(PlanAssignment.plan_id == plan_id))
    await db.delete(plan)
    await db.commit()
    return {"ok": True}


@router.patch("/{plan_id}")
async def update_plan(
    plan_id: int,
    body: PlanPatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_plans_write),
):
    plan = await db.get(BudgetPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    if body.name is not None:
        next_name = body.name.strip()
        if not next_name:
            raise HTTPException(400, "Plan name cannot be empty")
        clash = (
            (await db.execute(select(BudgetPlan).where(BudgetPlan.name == next_name, BudgetPlan.id != plan_id)))
            .scalars()
            .first()
        )
        if clash:
            raise HTTPException(400, "Plan name already exists")
        plan.name = next_name
    if body.monthly_budget_usd is not None:
        plan.monthly_budget_usd = body.monthly_budget_usd
    await db.commit()
    await db.refresh(plan)
    return {
        "id": plan.id,
        "name": plan.name,
        "monthly_budget_usd": plan.monthly_budget_usd,
    }
