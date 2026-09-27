"""A finished agent run, saved to the person's chat history.

The run's steps went to the model one call at a time and were never a chat;
what the person keeps is a chat of two messages - their task, and the agent's
answer with the list of what it did - so the run can be found again beside
their other conversations. Nothing a page said is in it: no page text, no
screenshots, nothing the agent typed; a step is its tool, what it was about
(the element's name at most), and how it ended.

Saving is the administrator's to allow (``save_runs``), and the person's to
decline for one run with a private run (``private_runs``), in which case the
panel never asks for it. Admin Logs has every run either way.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extension_settings import ExtensionSettings
from app.services.user_chat_storage_service import append_session_messages, create_chat_session

MAX_TASK_CHARS = 4000
MAX_SUMMARY_CHARS = 4000
MAX_STEPS = 200
MAX_STEP_CHARS = 200
MAX_TITLE_CHARS = 80

#: What the chat's tools field says, so the web app can tell a saved run from a conversation.
RUN_TOOLS = {"browser_agent": True}

OUTCOME_LABEL = {
    "done": "Finished",
    "stopped": "Stopped",
    "max_steps": "Stopped at the step limit",
    "max_minutes": "Stopped at the time limit",
    "errors": "Stopped after three failed steps in a row",
    "failed": "Could not go on",
}

STATUS_MARK = {
    "done": "done",
    "denied": "denied by you",
    "blocked": "refused by the rules",
    "skipped": "skipped",
    "error": "failed",
    "stopped": "stopped",
}


class RunNotSaved(Exception):
    """Why the run was not saved, in words the panel can show."""


@dataclass(frozen=True)
class RunStep:
    tool: str
    summary: str
    status: str
    detail: str | None = None


@dataclass(frozen=True)
class FinishedRun:
    task: str
    outcome: str
    summary: str
    steps: tuple[RunStep, ...]
    model: str | None
    mode: str | None
    duration_ms: int | None


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_title(task: str) -> str:
    """The chat's title: the task, cut to a sidebar's width."""
    return _clip(task, MAX_TITLE_CHARS) or "Browser agent run"


def run_answer(run: FinishedRun) -> str:
    """The assistant's message: how the run ended, what it said, and what it did, step by step."""
    lines = [f"**{OUTCOME_LABEL.get(run.outcome, 'Ended')}**"]
    if run.summary.strip():
        lines += ["", run.summary.strip()]
    if run.steps:
        lines += ["", f"**Steps ({len(run.steps)})**", ""]
        for index, step in enumerate(run.steps, 1):
            mark = STATUS_MARK.get(step.status, step.status)
            detail = f" - {step.detail}" if step.detail and step.status != "done" else ""
            lines.append(f"{index}. {step.summary or step.tool} - {mark}{detail}")
    if run.duration_ms is not None:
        minutes, seconds = divmod(max(0, int(run.duration_ms)) // 1000, 60)
        lines += ["", f"_{minutes} min {seconds} s{f', {run.mode} mode' if run.mode else ''}, in your browser._"]
    return "\n".join(lines)


async def save_run(db: AsyncSession, settings: ExtensionSettings, *, user_id: int, run: FinishedRun) -> str:
    """Save the run as a chat of the person's; the chat's id. Raises RunNotSaved when the administrator turned saving off."""
    if not settings.save_runs:
        raise RunNotSaved("Your administrator does not keep agent runs in chat history.")
    now = int(datetime.datetime.now(datetime.UTC).timestamp() * 1000)
    started = now - (run.duration_ms or 0)
    session = await create_chat_session(
        db,
        user_id,
        {
            "title": run_title(run.task),
            "model": run.model or "",
            "tools": dict(RUN_TOOLS),
            "toolsTouched": True,
            "createdAt": started,
            "updatedAt": now,
        },
    )
    await append_session_messages(
        db,
        user_id,
        str(session["id"]),
        [
            {"role": "user", "content": run.task, "modelId": run.model, "sentAt": started},
            {"role": "assistant", "content": run_answer(run), "modelId": run.model, "receivedAt": now},
        ],
    )
    return str(session["id"])
