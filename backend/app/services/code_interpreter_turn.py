"""Code Interpreter step of a chat turn (Phase 4.1).

The sandbox part of ``stream_chat``: wait for the sandbox while honouring
Stop, turn the execution result into the text shown to the user and the
feedback message sent back to the model, and store generated files. Pure
orchestration helpers — the streaming loop still decides when to call them
and what to yield.

Collaborators that tests patch on ``proxy_service`` (``run_python_sandbox``,
``_persist_code_interpreter_artifacts``) are injected as callables so the
seam stays where it was.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.code_interpreter_service import (
    SandboxExecutionResult,
    code_interpreter_error_hint,
    format_code_output_for_chat,
)
from app.services.observability import increment

logger = logging.getLogger(__name__)

#: How often the sandbox wait re-checks whether the user pressed Stop.
SANDBOX_CANCEL_POLL_SECONDS = 0.4

#: Strong refs for fire-and-forget drains so the tasks are not GC'd early.
_background_tasks: set[asyncio.Task] = set()


@dataclass(slots=True)
class CodeInterpreterLoop:
    """Per-turn Code Interpreter bookkeeping."""

    max_iterations: int
    iterations: int = 0
    nudge_sent: bool = False
    executed: bool = False
    emitted_artifact_ids: set[int] = field(default_factory=set)
    observed_compatibility_models: set[str] = field(default_factory=set)

    @property
    def exhausted(self) -> bool:
        return self.iterations >= self.max_iterations


@dataclass(slots=True)
class CodeStepOutput:
    #: Markdown appended to the assistant message and streamed to the client.
    formatted: str
    #: The "tool result" user message the model continues from.
    feedback: str
    succeeded: bool


def abandon_task(task: asyncio.Task) -> None:
    """Cancel a task we no longer wait on and swallow its eventual result.

    Without draining it, asyncio logs "Task exception was never retrieved" once
    the abandoned sandbox call finishes or raises.
    """
    task.cancel()

    async def _drain() -> None:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    drain = asyncio.create_task(_drain())
    _background_tasks.add(drain)
    drain.add_done_callback(_background_tasks.discard)


async def run_sandbox_until_stopped(
    code: str,
    files: dict[str, str],
    *,
    sandbox_runner: Callable[[str, dict[str, str]], Coroutine[Any, Any, SandboxExecutionResult | str]],
    client_stopped: Callable[[], Awaitable[bool]],
) -> SandboxExecutionResult | str | None:
    """Run sandbox code, abandoning the wait as soon as the user stops.

    Returns ``None`` when the client stopped while the sandbox was still
    running. Cancelling the executor task invokes the broker Job DELETE path,
    which force-removes the active container.
    """
    task: asyncio.Task[SandboxExecutionResult | str] = asyncio.create_task(sandbox_runner(code, files))
    while True:
        done, _pending = await asyncio.wait({task}, timeout=SANDBOX_CANCEL_POLL_SECONDS)
        if task in done:
            return task.result()
        if await client_stopped():
            abandon_task(task)
            increment("code_interpreter_cancelled")
            return None


async def describe_code_step(
    exec_result: SandboxExecutionResult,
    *,
    loop: CodeInterpreterLoop,
    can_persist_artifacts: bool,
    persist_artifacts: Callable[[Sequence[Any]], Awaitable[Sequence[Any]]] | None,
    artifact_links_markdown: Callable[[list[Any]], str],
) -> CodeStepOutput:
    """Format one execution result for the user and for the model.

    ``persist_artifacts`` stores generated files in the user's Media library
    (only for persisted app chats); the returned records carry ``asset_id``,
    ``name`` and ``url``. Failure to store never fails the turn — the model
    is told not to invent download links instead.
    """
    formatted = format_code_output_for_chat(exec_result)
    artifact_context = ""
    if exec_result.artifacts:
        if can_persist_artifacts and persist_artifacts is not None:
            try:
                stored = await persist_artifacts(exec_result.artifacts)
                new_artifacts = [item for item in stored if item.asset_id not in loop.emitted_artifact_ids]
                loop.emitted_artifact_ids.update(item.asset_id for item in new_artifacts)
                formatted += artifact_links_markdown(new_artifacts)
                artifact_context = "Platform-stored artifacts (use only these exact download links):\n" + "\n".join(
                    f"- {item.name}: {item.url}" for item in stored
                )
            except Exception:
                logger.exception("Failed to persist code interpreter artifacts")
                artifact_context = "The generated files could not be stored in Media. Do not invent download links."
                formatted += "\n> Generated files could not be stored in Media. No download link was created.\n\n"
        else:
            artifact_context = (
                "This is not a persisted app chat, so generated files were not stored. Do not invent download links."
            )
            formatted += "\n> Generated files are not persisted for Private Mode or non-persisted API chats.\n\n"
    remediation = code_interpreter_error_hint(exec_result.output) if exec_result.exit_code != 0 else ""
    feedback = "\n\n".join(
        part
        for part in (
            exec_result.output,
            artifact_context,
            remediation,
            "Continue your reply to the user using these results. Do not repeat the same code unless necessary.",
        )
        if part
    )
    return CodeStepOutput(formatted=formatted, feedback=feedback, succeeded=exec_result.exit_code == 0)
