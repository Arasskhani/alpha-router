"""The monthly reset must not be one transaction over every user.

``reset_all_monthly_budgets`` loaded every user, took a lock per user through
``release_open_holds_for_subject``, resolved each user's plan with three or
four queries of its own, and committed once at the end. On a large
installation that is one transaction holding locks on every user row for the
length of the run - and if anything raises, nobody is reset.

Nobody is reset is the bad case: a user whose ``budget_used_usd`` was not
cleared is over budget for the whole of the following month, and this job runs
once a month, so the next attempt is thirty days away.
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.user import User
from app.services import budget_service
from app.services.budget_service import reset_all_monthly_budgets


async def _spender(db_session, name: str, used: float = 7.5) -> User:
    row = User(
        username=name,
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
        budget_used_usd=used,
        budget_reserved_usd=2.0,
        budget_period_start=datetime.datetime(2000, 1, 1),
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _used(db_session, username: str) -> float:
    row = (await db_session.execute(select(User).where(User.username == username))).scalars().one()
    return float(row.budget_used_usd or 0.0)


async def test_everyone_is_reset(db_session):
    for index in range(5):
        await _spender(db_session, f"resettable_{index}")
    await db_session.commit()

    count = await reset_all_monthly_budgets(db_session)

    assert count >= 5
    for index in range(5):
        assert await _used(db_session, f"resettable_{index}") == 0.0


async def test_the_work_is_committed_as_it_goes(db_session, monkeypatch):
    """A failure on the last user does not undo the first four."""

    monkeypatch.setattr(budget_service, "MONTHLY_RESET_BATCH_SIZE", 2)
    for index in range(5):
        await _spender(db_session, f"batched_{index}")
    await db_session.commit()

    doomed = (await db_session.execute(select(User).where(User.username == "batched_4"))).scalars().one()

    from app.services import budget_reservation_service

    real = budget_reservation_service.release_open_holds_for_subject

    async def explode(db, subject_type, subject_id):
        if int(subject_id) == int(doomed.id):
            raise RuntimeError("this user's holds cannot be released")
        return await real(db, subject_type, subject_id)

    monkeypatch.setattr(budget_reservation_service, "release_open_holds_for_subject", explode)

    await reset_all_monthly_budgets(db_session)

    for index in range(4):
        assert await _used(db_session, f"batched_{index}") == 0.0, "an earlier batch was rolled back by a later failure"


async def test_one_bad_user_does_not_take_its_batch_down(db_session, monkeypatch):
    monkeypatch.setattr(budget_service, "MONTHLY_RESET_BATCH_SIZE", 10)
    for index in range(4):
        await _spender(db_session, f"companion_{index}")
    await db_session.commit()

    doomed = (await db_session.execute(select(User).where(User.username == "companion_2"))).scalars().one()
    doomed_id = int(doomed.id)

    from app.services import budget_reservation_service

    real = budget_reservation_service.release_open_holds_for_subject

    async def explode(db, subject_type, subject_id):
        if int(subject_id) == doomed_id:
            raise RuntimeError("this user's holds cannot be released")
        return await real(db, subject_type, subject_id)

    monkeypatch.setattr(budget_reservation_service, "release_open_holds_for_subject", explode)

    await reset_all_monthly_budgets(db_session)

    for index in (0, 1, 3):
        assert await _used(db_session, f"companion_{index}") == 0.0, "one unresettable user blocked the rest"


async def test_the_plans_are_resolved_in_bulk(db_session, monkeypatch):
    """Per-user resolution is three or four queries each; the bulk form exists."""

    monkeypatch.setattr(budget_service, "MONTHLY_RESET_BATCH_SIZE", 50)
    for index in range(6):
        await _spender(db_session, f"planned_{index}")
    await db_session.commit()

    calls: list[int] = []
    real = budget_service.resolve_monthly_budgets_batch

    async def counting(db, users):
        calls.append(len(users))
        return await real(db, users)

    monkeypatch.setattr(budget_service, "resolve_monthly_budgets_batch", counting)

    await reset_all_monthly_budgets(db_session)

    assert calls, "the reset resolves each user's plan one at a time"
    assert max(calls) > 1


@pytest.mark.parametrize("field", ["budget_used_usd", "budget_reserved_usd"])
async def test_the_period_counters_are_cleared(db_session, field):
    await _spender(db_session, f"cleared_{field}")
    await db_session.commit()

    await reset_all_monthly_budgets(db_session)

    row = (await db_session.execute(select(User).where(User.username == f"cleared_{field}"))).scalars().one()
    assert float(getattr(row, field) or 0.0) == 0.0
    today = datetime.datetime.utcnow()
    assert row.budget_period_start == datetime.datetime(today.year, today.month, 1)
