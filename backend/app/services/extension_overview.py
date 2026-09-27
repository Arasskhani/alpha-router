"""What an administrator sees at a glance about the browser extension.

The tiles on the Browser Extension page: whether the extension is on, how many
browsers are connected and how many of them run an older package, what the
agent did today, and which package this server hands out. Everything is
counted, never listed: the page shows numbers, and Admin Logs holds the trail.

"Today" is the current UTC day, the same window Admin Logs counts by, so the
two agree.
"""

from __future__ import annotations

import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extension import ExtensionEvent
from app.models.user import User
from app.services.extension_agent import EVENT_AGENT_STEP, EVENT_AGENT_TASK
from app.services.extension_settings import ExtensionSettings
from app.services.extension_tokens import open_sessions

#: Outcomes of a step the rules refused or the user denied.
_REFUSED_OUTCOMES = ("blocked", "denied")


def _start_of_today() -> datetime.datetime:
    now = datetime.datetime.now(datetime.UTC)
    return datetime.datetime(now.year, now.month, now.day)


async def _browsers(db: AsyncSession, latest_version: str | None) -> dict[str, int]:
    """Connected browsers, and how many run a package older than the one on offer.

    A session whose owner signed out everywhere since is not connected any
    more, so the owner's token version is checked here rather than in SQL.
    """
    rows = await open_sessions(db)
    if not rows:
        return {"connected": 0, "outdated": 0, "unknown_version": 0}
    owners = {
        int(user_id): int(version or 0)
        for user_id, version in (
            await db.execute(select(User.id, User.token_version).where(User.id.in_({int(r.user_id) for r in rows})))
        ).all()
    }
    live = [r for r in rows if int(r.token_version or 0) >= owners.get(int(r.user_id), 0)]
    outdated = 0
    unknown = 0
    for row in live:
        reported = str(row.extension_version or "")
        if not reported:
            unknown += 1
        elif latest_version and _older(reported, latest_version):
            outdated += 1
    return {"connected": len(live), "outdated": outdated, "unknown_version": unknown}


def _parts(version: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in version.split("."):
        try:
            out.append(int(part))
        except ValueError:
            return ()
    return tuple(out)


def _older(reported: str, latest: str) -> bool:
    """Whether ``reported`` is behind ``latest``; unreadable versions are not called old."""
    left, right = _parts(reported), _parts(latest)
    if not left or not right:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) < right + (0,) * (width - len(right))


async def _today(db: AsyncSession) -> dict[str, int]:
    since = _start_of_today()
    runs = await db.scalar(
        select(func.count())
        .select_from(ExtensionEvent)
        .where(ExtensionEvent.kind == EVENT_AGENT_TASK, ExtensionEvent.created_at >= since)
    )
    refused = await db.scalar(
        select(func.count())
        .select_from(ExtensionEvent)
        .where(
            ExtensionEvent.kind == EVENT_AGENT_STEP,
            ExtensionEvent.created_at >= since,
            ExtensionEvent.outcome.in_(_REFUSED_OUTCOMES),
        )
    )
    return {"agent_runs": int(runs or 0), "actions_refused": int(refused or 0)}


async def extension_overview(
    db: AsyncSession, settings: ExtensionSettings, *, package_version: str | None
) -> dict[str, object]:
    """The tiles, as the admin page shows them."""
    return {
        "enabled": bool(settings.enabled),
        "full_control": bool(settings.full_control),
        "package_version": package_version,
        "browsers": await _browsers(db, package_version),
        "today": await _today(db),
        "stop_runs_before": settings.stop_runs_before,
    }
