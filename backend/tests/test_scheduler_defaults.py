"""Scheduler defaults and the per-user media cleanup decision."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import scheduler as sched
from app.services.scheduler import user_media_cleanup_due


def _prefs(hour, minute, last=None):
    return SimpleNamespace(cleanup_hour=hour, cleanup_minute=minute, last_cleanup_at=last)


def test_scheduler_has_misfire_grace_and_coalescing():
    defaults = sched.scheduler._job_defaults
    assert defaults["misfire_grace_time"] == 300
    assert defaults["coalesce"] is True
    assert defaults["max_instances"] == 1
    assert sched.scheduler.timezone is not None


def test_cleanup_with_a_non_zero_minute_actually_runs():
    day = datetime(2026, 9, 14)
    prefs = _prefs(3, 30)
    # Hourly poll at 03:00 used to be the only chance and was skipped (0 < 30).
    assert user_media_cleanup_due(prefs, day.replace(hour=3, minute=0)) is False
    assert user_media_cleanup_due(prefs, day.replace(hour=3, minute=30)) is True
    assert user_media_cleanup_due(prefs, day.replace(hour=3, minute=45)) is True
    assert user_media_cleanup_due(prefs, day.replace(hour=23, minute=59)) is True  # late is still due


def test_cleanup_runs_once_per_scheduled_slot():
    day = datetime(2026, 9, 14)
    served = day.replace(hour=3, minute=31)
    prefs = _prefs(3, 30, last=served)
    assert user_media_cleanup_due(prefs, day.replace(hour=4)) is False
    assert user_media_cleanup_due(prefs, day.replace(hour=22)) is False
    # Next day's slot is due again.
    assert user_media_cleanup_due(prefs, (day + timedelta(days=1)).replace(hour=3, minute=30)) is True
    # A run that happened *before* today's slot (e.g. yesterday) does not count.
    prefs_old = _prefs(3, 30, last=day.replace(hour=2))
    assert user_media_cleanup_due(prefs_old, day.replace(hour=3, minute=30)) is True


def test_budget_reset_trigger_is_utc_and_reset_has_no_day_guard(monkeypatch):
    from app.services import budget_service

    # Trigger registration: the budget_reset cron carries an explicit UTC zone.
    added = []
    monkeypatch.setattr(sched.scheduler, "add_job", lambda *a, **k: added.append((a, k)))
    monkeypatch.setattr(sched.scheduler, "start", lambda: None)
    sched.start_scheduler()
    reset = next(k for a, k in added if k.get("id") == "budget_reset")
    assert reset["timezone"] is timezone.utc

    # Function: runs on any day (the trigger decides) - the 14th here.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import app.models  # noqa: F401
    from app.database import Base
    from app.models.user import User

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as db:
                u = User(
                    username="r", email="r@t", hashed_password="x", auth_provider="local", is_active=True,
                    monthly_budget_usd=10.0, budget_used_usd=4.0, budget_reserved_usd=0.0,
                )
                db.add(u)
                await db.commit()
                with monkeypatch.context() as m:
                    m.setattr(budget_service.datetime, "datetime", _FixedDT)
                    assert await budget_service.reset_all_monthly_budgets(db) == 1
                await db.refresh(u)
                assert u.budget_used_usd == 0.0
                assert u.budget_period_start == datetime(2026, 9, 1)
        finally:
            await engine.dispose()

    asyncio.run(run())


class _FixedDT(datetime):
    @classmethod
    def utcnow(cls):
        return cls(2026, 9, 14, 0, 6)  # the 14th, not the 1st
