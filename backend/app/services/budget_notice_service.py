"""Warn a user as their monthly budget runs down, once per threshold.

Until now the first sign that a budget was nearly gone was a request being
refused. This module decides when to say something, and says it at most once
per threshold per period.

``users.budget_notice_level`` holds the highest threshold the user has actually
been *shown* — not the highest they have crossed. That distinction is the whole
design:

* **Reading never spends the warning.** Deciding that a notice is pending is a
  pure computation over the live figures. If the chat stream's trailing frame
  never reaches the browser — the client disconnected, the tab was closed, the
  network dropped — nothing was recorded, so the next page load reports the same
  pending notice. A warning that can be lost by a dropped socket is not a
  warning.
* **Only the client marks it shown**, by acknowledging the level it displayed.
  That is the one moment we know the user saw it.
* **The level is lowered eagerly, on any evaluation.** A budget can be raised or
  reset — by a plan change, the monthly rollover in ``ensure_budget_period``,
  the scheduler's ``reset_all_monthly_budgets``, or an administrator's
  ``budget-reset``. All of them drop the percentage, and all of them are handled
  here for free. Had the level only ever ratcheted upward, each would have
  needed its own reset, and the fifth one added later would have been the bug.
  Lowering is always safe: it can only let a warning fire again, never suppress
  one.

Usage is ``used + reserved`` — the same number ``get_user_budget_state``
enforces against and the same number the profile menu shows the user, because a
warning that disagrees with the figure on screen is worse than no warning.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.budget_service import resolve_monthly_budget

logger = logging.getLogger("alpha_router.budget_notice")

#: Percentages at which the user is told, highest first. Deliberately constants
#: rather than settings: two well-chosen thresholds that behave identically for
#: everyone are easier to reason about than a knob nobody turns. Making them
#: per-plan later means replacing this tuple with a lookup and nothing else.
BUDGET_NOTICE_THRESHOLDS: tuple[int, ...] = (90, 70)

#: Nothing has been shown.
NOTICE_LEVEL_NONE = 0


def notice_level_for(budget: float, usage: float) -> int:
    """The highest threshold this usage has reached, or 0.

    A budget of zero means "no plan assigned" (``resolve_monthly_budget``
    returns 0.0 for that), not "a budget of nothing". There is no percentage to
    report and nothing useful to warn about, so it is excluded before any
    division happens.

    Only the highest crossed threshold is returned, which is what makes a jump
    straight from 60% to 95% produce one notice saying 90% rather than two.
    """
    if budget <= 0:
        return NOTICE_LEVEL_NONE
    percent = (usage / budget) * 100.0
    for threshold in BUDGET_NOTICE_THRESHOLDS:
        if percent >= threshold:
            return threshold
    return NOTICE_LEVEL_NONE


def notice_payload(level: int, budget: float, usage: float) -> dict[str, Any]:
    """What the client needs to render the toast without a second request."""
    return {
        "level": int(level),
        "percent": round((usage / budget) * 100.0, 1) if budget > 0 else 0.0,
        "monthly_budget_usd": round(float(budget), 6),
        "used_usd": round(float(usage), 6),
        "remaining_usd": round(max(0.0, float(budget) - float(usage)), 6),
    }


def _usage_of(user: User) -> float:
    return float(user.budget_used_usd or 0) + float(user.budget_reserved_usd or 0)


async def pending_budget_notice(db: AsyncSession, user: User) -> dict[str, Any] | None:
    """The notice this user has not been shown yet, if any.

    Takes the ``User`` the caller already has. Safe on a request-scoped
    instance because nothing here depends on a value another transaction may be
    writing concurrently: the figures come from the same row the caller is
    about to show the user, and the only write is a *downward* correction.
    """
    budget = await resolve_monthly_budget(db, user)
    usage = _usage_of(user)
    level = notice_level_for(budget, usage)
    shown = int(user.budget_notice_level or NOTICE_LEVEL_NONE)

    if level < shown:
        # A raised plan or a reset; let the warning fire again later.
        user.budget_notice_level = level
        await db.flush()
        return None
    if level > shown:
        return notice_payload(level, budget, usage)
    return None


async def acknowledge_budget_notice(db: AsyncSession, user_id: int, level: int) -> int:
    """Record that the user was shown ``level``; returns the stored value.

    The row is taken with ``SELECT ... FOR UPDATE`` through
    ``_locked_user_stmt``: ``budget_used_usd`` and ``budget_reserved_usd`` are
    written under that same lock by settlements and reservations in other
    transactions, and ``_locked_user_stmt`` re-reads the row rather than handing
    back the session's cached snapshot. Writing this column from an unlocked
    instance would put back a stale copy of the other two.

    The acknowledgement is clamped to what the figures currently justify, so a
    client cannot silence a warning it was never shown by posting 90.
    """
    from app.services.budget_reservation_service import _locked_user_stmt

    user = (await db.execute(_locked_user_stmt(int(user_id)))).scalar_one_or_none()
    if user is None:
        return NOTICE_LEVEL_NONE
    budget = await resolve_monthly_budget(db, user)
    current = notice_level_for(budget, _usage_of(user))
    user.budget_notice_level = min(int(level), current)
    await db.flush()
    return int(user.budget_notice_level)


async def budget_notice_after_settlement(user_id: int | None) -> dict[str, Any] | None:
    """The settlement-path entry point: its own session, and never fatal.

    A separate session is not a stylistic choice. ``_persist_stream_usage``
    writes ``budget_used_usd`` through an independent session and commits, so
    the ``User`` loaded in the request session is a pre-settlement snapshot —
    reading it here would miss the very spend we are reacting to and warn the
    user one turn late. A fresh session sees the committed figure.

    Settlement runs inside the streaming response, so a failure here must not
    cost the user their answer: the notice is best-effort by construction.
    """
    if not user_id:
        return None
    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, int(user_id))
            if user is None:
                return None
            notice = await pending_budget_notice(db, user)
            await db.commit()
            return notice
    except Exception:  # noqa: BLE001 -- a missed warning must never break the turn
        logger.debug("Budget notice evaluation failed for user=%s", user_id, exc_info=True)
        return None
