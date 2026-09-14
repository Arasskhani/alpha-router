"""Assign budget plans to users, groups, and departments."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPlan, PlanAssignment
from app.models.user import User, UserGroup, user_group_members
from app.services.budget_service import resolve_monthly_budget

USER_PLAN_INHERIT = "inherit"
USER_PLAN_NONE = "none"
USER_PLAN_ASSIGNED = "assigned"


async def get_user_direct_assignment(db: AsyncSession, user_id: int) -> PlanAssignment | None:
    return (await db.execute(select(PlanAssignment).where(PlanAssignment.user_id == user_id))).scalars().first()


def user_plan_mode(assignment: PlanAssignment | None) -> str:
    if assignment is None:
        return USER_PLAN_INHERIT
    if assignment.plan_id is None:
        return USER_PLAN_NONE
    return USER_PLAN_ASSIGNED


async def _member_user_ids(db: AsyncSession, group_id: int) -> list[int]:
    rows = (
        await db.execute(select(user_group_members.c.user_id).where(user_group_members.c.group_id == group_id))
    ).all()
    return [int(r[0]) for r in rows if r[0] is not None]


async def upsert_user_plan(db: AsyncSession, user_id: int, plan_id: int) -> None:
    """Direct plan on user — overrides group/department inheritance."""
    row = await get_user_direct_assignment(db, user_id)
    if row:
        row.plan_id = plan_id
        row.group_id = None
        row.department = None
    else:
        db.add(PlanAssignment(plan_id=plan_id, user_id=user_id))


async def upsert_user_no_plan(db: AsyncSession, user_id: int) -> None:
    """Explicit No Plan — blocks group/department inheritance."""
    row = await get_user_direct_assignment(db, user_id)
    if row:
        row.plan_id = None
        row.group_id = None
        row.department = None
    else:
        db.add(PlanAssignment(user_id=user_id, plan_id=None))


async def clear_user_plan_override(db: AsyncSession, user_id: int) -> None:
    """Remove user-level override so group/department plans apply."""
    await db.execute(delete(PlanAssignment).where(PlanAssignment.user_id == user_id))


async def upsert_group_plan(db: AsyncSession, group_id: int, plan_id: int) -> None:
    row = (await db.execute(select(PlanAssignment).where(PlanAssignment.group_id == group_id))).scalars().first()
    if row:
        row.plan_id = plan_id
        row.user_id = None
        row.department = None
    else:
        db.add(PlanAssignment(plan_id=plan_id, group_id=group_id))


async def assign_plan_to_group_members(db: AsyncSession, plan_id: int, group_id: int) -> dict[str, int]:
    """Assign plan to the group; members inherit unless they have a user-level override."""
    plan = await db.get(BudgetPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")

    await upsert_group_plan(db, group_id, plan_id)
    member_ids = await _member_user_ids(db, group_id)
    for uid in member_ids:
        user = await db.get(User, uid)
        if not user:
            continue
        if user_plan_mode(await get_user_direct_assignment(db, uid)) == USER_PLAN_INHERIT:
            user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await db.flush()
    return {"users_assigned": len(member_ids), "group_id": group_id}


async def clear_group_plan(db: AsyncSession, group_id: int) -> dict[str, int]:
    """Remove group plan assignment and refresh inheriting members' budgets."""
    group = await db.get(UserGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    await db.execute(delete(PlanAssignment).where(PlanAssignment.group_id == group_id))
    member_ids = await _member_user_ids(db, group_id)
    for uid in member_ids:
        user = await db.get(User, uid)
        if not user:
            continue
        if user_plan_mode(await get_user_direct_assignment(db, uid)) == USER_PLAN_INHERIT:
            user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await db.flush()
    return {"users_assigned": len(member_ids), "group_id": group_id}
