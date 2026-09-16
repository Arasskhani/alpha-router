"""A user should hear that their budget is running down before it stops them.

Until now the first signal was a refused request. These cover the two things
that make a warning trustworthy: it arrives once per threshold, and it cannot
be lost — reading a notice does not spend it, only the client confirming it was
displayed does.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.budget import BudgetPlan, PlanAssignment
from app.models.user import User
from app.services.budget_notice_service import (
    BUDGET_NOTICE_THRESHOLDS,
    NOTICE_LEVEL_NONE,
    acknowledge_budget_notice,
    notice_level_for,
    pending_budget_notice,
)


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _user_on_plan(db: AsyncSession, budget: float, used: float = 0.0, reserved: float = 0.0) -> User:
    user = User(
        username="u",
        email="u@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
        budget_used_usd=used,
        budget_reserved_usd=reserved,
    )
    db.add(user)
    await db.flush()
    if budget > 0:
        plan = BudgetPlan(name="p", monthly_budget_usd=budget)
        db.add(plan)
        await db.flush()
        db.add(PlanAssignment(plan_id=plan.id, user_id=user.id))
        await db.flush()
    return user


class TestThresholds:
    @pytest.mark.parametrize(
        "used,expected",
        [(0.0, 0), (69.99, 0), (70.0, 70), (89.99, 70), (90.0, 90), (100.0, 90), (250.0, 90)],
    )
    def test_the_highest_threshold_reached_wins(self, used, expected):
        assert notice_level_for(100.0, used) == expected

    def test_a_leap_past_both_lines_says_ninety_once(self):
        """The user asked for one message, not two, when a single expensive
        turn jumps from under 70% straight past 90%."""
        assert notice_level_for(100.0, 95.0) == 90

    def test_no_plan_is_not_a_budget_of_nothing(self):
        """resolve_monthly_budget returns 0.0 for an unassigned account. There
        is no percentage to report, and any division would be by zero."""
        assert notice_level_for(0.0, 12.0) == NOTICE_LEVEL_NONE

    def test_a_negative_budget_is_treated_the_same(self):
        assert notice_level_for(-5.0, 1.0) == NOTICE_LEVEL_NONE

    def test_the_thresholds_are_ordered_highest_first(self):
        """notice_level_for returns the first match, so the order is load-bearing."""
        assert list(BUDGET_NOTICE_THRESHOLDS) == sorted(BUDGET_NOTICE_THRESHOLDS, reverse=True)


class TestPending:
    async def test_nothing_is_said_below_the_first_line(self, db):
        user = await _user_on_plan(db, 100.0, used=50.0)
        assert await pending_budget_notice(db, user) is None

    async def test_crossing_seventy_produces_a_notice(self, db):
        user = await _user_on_plan(db, 100.0, used=72.0)
        notice = await pending_budget_notice(db, user)
        assert notice is not None
        assert notice["level"] == 70
        assert notice["percent"] == 72.0
        assert notice["remaining_usd"] == 28.0

    async def test_reserved_spend_counts_towards_the_percentage(self, db):
        """Same definition get_user_budget_state enforces with and the profile
        menu displays — a warning that disagrees with the number on screen is
        worse than none."""
        user = await _user_on_plan(db, 100.0, used=40.0, reserved=35.0)
        notice = await pending_budget_notice(db, user)
        assert notice is not None and notice["level"] == 70

    async def test_reading_twice_still_reports_it(self, db):
        """Reading must not spend the notice: if it did, a trailing frame lost
        to a closed tab would take the only warning with it."""
        user = await _user_on_plan(db, 100.0, used=72.0)
        assert await pending_budget_notice(db, user) is not None
        assert await pending_budget_notice(db, user) is not None
        assert int(user.budget_notice_level or 0) == 0

    async def test_once_acknowledged_it_goes_quiet(self, db):
        user = await _user_on_plan(db, 100.0, used=72.0)
        await db.commit()
        await acknowledge_budget_notice(db, user.id, 70)
        await db.refresh(user)
        assert await pending_budget_notice(db, user) is None

    async def test_but_the_next_threshold_still_speaks(self, db):
        user = await _user_on_plan(db, 100.0, used=72.0)
        await db.commit()
        await acknowledge_budget_notice(db, user.id, 70)
        user.budget_used_usd = 93.0
        await db.flush()
        notice = await pending_budget_notice(db, user)
        assert notice is not None and notice["level"] == 90

    async def test_a_raised_budget_lets_the_warning_fire_again(self, db):
        """The trap the whole design is built around. An administrator raising
        the plan drops the percentage; without lowering the recorded level the
        user would never be warned again this period."""
        user = await _user_on_plan(db, 100.0, used=95.0)
        await db.commit()
        await acknowledge_budget_notice(db, user.id, 90)
        await db.refresh(user)
        assert int(user.budget_notice_level) == 90

        plan = await db.get(BudgetPlan, 1)
        assert plan is not None
        plan.monthly_budget_usd = 1000.0
        await db.flush()

        # 9.5% — nothing to say, and the marker comes back down on its own.
        assert await pending_budget_notice(db, user) is None
        assert int(user.budget_notice_level) == 0

        # Later in the same period the user spends again and is warned properly.
        user.budget_used_usd = 720.0
        await db.flush()
        notice = await pending_budget_notice(db, user)
        assert notice is not None and notice["level"] == 70

    async def test_a_budget_reset_is_handled_without_touching_the_reset_paths(self, db):
        """ensure_budget_period, the scheduler and the admin reset all clear
        usage. None of them knows this column exists, and none needs to."""
        user = await _user_on_plan(db, 100.0, used=95.0)
        await db.commit()
        await acknowledge_budget_notice(db, user.id, 90)
        await db.refresh(user)

        user.budget_used_usd = 0.0
        user.budget_reserved_usd = 0.0
        await db.flush()

        assert await pending_budget_notice(db, user) is None
        assert int(user.budget_notice_level) == 0

    async def test_losing_a_plan_silences_it(self, db):
        user = await _user_on_plan(db, 0.0, used=95.0)
        assert await pending_budget_notice(db, user) is None


class TestAcknowledge:
    async def test_it_cannot_be_used_to_silence_a_warning_never_shown(self, db):
        """A client posting 90 at 72% would otherwise skip the 90% warning
        entirely. The acknowledgement is clamped to what the figures justify."""
        user = await _user_on_plan(db, 100.0, used=72.0)
        await db.commit()
        stored = await acknowledge_budget_notice(db, user.id, 90)
        assert stored == 70
        user.budget_used_usd = 93.0
        await db.flush()
        notice = await pending_budget_notice(db, user)
        assert notice is not None and notice["level"] == 90

    async def test_an_unknown_user_is_not_an_error(self, db):
        assert await acknowledge_budget_notice(db, 999_999, 70) == NOTICE_LEVEL_NONE


def test_the_chat_stream_only_tells_the_chat_ui():
    """Gateway API-key callers bill against a different pool; handing them an
    unexpected field in their response body is a leak, not a feature."""
    import inspect

    from app.services import turn_settlement

    source = inspect.getsource(turn_settlement)
    marker = 'if not outcome.was_cancelled and identity.source == "alpha_router_chat":'
    assert marker in source
    assert source.index(marker) < source.index("budget_notice_after_settlement(identity.user_id)")


def test_the_settlement_path_reads_a_fresh_session():
    """_persist_stream_usage writes budget_used_usd from an independent session
    and commits, so the request-scoped User is a pre-settlement snapshot."""
    import inspect

    from app.services import budget_notice_service

    source = inspect.getsource(budget_notice_service.budget_notice_after_settlement)
    assert "AsyncSessionLocal()" in source


def test_acknowledgement_takes_the_row_lock():
    """budget_used_usd and budget_reserved_usd are written under this lock by
    settlements and reservations; writing a sibling column from an unlocked
    instance puts a stale copy of those back."""
    import inspect

    from app.services import budget_notice_service

    source = inspect.getsource(budget_notice_service.acknowledge_budget_notice)
    assert "_locked_user_stmt" in source
