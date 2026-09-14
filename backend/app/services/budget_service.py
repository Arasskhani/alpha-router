"""Monthly budget resolution, usage aggregation, and calendar reset."""

import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPlan, PlanAssignment
from app.models.cost_accounting import LedgerEntry
from app.models.logging import RequestLog
from app.models.user import User, user_group_members

NO_PLAN_BUDGET_DETAIL = (
    "No budget plan is assigned to your account. "
    "Ask an administrator to assign a plan before you can use Alpharouter features."
)
BUDGET_EXCEEDED_DETAIL = "Monthly budget exceeded"


async def resolve_monthly_budget(db: AsyncSession, user: User) -> float:
    """Resolve monthly USD budget: user override (plan or explicit none) → group → department."""
    from app.services.plan_assignment_service import get_user_direct_assignment

    direct = await get_user_direct_assignment(db, user.id)
    if direct is not None:
        if direct.plan_id is None:
            return 0.0
        plan = await db.get(BudgetPlan, direct.plan_id)
        if plan:
            return plan.monthly_budget_usd
        return 0.0

    group_ids = select(user_group_members.c.group_id).where(user_group_members.c.user_id == user.id)
    gq = select(PlanAssignment).where(PlanAssignment.group_id.in_(group_ids))
    group_assign = (await db.execute(gq)).scalars().first()
    if group_assign:
        plan = await db.get(BudgetPlan, group_assign.plan_id)
        if plan:
            return plan.monthly_budget_usd

    if user.department:
        dq = select(PlanAssignment).where(
            PlanAssignment.department == user.department,
            PlanAssignment.department.isnot(None),
        )
        dept_assign = (await db.execute(dq)).scalars().first()
        if dept_assign:
            plan = await db.get(BudgetPlan, dept_assign.plan_id)
            if plan:
                return plan.monthly_budget_usd

    return 0.0


async def resolve_monthly_budgets_batch(db: AsyncSession, users: list[User]) -> dict[int, float]:
    """Batch-resolve monthly budgets for admin lists (same rules as resolve_monthly_budget)."""
    if not users:
        return {}

    user_ids = [u.id for u in users]
    budgets = {u.id: 0.0 for u in users}

    direct_rows = (
        await db.execute(
            select(PlanAssignment.user_id, PlanAssignment.plan_id, BudgetPlan.monthly_budget_usd)
            .outerjoin(BudgetPlan, BudgetPlan.id == PlanAssignment.plan_id)
            .where(PlanAssignment.user_id.in_(user_ids), PlanAssignment.user_id.isnot(None))
        )
    ).all()

    explicit_none_ids: set[int] = set()
    assigned_direct_ids: set[int] = set()
    for uid, plan_id, amount in direct_rows:
        if uid is None:
            continue
        user_id = int(uid)
        if plan_id is None:
            budgets[user_id] = 0.0
            explicit_none_ids.add(user_id)
        elif amount is not None:
            budgets[user_id] = float(amount)
            assigned_direct_ids.add(user_id)

    unresolved_ids = [uid for uid in user_ids if uid not in explicit_none_ids and uid not in assigned_direct_ids]
    if unresolved_ids:
        member_rows = (
            await db.execute(
                select(user_group_members.c.user_id, user_group_members.c.group_id).where(
                    user_group_members.c.user_id.in_(unresolved_ids)
                )
            )
        ).all()
        user_group_ids: dict[int, list[int]] = {}
        group_ids: set[int] = set()
        for uid, gid in member_rows:
            if uid is None or gid is None:
                continue
            user_group_ids.setdefault(int(uid), []).append(int(gid))
            group_ids.add(int(gid))
        if group_ids:
            group_rows = (
                await db.execute(
                    select(PlanAssignment.group_id, BudgetPlan.monthly_budget_usd)
                    .join(BudgetPlan, BudgetPlan.id == PlanAssignment.plan_id)
                    .where(PlanAssignment.group_id.in_(group_ids), PlanAssignment.group_id.isnot(None))
                )
            ).all()
            group_budgets = {int(gid): float(amount) for gid, amount in group_rows if gid is not None}
            for uid in unresolved_ids:
                for gid in user_group_ids.get(uid, []):
                    if gid in group_budgets:
                        budgets[uid] = group_budgets[gid]
                        break

    dept_users = [u for u in users if u.id in unresolved_ids and budgets[u.id] <= 0 and u.department]
    if dept_users:
        departments = {u.department for u in dept_users if u.department}
        dept_rows = (
            await db.execute(
                select(PlanAssignment.department, BudgetPlan.monthly_budget_usd)
                .join(BudgetPlan, BudgetPlan.id == PlanAssignment.plan_id)
                .where(PlanAssignment.department.in_(departments), PlanAssignment.department.isnot(None))
            )
        ).all()
        dept_budgets = {str(dept): float(amount) for dept, amount in dept_rows if dept}
        for user in dept_users:
            if user.department in dept_budgets:
                budgets[user.id] = dept_budgets[user.department]

    return budgets


async def resolve_inherited_plans_batch(db: AsyncSession, users: list[User]) -> dict[int, dict]:
    """Batch-resolve group/department plan inherited by users without a direct override."""
    empty = {
        "inherited_plan_id": None,
        "inherited_plan_name": None,
        "inherited_plan_source": None,
    }
    if not users:
        return {}

    user_ids = [u.id for u in users]
    users_by_id = {u.id: u for u in users}
    out: dict[int, dict] = {uid: dict(empty) for uid in user_ids}

    direct_rows = (
        await db.execute(
            select(PlanAssignment.user_id, PlanAssignment.plan_id).where(
                PlanAssignment.user_id.in_(user_ids), PlanAssignment.user_id.isnot(None)
            )
        )
    ).all()
    explicit_none_ids = {int(uid) for uid, plan_id in direct_rows if uid is not None and plan_id is None}
    assigned_direct_ids = {int(uid) for uid, plan_id in direct_rows if uid is not None and plan_id is not None}
    inherit_ids = [uid for uid in user_ids if uid not in explicit_none_ids and uid not in assigned_direct_ids]
    if not inherit_ids:
        return out

    member_rows = (
        await db.execute(
            select(user_group_members.c.user_id, user_group_members.c.group_id).where(
                user_group_members.c.user_id.in_(inherit_ids)
            )
        )
    ).all()
    user_group_ids: dict[int, list[int]] = {}
    group_ids: set[int] = set()
    for uid, gid in member_rows:
        if uid is None or gid is None:
            continue
        user_group_ids.setdefault(int(uid), []).append(int(gid))
        group_ids.add(int(gid))

    if group_ids:
        group_rows = (
            await db.execute(
                select(PlanAssignment.group_id, BudgetPlan.id, BudgetPlan.name)
                .join(BudgetPlan, BudgetPlan.id == PlanAssignment.plan_id)
                .where(PlanAssignment.group_id.in_(group_ids), PlanAssignment.group_id.isnot(None))
            )
        ).all()
        group_plans = {
            int(gid): (int(plan_id), str(name))
            for gid, plan_id, name in group_rows
            if gid is not None and plan_id is not None and name
        }
        for uid in inherit_ids:
            for gid in user_group_ids.get(uid, []):
                if gid in group_plans:
                    plan_id, plan_name = group_plans[gid]
                    out[uid] = {
                        "inherited_plan_id": plan_id,
                        "inherited_plan_name": plan_name,
                        "inherited_plan_source": "group",
                    }
                    break

    dept_candidates = [
        uid for uid in inherit_ids if out[uid]["inherited_plan_id"] is None and users_by_id[uid].department
    ]
    if dept_candidates:
        departments = {users_by_id[uid].department for uid in dept_candidates}
        dept_rows = (
            await db.execute(
                select(PlanAssignment.department, BudgetPlan.id, BudgetPlan.name)
                .join(BudgetPlan, BudgetPlan.id == PlanAssignment.plan_id)
                .where(PlanAssignment.department.in_(departments), PlanAssignment.department.isnot(None))
            )
        ).all()
        dept_plans = {
            str(dept): (int(plan_id), str(name))
            for dept, plan_id, name in dept_rows
            if dept and plan_id is not None and name
        }
        for uid in dept_candidates:
            dept = users_by_id[uid].department
            if dept in dept_plans:
                plan_id, plan_name = dept_plans[dept]
                out[uid] = {
                    "inherited_plan_id": plan_id,
                    "inherited_plan_name": plan_name,
                    "inherited_plan_source": "department",
                }

    return out


def budget_request_blocked(budget: float, usage: float) -> str | None:
    """Return HTTP error detail when chat/API spend must be blocked, else None."""
    if budget <= 0:
        return NO_PLAN_BUDGET_DETAIL
    if usage >= budget:
        return BUDGET_EXCEEDED_DETAIL
    return None


async def get_user_budget_state(db: AsyncSession, user: User) -> tuple[float, float]:
    """Ensure period is current and return (monthly_budget_usd, used_usd)."""
    await ensure_budget_period(db, user)
    budget = await resolve_monthly_budget(db, user)
    # Atomic settlements and reservations enforce against this live counter.
    # Read it here too so dashboards, admin resets, and blocking cannot drift.
    usage = float(user.budget_used_usd or 0) + float(user.budget_reserved_usd or 0)
    return budget, usage


async def get_month_usage(db: AsyncSession, user_id: int) -> float:
    now = datetime.datetime.utcnow()
    month_start = datetime.datetime(now.year, now.month, 1)
    user_period_start = (
        await db.execute(select(User.budget_period_start).where(User.id == user_id))
    ).scalar_one_or_none()
    start = user_period_start if user_period_start is not None and user_period_start > month_start else month_start
    ledger_q = select(func.coalesce(func.sum(LedgerEntry.amount_usd), 0.0)).where(
        LedgerEntry.subject_type == "user",
        LedgerEntry.subject_id == user_id,
        LedgerEntry.effective_at >= start,
    )
    legacy_q = select(func.coalesce(func.sum(RequestLog.total_cost_usd), 0.0)).where(
        RequestLog.user_id == user_id,
        RequestLog.request_time >= start,
        RequestLog.usage_operation_id.is_(None),
    )
    ledger_total = float((await db.execute(ledger_q)).scalar_one())
    legacy_total = float((await db.execute(legacy_q)).scalar_one())
    return max(0.0, ledger_total + legacy_total)


async def ensure_budget_period(db: AsyncSession, user: User) -> None:
    """Reset usage at month boundary; always sync cached budget from plan assignments.

    On rollover, open budget holds are expired and ``budget_reserved_usd`` is
    reconciled so reserved counters cannot leak from the previous month.
    """
    now = datetime.datetime.utcnow()
    month_start = datetime.datetime(now.year, now.month, 1)
    if not user.budget_period_start or user.budget_period_start < month_start:
        from app.services.budget_reservation_service import (
            SUBJECT_USER,
            _locked_user_stmt,
            release_open_holds_for_subject,
        )

        # Callers pass the request-scoped User loaded without a lock. The
        # rollover rewrites budget_used_usd / budget_reserved_usd, which
        # ``reserve`` and ``release`` update under SELECT ... FOR UPDATE in
        # other transactions; writing them from an unlocked snapshot lost
        # those updates. Take the row lock (refreshing the instance) and
        # re-check: another request may have rolled the period over already.
        locked = (await db.execute(_locked_user_stmt(int(user.id)))).scalar_one_or_none()
        if locked is None:
            return
        user = locked
        if not user.budget_period_start or user.budget_period_start < month_start:
            await release_open_holds_for_subject(db, SUBJECT_USER, int(user.id))
            user.budget_period_start = month_start
            user.budget_used_usd = await get_month_usage(db, user.id)
            user.budget_reserved_usd = 0.0
    user.monthly_budget_usd = await resolve_monthly_budget(db, user)
    await db.flush()


async def reset_all_monthly_budgets(db: AsyncSession) -> int:
    """Called at 00:05 UTC on the 1st of each month by the scheduler.

    No ``now.day != 1`` guard: the cron trigger (UTC, with misfire grace) is
    the authority on *when*. The guard used to turn a run that fired a few
    minutes late - or fired in a non-UTC server zone - into a silent no-op.
    """
    now = datetime.datetime.utcnow()
    from app.services.budget_reservation_service import (
        SUBJECT_USER,
        release_open_holds_for_subject,
    )

    users = (await db.execute(select(User))).scalars().all()
    count = 0
    for u in users:
        await release_open_holds_for_subject(db, SUBJECT_USER, int(u.id))
        u.budget_used_usd = 0.0
        u.budget_reserved_usd = 0.0
        u.budget_period_start = datetime.datetime(now.year, now.month, 1)
        u.monthly_budget_usd = await resolve_monthly_budget(db, u)
        count += 1
    await db.commit()
    return count
