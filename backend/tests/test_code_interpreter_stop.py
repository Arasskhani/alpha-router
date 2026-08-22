"""Stop must interrupt a Code Interpreter turn, including mid-sandbox."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import proxy_service


def _chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
        usage=None,
    )


class _FakePersister:
    """Minimal persister whose cancel flag flips once the sandbox is running."""

    def __init__(self, cancel_when: asyncio.Event) -> None:
        self.cancel_when = cancel_when
        self.finalized: dict | None = None
        self.contents: list[str] = []

    async def prepare(self) -> None:
        return None

    async def on_content(self, content: str) -> None:
        self.contents.append(content)

    def schedule_content(self, content: str) -> None:
        self.contents.append(content)

    def peek_cancel_requested(self) -> bool:
        return self.cancel_when.is_set()

    def schedule_cancel_poll(self) -> None:
        return None

    async def is_cancel_requested(self, *, force: bool = False) -> bool:
        del force
        return self.cancel_when.is_set()

    def reset_persist_state(self) -> None:
        return None

    async def finalize(self, *, success: bool, error_message: str | None = None) -> None:
        self.finalized = {"success": success, "error_message": error_message}


async def _run_stop_during_sandbox() -> dict:
    sandbox_started = asyncio.Event()
    state = {"calls": 0, "sandbox_cancelled": False, "sandbox_finished": False}
    release_capacity = AsyncMock(return_value=True)

    async def fake_acompletion(**kwargs):
        del kwargs
        state["calls"] += 1

        async def _gen():
            yield _chunk("Working on it:\n```python\nprint(2 + 2)\n```")

        return _gen()

    async def slow_sandbox(code, files):
        del code, files
        sandbox_started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            state["sandbox_cancelled"] = True
            raise
        state["sandbox_finished"] = True
        return proxy_service.SandboxExecutionResult(output="4", exit_code=0)

    persister = _FakePersister(sandbox_started)

    request = MagicMock()
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = AsyncMock(return_value=False)
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            external_id="vendor/good",
            display_name="Good model",
            connection_id=7,
        ),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openrouter",
        model_id="vendor/good",
        code_interpreter_capacity_permit=SimpleNamespace(
            lease_id="lease-stop",
            subject="user:1",
        ),
    )

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(
            proxy_service,
            "parse_tools_config",
            return_value=SimpleNamespace(code_interpreter=True),
        ),
        patch.object(
            proxy_service,
            "augment_messages_with_tools",
            AsyncMock(side_effect=lambda db, m, t, **_kwargs: m),
        ),
        patch.object(proxy_service, "apply_prompt_cache_breakpoints", side_effect=lambda m: m),
        patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
        patch.object(proxy_service, "persister_from_body", return_value=persister),
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(10, 5, 0)),
        patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0),
        patch.object(proxy_service, "log_usage", side_effect=AsyncMock()),
        patch.object(proxy_service, "record_compatibility_result", side_effect=AsyncMock()),
        patch.object(
            proxy_service,
            "release_code_interpreter_turn",
            release_capacity,
        ),
        patch.object(proxy_service, "run_python_sandbox", side_effect=slow_sandbox),
        patch.object(proxy_service, "openrouter_auto_plugin", AsyncMock(return_value=None)),
    ):
        chunks = []
        async for chunk in proxy_service.stream_chat(
            request,
            {
                "model": "vendor/good",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
                "persist_chat": True,
                "chat_session_id": "s1",
            },
            user_id=1,
            username="admin",
            source="alpha_router_chat",
            skip_budget=False,
            resolved=resolved,
        ):
            chunks.append(chunk)

        pending = list(proxy_service._background_compatibility_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    return {
        "calls": state["calls"],
        "sandbox_cancelled": state["sandbox_cancelled"],
        "sandbox_finished": state["sandbox_finished"],
        "finalized": persister.finalized,
        "chunks": b"".join(chunks).decode(),
        "capacity_release_calls": release_capacity.await_count,
    }


def test_stop_during_sandbox_interrupts_the_turn():
    result = asyncio.run(_run_stop_during_sandbox())

    # The turn must end at the sandbox: no follow-up completion is requested.
    assert result["calls"] == 1
    assert result["sandbox_cancelled"] is True
    assert result["sandbox_finished"] is False
    assert result["capacity_release_calls"] == 1
    # The abandoned sandbox output must never reach the chat.
    assert "Code output" not in result["chunks"]
    assert result["finalized"] is not None


async def _run_stop_before_sandbox() -> dict:
    state = {"calls": 0, "sandbox_calls": 0}
    already_cancelled = asyncio.Event()
    already_cancelled.set()

    async def fake_acompletion(**kwargs):
        del kwargs
        state["calls"] += 1

        async def _gen():
            yield _chunk("Sure:\n```python\nprint(1)\n```")

        return _gen()

    async def never_run_sandbox(code, files):
        del code, files
        state["sandbox_calls"] += 1
        return proxy_service.SandboxExecutionResult(output="1", exit_code=0)

    persister = _FakePersister(already_cancelled)

    request = MagicMock()
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = AsyncMock(return_value=False)
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            external_id="vendor/good",
            display_name="Good model",
            connection_id=7,
        ),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openrouter",
        model_id="vendor/good",
    )

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(
            proxy_service,
            "parse_tools_config",
            return_value=SimpleNamespace(code_interpreter=True),
        ),
        patch.object(
            proxy_service,
            "augment_messages_with_tools",
            AsyncMock(side_effect=lambda db, m, t, **_kwargs: m),
        ),
        patch.object(proxy_service, "apply_prompt_cache_breakpoints", side_effect=lambda m: m),
        patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
        patch.object(proxy_service, "persister_from_body", return_value=persister),
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(10, 5, 0)),
        patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0),
        patch.object(proxy_service, "log_usage", side_effect=AsyncMock()),
        patch.object(proxy_service, "record_compatibility_result", side_effect=AsyncMock()),
        patch.object(proxy_service, "run_python_sandbox", side_effect=never_run_sandbox),
        patch.object(proxy_service, "openrouter_auto_plugin", AsyncMock(return_value=None)),
    ):
        async for _chunk_out in proxy_service.stream_chat(
            request,
            {
                "model": "vendor/good",
                "messages": [{"role": "user", "content": "What is 1?"}],
                "persist_chat": True,
                "chat_session_id": "s1",
            },
            user_id=1,
            username="admin",
            source="alpha_router_chat",
            skip_budget=False,
            resolved=resolved,
        ):
            pass

    return state


def test_stop_before_sandbox_skips_execution_entirely():
    state = asyncio.run(_run_stop_before_sandbox())

    assert state["calls"] == 1
    assert state["sandbox_calls"] == 0


async def _run_partial_flush_stops_after_cancel() -> list[str]:
    """Once Stop lands, no partial flush may re-mark the row as streaming."""
    cancelled = asyncio.Event()

    async def fake_acompletion(**kwargs):
        del kwargs

        async def _gen():
            yield _chunk("first ")
            cancelled.set()
            yield _chunk("second ")
            yield _chunk("third")

        return _gen()

    persister = _FakePersister(cancelled)

    request = MagicMock()
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = AsyncMock(return_value=False)
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            external_id="vendor/good",
            display_name="Good model",
            connection_id=7,
        ),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openrouter",
        model_id="vendor/good",
    )

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(
            proxy_service,
            "parse_tools_config",
            return_value=SimpleNamespace(code_interpreter=False),
        ),
        patch.object(
            proxy_service,
            "augment_messages_with_tools",
            AsyncMock(side_effect=lambda db, m, t, **_kwargs: m),
        ),
        patch.object(proxy_service, "apply_prompt_cache_breakpoints", side_effect=lambda m: m),
        patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
        patch.object(proxy_service, "persister_from_body", return_value=persister),
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(10, 5, 0)),
        patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0),
        patch.object(proxy_service, "log_usage", side_effect=AsyncMock()),
        patch.object(proxy_service, "openrouter_auto_plugin", AsyncMock(return_value=None)),
    ):
        async for _chunk_out in proxy_service.stream_chat(
            request,
            {
                "model": "vendor/good",
                "messages": [{"role": "user", "content": "hi"}],
                "persist_chat": True,
                "chat_session_id": "s1",
            },
            user_id=1,
            username="admin",
            source="alpha_router_chat",
            skip_budget=False,
            resolved=resolved,
        ):
            pass

    return persister.contents


def test_no_partial_flush_after_cancel():
    contents = asyncio.run(_run_partial_flush_stops_after_cancel())

    assert contents == ["first "]
