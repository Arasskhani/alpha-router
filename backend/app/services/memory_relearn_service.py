"""Read the last days of chats again for memory: the administrator's catch-up after the window bug.

Extraction used to keep the newest 24,000 characters of a job's stretch and
drop the rest, while marking the whole stretch as mined. What it dropped is
still in the chats. This reads the chats of the last ``days`` again, from
their first message in that time, through the ordinary extraction jobs: the
same gates, the same monthly cap, the same suppressions, part by part.

It is run by hand, only while the administrator's switch for it is on (off
by default), and never reads what the person did not agree to be learned
from:

- only chats of people (and projects) with automatic learning on now, never
  a private chat or a members' channel;
- nothing said before a person's last "Delete all memories", or a project's
  last clearing of what it learned;
- nothing said before a person last changed their settings: their switch has
  no history, and they may have turned learning off and on again then. A
  project's settings do have one, so a project is read from when learning
  was last turned back on.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import (
    CHANNEL_KIND_MEMBER,
    ChatMessage,
    ChatSession,
    UserChatPrefs,
    UserMemoryEvent,
    UserMemoryJob,
)
from app.models.project import (
    PROJECT_STATUS_ACTIVE,
    Project,
    ProjectConfigVersion,
    ProjectMemoryEvent,
    ProjectMemoryJob,
)
from app.models.user import User
from app.services.memory_extraction_service import CONTEXT_CHARS, MAX_MESSAGE_CHARS, MAX_WINDOW_CHARS
from app.services.memory_settings_service import get_memory_settings
from app.services.outbox_service import enqueue_outbox_event
from app.services.user_chat_storage_service import _normalize_prefs

MAX_DAYS = 90
#: What every part sends besides the chat: the rules and the existing memories.
PROMPT_OVERHEAD_CHARS = 4_000
#: A rough mean for Persian and English text alike.
CHARS_PER_TOKEN = 3
ANSWER_TOKENS_PER_PART = 400
#: Jobs start this far apart, so a catch-up does not take the worker from everyone else at once.
STAGGER_SECONDS = 3


class RelearnUnavailable(RuntimeError):
    """The switch is off, or there is no extraction model to read with."""


@dataclass
class RelearnChat:
    scope: str  # "user" | "project"
    owner: Any  # user id or project id
    session_id: str
    first: int  # the first sequence to read
    last: int  # the last
    messages: int
    characters: int

    @property
    def parts(self) -> int:
        return max(1, math.ceil(self.characters / (MAX_WINDOW_CHARS - CONTEXT_CHARS)))


@dataclass
class RelearnPlan:
    days: int
    chats: list[RelearnChat] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "days": self.days,
            "chats": {scope: sum(1 for c in self.chats if c.scope == scope) for scope in ("user", "project")},
            "messages": sum(c.messages for c in self.chats),
            "characters": sum(c.characters for c in self.chats),
            "parts": sum(c.parts for c in self.chats),
        }


def _moment(value: Any) -> dt.datetime | None:
    return value if isinstance(value, dt.datetime) else None


def _days(days: int) -> int:
    return max(1, min(MAX_DAYS, int(days)))


async def _aggregates(db: AsyncSession, session_ids: list[str], since: dt.datetime) -> dict[str, tuple[int, ...]]:
    """(first, last, messages, characters) per chat, over its turns since ``since``."""
    if not session_ids:
        return {}
    length = func.length(ChatMessage.content)
    capped = case((length > MAX_MESSAGE_CHARS, MAX_MESSAGE_CHARS), else_=length)
    rows = (
        await db.execute(
            select(
                ChatMessage.session_id,
                func.min(ChatMessage.sequence),
                func.max(ChatMessage.sequence),
                func.count(),
                func.coalesce(func.sum(capped), 0),
            )
            .where(
                ChatMessage.session_id.in_(session_ids),
                ChatMessage.created_at >= since,
                ChatMessage.role.in_(("user", "assistant")),
            )
            .group_by(ChatMessage.session_id)
        )
    ).all()
    return {str(sid): (int(first), int(last), int(count), int(chars)) for sid, first, last, count, chars in rows}


async def _personal_bounds(db: AsyncSession, user_ids: set[int]) -> dict[int, dt.datetime | None]:
    """Per person: the time before which nothing is read again (their last delete-all or settings change)."""
    if not user_ids:
        return {}
    bounds: dict[int, dt.datetime | None] = {}
    prefs = (
        await db.execute(
            select(UserChatPrefs.user_id, UserChatPrefs.updated_at, UserChatPrefs.prefs).where(
                UserChatPrefs.user_id.in_(user_ids)
            )
        )
    ).all()
    learning_off: set[int] = set()
    for user_id, updated_at, values in prefs:
        if not _normalize_prefs(values if isinstance(values, dict) else {}).get("memory_auto_capture", True):
            learning_off.add(int(user_id))
        bounds[int(user_id)] = updated_at
    wipes = (
        await db.execute(
            select(UserMemoryEvent.user_id, UserMemoryEvent.created_at, UserMemoryEvent.detail).where(
                UserMemoryEvent.user_id.in_(user_ids),
                UserMemoryEvent.event_type == "purged",
                UserMemoryEvent.actor.in_(("user", "admin")),
            )
        )
    ).all()
    for user_id, created_at, detail in wipes:
        if isinstance(detail, dict) and detail.get("scope") == "all":
            current = bounds.get(int(user_id))
            bounds[int(user_id)] = created_at if current is None else max(current, created_at)
    for user_id in learning_off:
        bounds.pop(user_id, None)
    return {user_id: bounds.get(user_id) for user_id in user_ids if user_id not in learning_off}


async def _project_bounds(db: AsyncSession, project_ids: set[str]) -> dict[str, dt.datetime | None]:
    """Per project with learning on: the time before which nothing is read again."""
    bounds: dict[str, dt.datetime | None] = {}
    for project_id in sorted(project_ids):
        project = await db.get(Project, project_id)
        if project is None or str(project.status) != PROJECT_STATUS_ACTIVE:
            continue
        versions = (
            (
                await db.execute(
                    select(ProjectConfigVersion)
                    .where(ProjectConfigVersion.project_id == project_id)
                    .order_by(ProjectConfigVersion.revision.asc())
                )
            )
            .scalars()
            .all()
        )
        active = next((v for v in versions if v.id == project.active_config_version_id), None)
        if active is not None and not (active.memory_enabled and active.memory_auto_capture):
            continue
        on_since: dt.datetime | None = None
        was_off = False
        for version in versions:
            off = not (version.memory_enabled and version.memory_auto_capture)
            if off:
                was_off, on_since = True, None
            elif was_off and on_since is None:
                on_since = _moment(version.created_at)
            if active is not None and version.id == active.id:
                break
        cleared = (
            await db.execute(
                select(func.max(ProjectMemoryEvent.created_at)).where(
                    ProjectMemoryEvent.project_id == project_id,
                    ProjectMemoryEvent.event_type == "deleted_all_auto",
                )
            )
        ).scalar_one_or_none()
        candidates = [moment for moment in (on_since, cleared) if moment is not None]
        bounds[project_id] = max(candidates) if candidates else None
    return bounds


async def plan_relearn(db: AsyncSession, *, days: int, now: dt.datetime | None = None) -> RelearnPlan:
    """Which chats would be read again, from where, and how much."""
    days = _days(days)
    current = now or dt.datetime.utcnow()
    since = current - dt.timedelta(days=days)
    settings = await get_memory_settings(db)
    active_chats = (
        select(ChatMessage.session_id)
        .where(ChatMessage.created_at >= since, ChatMessage.role.in_(("user", "assistant")))
        .distinct()
    )
    sessions = (
        await db.execute(
            select(ChatSession.id, ChatSession.user_id, ChatSession.project_id, User.is_active)
            .join(User, User.id == ChatSession.user_id)
            .where(
                ChatSession.id.in_(active_chats),
                ChatSession.private_mode.is_(False),
                (ChatSession.channel_kind.is_(None)) | (ChatSession.channel_kind != CHANNEL_KIND_MEMBER),
            )
        )
    ).all()
    personal = [(str(sid), int(uid)) for sid, uid, pid, active in sessions if not pid and active]
    project = (
        [(str(sid), str(pid)) for sid, _uid, pid, _active in sessions if pid]
        if settings.get("project_feature_enabled", True)
        else []
    )
    personal_bounds = await _personal_bounds(db, {uid for _sid, uid in personal})
    project_bounds = await _project_bounds(db, {pid for _sid, pid in project})

    plan = RelearnPlan(days=days)
    wanted: list[tuple[str, Any, str, dt.datetime]] = []
    for sid, uid in personal:
        if uid in personal_bounds:
            bound = personal_bounds[uid]
            wanted.append(("user", uid, sid, max(since, bound) if bound else since))
    for sid, pid in project:
        if pid in project_bounds:
            bound = project_bounds[pid]
            wanted.append(("project", pid, sid, max(since, bound) if bound else since))
    by_since: dict[dt.datetime, list[str]] = {}
    for _scope, _owner, sid, start in wanted:
        by_since.setdefault(start, []).append(sid)
    figures: dict[str, tuple[int, ...]] = {}
    for start, ids in by_since.items():
        figures.update(await _aggregates(db, ids, start))
    for scope, owner, sid, _start in wanted:
        if sid in figures:
            first, last, count, chars = figures[sid]
            plan.chats.append(RelearnChat(scope, owner, sid, first, last, count, chars))
    return plan


async def _quote(db: AsyncSession, plan: RelearnPlan, model_id: int | None) -> float | None:
    """Roughly what the plan costs on the extraction model; None when that model has no price."""
    if not plan.chats:
        return 0.0
    if not model_id:
        return None
    from app.models.model_catalog import AIModel
    from app.services.usage_accounting_service import quote_hold

    ai_model = await db.get(AIModel, int(model_id))
    if ai_model is None:
        return None
    figures = plan.summary()
    prompt_tokens = (figures["characters"] + figures["parts"] * PROMPT_OVERHEAD_CHARS) // CHARS_PER_TOKEN
    quote = await quote_hold(
        db,
        service_type="llm",
        ai_model=ai_model,
        provider_type=getattr(ai_model, "provider_type", None),
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(figures["parts"] * ANSWER_TOKENS_PER_PART),
    )
    return float(quote.quoted_usd) if quote.priced and quote.quoted_usd is not None else None


async def estimate_relearn(db: AsyncSession, *, days: int) -> dict[str, Any]:
    """What reading the last ``days`` again would take: chats, messages, parts, and roughly what it costs."""
    from app.services.memory_extraction_service import extraction_spend_this_month

    settings = await get_memory_settings(db)
    plan = await plan_relearn(db, days=days)
    return {
        "enabled": bool(settings.get("relearn_enabled")),
        "model_configured": bool(settings.get("extraction_model_id")),
        **plan.summary(),
        "estimated_cost_usd": await _quote(db, plan, settings.get("extraction_model_id")),
        "spent_this_month_usd": await extraction_spend_this_month(db),
        "monthly_cap_usd": float(settings.get("extract_monthly_budget_usd") or 0.0),
    }


async def _open_job(db: AsyncSession, model: Any, chat: RelearnChat) -> Any | None:
    owner = model.user_id if chat.scope == "user" else model.project_id
    return (
        (
            await db.execute(
                select(model).where(
                    owner == chat.owner,
                    model.session_id == chat.session_id,
                    model.status.in_(("pending", "retry")),
                )
            )
        )
        .scalars()
        .first()
    )


async def start_relearn(db: AsyncSession, *, days: int) -> dict[str, Any]:
    """Queue the chats of the last ``days`` to be read again; each through an ordinary extraction job.

    A chat with an open job already has that job start earlier instead, so
    one chat never has two.
    """
    from app.config import get_settings

    settings = await get_memory_settings(db)
    if not settings.get("relearn_enabled"):
        raise RelearnUnavailable("Relearning from recent chats is switched off in Admin -> Memory")
    if (
        not settings.get("feature_enabled", True)
        or not settings.get("extraction_model_id")
        or not get_settings().memory_extract_enabled
    ):
        raise RelearnUnavailable("Automatic memory has no extraction model to read with")
    plan = await plan_relearn(db, days=days)
    now = dt.datetime.utcnow()
    counts = {"queued": 0, "merged": 0}
    for index, chat in enumerate(plan.chats):
        model: Any = UserMemoryJob if chat.scope == "user" else ProjectMemoryJob
        start_after = max(0, chat.first - 1)
        open_job = await _open_job(db, model, chat)
        if open_job is not None:
            open_job.extracted_sequence = min(int(open_job.extracted_sequence or 0), start_after)
            open_job.watermark_sequence = max(int(open_job.watermark_sequence or 0), chat.last)
            open_job.updated_at = now
            counts["merged"] += 1
            continue
        run_after = now + dt.timedelta(seconds=index * STAGGER_SECONDS)
        owner = {"user_id": chat.owner} if chat.scope == "user" else {"project_id": chat.owner}
        job = model(
            id=str(uuid.uuid4()),
            **owner,
            session_id=chat.session_id,
            status="pending",
            watermark_sequence=chat.last,
            extracted_sequence=start_after,
            run_after=run_after,
            attempt_count=0,
            max_attempts=get_settings().memory_job_max_attempts,
            created_at=now,
            updated_at=now,
        )
        try:
            async with db.begin_nested():
                db.add(job)
                await db.flush()
        except IntegrityError:
            # The person spoke a moment ago and an open job was made: have it start earlier.
            open_job = await _open_job(db, model, chat)
            if open_job is not None:
                open_job.extracted_sequence = min(int(open_job.extracted_sequence or 0), start_after)
                open_job.watermark_sequence = max(int(open_job.watermark_sequence or 0), chat.last)
                open_job.updated_at = now
                counts["merged"] += 1
            continue
        if chat.scope == "user":
            aggregate, event, prefix = "user_memory_job", "memory.job.ready", "user-memory"
        else:
            from app.services.project_memory_job_service import AGGREGATE_TYPE, EVENT_TYPE

            aggregate, event, prefix = AGGREGATE_TYPE, EVENT_TYPE, "project-memory"
        await enqueue_outbox_event(
            db,
            aggregate_type=aggregate,
            aggregate_id=job.id,
            event_type=event,
            payload={"job_id": job.id, "attempt": 0},
            idempotency_key=f"{prefix}:{job.id}:dispatch:0:relearn",
            available_at=run_after,
        )
        counts["queued"] += 1
    await db.flush()
    return {**plan.summary(), **counts}
