"""The limits an administrator puts on the browser agent's runs, checked at each step.

Every step of a run is one ``/api/chat/completions`` call from a connected
browser, carrying the run's start time; the extension enforces the same
limits itself, and the server checks again what it can see, so that an old or
altered extension cannot outlast them:

- the run's time limit, from its start time;
- runs per person per day, from the runs recorded in Admin Logs;
- the package: with "require the newest package" on, a browser that reports an
  older version - or none - gets no agent step;
- data location: screenshots only to a model that may see them, and pages of
  an internal site only to a model inside the organisation.

A refusal is a ``PageContextRefused``, as the model checks raise, so the chat
API turns them all into the same kind of answer.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extension import ExtensionEvent, ExtensionSession
from app.models.model_catalog import AIModel
from app.services.extension_page_context import PageContextRefused
from app.services.extension_settings import (
    ExtensionSettings,
    inside_organisation,
    internal_site,
    normalize_page_host,
    screenshot_allowed,
)

#: The event kind a finished run is recorded as (extension_agent.EVENT_AGENT_TASK, without the import cycle).
AGENT_TASK_KIND = "agent_task"

#: A run may take this much longer than its limit before the server refuses
#: its steps: the extension ends the run at the limit, and clocks differ a little.
RUN_TIME_GRACE = datetime.timedelta(minutes=2)

#: The page tags the extension wraps page content in, with the site they name.
_PAGE_TAG_RE = re.compile(r"<untrusted_page_content_[A-Za-z0-9]+ site=\"([^\"]{0,253})\">")


def start_of_today() -> datetime.datetime:
    """The start of the current UTC day, naive, as the event rows are stamped."""
    now = datetime.datetime.now(datetime.UTC)
    return datetime.datetime(now.year, now.month, now.day)


def version_parts(version: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in version.split("."):
        try:
            out.append(int(part))
        except ValueError:
            return ()
    return tuple(out)


def older_version(reported: str, latest: str) -> bool:
    """Whether ``reported`` is behind ``latest``; unreadable versions are not called old."""
    left, right = version_parts(reported), version_parts(latest)
    if not left or not right:
        return False
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) < right + (0,) * (width - len(right))


def check_run_time(
    settings: ExtensionSettings, run_started_at: int | None, *, now: datetime.datetime | None = None
) -> None:
    """Refuse a step of a run past its time limit; raises PageContextRefused.

    A step that does not say when its run began is not judged here: the stop
    check already refuses it.
    """
    if run_started_at is None:
        return
    began = datetime.datetime.fromtimestamp(run_started_at / 1000, tz=datetime.UTC)
    limit = datetime.timedelta(minutes=int(settings.agent_max_minutes)) + RUN_TIME_GRACE
    if (now or datetime.datetime.now(datetime.UTC)) - began > limit:
        raise PageContextRefused(
            403,
            "run_too_long",
            f"This run has passed your administrator's limit of {settings.agent_max_minutes} minutes. Start a new one.",
        )


async def runs_today(db: AsyncSession, user_id: int) -> int:
    """How many runs this person finished today (each is one agent_task row)."""
    count = await db.scalar(
        select(func.count())
        .select_from(ExtensionEvent)
        .where(
            ExtensionEvent.kind == AGENT_TASK_KIND,
            ExtensionEvent.actor_user_id == int(user_id),
            ExtensionEvent.created_at >= start_of_today(),
        )
    )
    return int(count or 0)


async def check_daily_runs(db: AsyncSession, settings: ExtensionSettings, user_id: int) -> None:
    """Refuse every step once the person has used up today's runs; raises PageContextRefused.

    A run counts when it ends, so the run that reaches the limit finishes; the
    next one gets no step.
    """
    limit = settings.agent_runs_per_day
    if limit is None:
        return
    if await runs_today(db, user_id) >= int(limit):
        raise PageContextRefused(
            403,
            "daily_runs_reached",
            f"You have used today's {limit} agent runs, your administrator's limit. Try again tomorrow.",
        )


async def check_package_version(
    db: AsyncSession, settings: ExtensionSettings, session_id: str | None, latest_version: str | None
) -> None:
    """With "require the newest package" on, refuse a browser on an older package; raises PageContextRefused.

    A browser that never said which package it runs is treated as older: the
    versions before this field never reported one. Without a package to
    compare with (none built), nothing is refused.
    """
    if not settings.require_newest_package or not latest_version or not session_id:
        return
    session = await db.get(ExtensionSession, session_id)
    reported = str(session.extension_version or "") if session is not None else ""
    if not reported or older_version(reported, latest_version):
        raise PageContextRefused(
            403,
            "package_outdated",
            f"Your administrator requires the newest extension package ({latest_version}) for the agent. "
            "Download it from Settings → Extension and load it again.",
        )


def page_sites(messages: list[dict[str, Any]]) -> set[str]:
    """The sites the step's page content came from, as the extension's tags name them."""
    found: set[str] = set()
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(
                str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        for text in texts:
            for raw in _PAGE_TAG_RE.findall(text):
                try:
                    found.add(normalize_page_host(raw))
                except ValueError:
                    continue
    return found


def check_data_location(
    settings: ExtensionSettings, model: AIModel | None, messages: list[dict[str, Any]], *, has_images: bool
) -> None:
    """Refuse a step that would send what this model may not see; raises PageContextRefused.

    The extension keeps to the same rules; this is the server reading the step
    it was sent - the sites its page content names, and whether it carries
    screenshots - and refusing what those rules do not allow.
    """
    ref = f"model::{model.id}" if model is not None else None
    connection = int(model.connection_id) if model is not None and model.connection_id is not None else None
    if has_images and not screenshot_allowed(settings, ref, None, connection_id=connection):
        raise PageContextRefused(
            403,
            "screenshots_not_allowed",
            "Your administrator does not allow screenshots to be sent to this model. Choose another model.",
        )
    for site in sorted(page_sites(messages)):
        if not internal_site(settings, site):
            continue
        if not inside_organisation(settings, ref, connection):
            raise PageContextRefused(
                403,
                "internal_site_not_allowed",
                f"Your administrator keeps {site} inside the organisation: this model may not see it.",
                site=site,
            )
        if has_images and not screenshot_allowed(settings, ref, site, connection_id=connection):
            raise PageContextRefused(
                403,
                "screenshots_not_allowed",
                f"Your administrator does not allow screenshots of {site} to be sent to this model.",
                site=site,
            )
