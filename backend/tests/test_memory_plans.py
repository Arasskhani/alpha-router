"""Ongoing plans and routines are remembered while they are being followed.

A workout plan, a diet, a current project: the extractor was told to keep
"facts still useful in 7+ days" and had no word for them, so they were
learned as goals or not at all, and never went away. They now have their own
category, last ``plan_ttl_days`` (90 by default), and start again each time
the person mentions them. The administrator can switch plans off.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models.chat import UserMemory
from app.models.system import SystemSetting
from app.services.memory_extraction_service import MemoryOperation, apply_memory_operations, extraction_system_prompt
from app.services.memory_settings_service import MEMORY_CATEGORIES, parse_memory_settings

PLAN = "User follows a workout plan: squats on Monday, running on Wednesday."


def _plan(content: str = PLAN, **kwargs) -> MemoryOperation:
    return MemoryOperation(op="add", content=content, category="plan", confidence=0.9, salience=0.8, **kwargs)


async def _rows(db, user_id: int) -> list[UserMemory]:
    return list((await db.execute(select(UserMemory).where(UserMemory.user_id == user_id))).scalars())


def test_the_extractor_is_told_about_plans_only_while_they_are_on():
    assert "plan" in MEMORY_CATEGORIES
    on = extraction_system_prompt(plans=True)
    assert "|plan|" in on and "Ongoing plans and routines" in on
    off = extraction_system_prompt(plans=False)
    assert "plan" not in off.split("Rules:")[0] and "Ongoing plans" not in off
    assert parse_memory_settings({})["plan_ttl_days"] == 90 and parse_memory_settings({})["plan_memory_enabled"]


async def test_a_plan_lasts_its_time_and_starts_again_when_mentioned(db_session, user):
    result = await apply_memory_operations(db_session, user_id=user.id, session_id=None, operations=[_plan()])
    assert result.added == 1
    row = (await _rows(db_session, user.id))[0]
    assert row.category == "plan"
    assert abs((row.expires_at - dt.datetime.utcnow()) - dt.timedelta(days=90)) < dt.timedelta(minutes=1)

    row.expires_at = dt.datetime.utcnow() + dt.timedelta(days=3)
    await db_session.commit()
    await apply_memory_operations(db_session, user_id=user.id, session_id=None, operations=[_plan()])
    await db_session.refresh(row)
    assert row.expires_at - dt.datetime.utcnow() > dt.timedelta(days=89)


async def test_its_time_is_the_administrator_s_and_the_extractor_s_when_it_gives_one(db_session, user):
    db_session.add(SystemSetting(key="memory_plan_ttl_days", value="30"))
    await db_session.commit()
    await apply_memory_operations(
        db_session,
        user_id=user.id,
        session_id=None,
        operations=[_plan(), _plan("User is on a two-week diet without sugar.", ttl_days=14)],
    )
    by_content = {row.content: row for row in await _rows(db_session, user.id)}
    left = {content: (row.expires_at - dt.datetime.utcnow()).days for content, row in by_content.items()}
    assert left == {PLAN: 29, "User is on a two-week diet without sugar.": 13}


async def test_switched_off_no_plan_is_kept_and_nothing_else_changes(db_session, user):
    db_session.add(SystemSetting(key="memory_plan_enabled", value="false"))
    await db_session.commit()
    other = MemoryOperation(op="add", content="User lives in Tehran", category="identity")
    result = await apply_memory_operations(db_session, user_id=user.id, session_id=None, operations=[_plan(), other])
    assert (result.added, result.skipped) == (1, 1)
    assert [row.content for row in await _rows(db_session, user.id)] == ["User lives in Tehran"]


async def test_other_facts_still_do_not_expire(db_session, user):
    await apply_memory_operations(
        db_session,
        user_id=user.id,
        session_id=None,
        operations=[MemoryOperation(op="add", content="User prefers black coffee", category="preference")],
    )
    assert (await _rows(db_session, user.id))[0].expires_at is None
