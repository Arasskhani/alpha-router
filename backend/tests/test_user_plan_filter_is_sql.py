"""The effective-plan filter on /admin/users is decided by the query alone.

The list applied a plan predicate in SQL and then, from the rows that came
back, filtered *again* in Python with the full resolution rules. The second
pass could only remove rows - which meant the SQL predicate was letting rows
through that the product did not consider matches, and that a LIMIT placed on
the query would yield ragged pages that quietly hid accounts.

The gap was one rule: a department plan applies only when the user has no
group plan. Once the predicate says that too, the SQL answer *is* the answer,
the Python pass is redundant, and the list can be paged in the database.
"""

from __future__ import annotations

import itertools

from sqlalchemy import select

from app.api import admin as admin_api
from app.core.security import hash_password
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.user import User, UserGroup, user_group_members
from app.services.budget_service import resolve_inherited_plans_batch


async def _matrix(db_session) -> dict[str, User]:
    """Every combination of: direct (none / explicit-none / plan A), group plan
    (none / A / B), department plan (none / A / B)."""

    plan_a = BudgetPlan(name="A", monthly_budget_usd=10)
    plan_b = BudgetPlan(name="B", monthly_budget_usd=20)
    db_session.add_all([plan_a, plan_b])
    await db_session.flush()
    group_a = UserGroup(name="grp-a", source="local")
    group_b = UserGroup(name="grp-b", source="local")
    db_session.add_all([group_a, group_b])
    await db_session.flush()
    db_session.add_all(
        [
            PlanAssignment(group_id=group_a.id, plan_id=plan_a.id),
            PlanAssignment(group_id=group_b.id, plan_id=plan_b.id),
            PlanAssignment(department="dept-a", plan_id=plan_a.id),
            PlanAssignment(department="dept-b", plan_id=plan_b.id),
        ]
    )
    users: dict[str, User] = {}
    for direct, group, dept in itertools.product(
        ("none", "explicit-none", "A"), ("none", "A", "B"), ("none", "A", "B")
    ):
        name = f"u-{direct}-g{group}-d{dept}".lower()
        user = User(
            username=name,
            hashed_password=hash_password("x"),
            auth_provider="local",
            is_active=True,
            department=None if dept == "none" else f"dept-{dept.lower()}",
        )
        db_session.add(user)
        await db_session.flush()
        if direct == "explicit-none":
            db_session.add(PlanAssignment(user_id=user.id, plan_id=None))
        elif direct == "A":
            db_session.add(PlanAssignment(user_id=user.id, plan_id=plan_a.id))
        if group != "none":
            await db_session.execute(
                user_group_members.insert().values(user_id=user.id, group_id=(group_a if group == "A" else group_b).id)
            )
        users[name] = user
    await db_session.commit()
    return users


async def _python_effective(db_session, users: list[User]) -> dict[int, int | None]:
    plan_state = await admin_api._build_user_plan_state_map(db_session, [u.id for u in users])
    inherited = await resolve_inherited_plans_batch(db_session, users)
    return {u.id: admin_api._effective_plan_id(u.id, plan_state, inherited) for u in users}


async def _sql_matches(db_session, **plan_filter) -> set[int]:
    stmt = admin_api._apply_user_list_filters(
        select(User),
        q=None,
        username=None,
        email=None,
        department=None,
        job_title=None,
        role=None,
        is_active=None,
        group_id=None,
        active_only=True,
        **plan_filter,
    )
    return {u.id for u in (await db_session.execute(stmt)).scalars().all()}


async def test_the_query_agrees_with_the_resolver_for_every_plan(db_session):
    users = await _matrix(db_session)
    everyone = list(users.values())
    truth = await _python_effective(db_session, everyone)
    plan_ids = {p.name: p.id for p in (await db_session.execute(select(BudgetPlan))).scalars().all()}

    for name, plan_id in plan_ids.items():
        expected = {uid for uid, eff in truth.items() if eff == plan_id}
        got = await _sql_matches(db_session, plan_id=plan_id)
        wrong = {u.username for u in everyone if (u.id in got) != (u.id in expected)}
        assert not wrong, f"plan {name}: the query and the resolver disagree on {sorted(wrong)}"


async def test_the_query_agrees_with_the_resolver_for_no_plan(db_session):
    users = await _matrix(db_session)
    everyone = list(users.values())
    truth = await _python_effective(db_session, everyone)

    expected = {uid for uid, eff in truth.items() if eff is None}
    got = await _sql_matches(db_session, no_plan=True)
    wrong = {u.username for u in everyone if (u.id in got) != (u.id in expected)}
    assert not wrong, f"no_plan: the query and the resolver disagree on {sorted(wrong)}"


async def test_the_list_returns_exactly_the_query_s_answer(db_session):
    """No Python pass after the query: the rows the list returns for a plan are
    the rows the resolver says have it."""

    users = await _matrix(db_session)
    everyone = list(users.values())
    truth = await _python_effective(db_session, everyone)
    plan_b = (await db_session.execute(select(BudgetPlan).where(BudgetPlan.name == "B"))).scalar_one()

    rows, _ = await admin_api._list_admin_user_dicts(
        db_session,
        q=None,
        username=None,
        email=None,
        department=None,
        job_title=None,
        role=None,
        is_active=None,
        group_id=None,
        user_id=None,
        online=None,
        picker=False,
        plan_id=plan_b.id,
        no_plan=False,
    )

    assert {row["id"] for row in rows} == {uid for uid, eff in truth.items() if eff == plan_b.id}
