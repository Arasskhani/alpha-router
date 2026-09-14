"""A cancelled or disconnected chat stream must still settle.

Starlette cancels ``StreamingResponse`` bodies through an anyio cancel scope
when the client disconnects. anyio re-delivers that cancellation at every
subsequent ``await`` until the scope exits, so an unshielded ``finally`` block
in ``stream_chat`` used to abort at its first await: the reservation stayed
held, no RequestLog was written and the persister never finalized. These tests
drive ``stream_chat`` under a real anyio task group (cancel path), through
``aclose()`` (GeneratorExit path) and through ``request.is_disconnected``
(early-break path) and assert settlement ran in all three.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from app.services import proxy_service


def _chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
        usage=None,
    )


class _FakePersister:
    def __init__(self) -> None:
        self.finalized: dict | None = None
        self.contents: list[str] = []

    async def prepare(self) -> None:
        return None

    def schedule_content(self, content: str) -> None:
        self.contents.append(content)

    def peek_cancel_requested(self) -> bool:
        return False

    def schedule_cancel_poll(self) -> None:
        return None

    async def is_cancel_requested(self, *, force: bool = False) -> bool:
        del force
        return False

    def reset_persist_state(self) -> None:
        return None

    async def finalize(self, *, success: bool, error_message: str | None = None) -> None:
        # A real finalize awaits the database; keep an await here so the
        # re-cancellation bug (if reintroduced) would trip on it.
        await asyncio.sleep(0)
        self.finalized = {"success": success, "error_message": error_message}


class _SlowProvider:
    """Async iterator yielding a chunk every few ms until closed."""

    def __init__(self, delay: float = 0.02) -> None:
        self.delay = delay
        self.yielded = 0
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        await asyncio.sleep(self.delay)
        self.yielded += 1
        return _chunk(f"tok{self.yielded} ")

    async def aclose(self) -> None:
        self.closed = True


def _resolved() -> SimpleNamespace:
    return SimpleNamespace(
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
            lease_id="lease-cancel",
            subject="user:1",
        ),
    )


def _patches(provider: _SlowProvider, persister: _FakePersister, log_usage: AsyncMock, release: AsyncMock):
    async def fake_acompletion(**kwargs):
        del kwargs
        return provider

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)

    return (
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
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(0, 0, 0)),
        patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0),
        patch.object(proxy_service, "log_usage", log_usage),
        patch.object(proxy_service, "record_compatibility_result", side_effect=AsyncMock()),
        patch.object(proxy_service, "release_code_interpreter_turn", release),
        patch.object(proxy_service, "openrouter_auto_plugin", AsyncMock(return_value=None)),
    )


def _body() -> dict:
    return {
        "model": "vendor/good",
        "messages": [{"role": "user", "content": "Write a long story"}],
        "persist_chat": True,
        "chat_session_id": "s1",
    }


def _request(disconnected: AsyncMock | None = None) -> MagicMock:
    request = MagicMock()
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = disconnected or AsyncMock(return_value=False)
    return request


def _enter_all(patches):
    from contextlib import ExitStack

    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


async def test_task_group_cancellation_still_settles() -> None:
    """Starlette-style cancel: anyio cancel scope around the consumer."""

    async def run() -> dict:
        provider = _SlowProvider()
        persister = _FakePersister()
        log_usage = AsyncMock(return_value=42)
        release = AsyncMock(return_value=True)
        chunks: list[bytes] = []
        consumer_error: BaseException | None = None

        async def consume() -> None:
            nonlocal consumer_error
            try:
                async for chunk in proxy_service.stream_chat(
                    _request(),
                    _body(),
                    user_id=1,
                    username="admin",
                    source="alpha_router_chat",
                    skip_budget=False,
                    resolved=_resolved(),
                ):
                    chunks.append(chunk)
            except BaseException as exc:  # noqa: BLE001 - we want to inspect it
                consumer_error = exc
                raise

        with _enter_all(_patches(provider, persister, log_usage, release)):
            async with anyio.create_task_group() as tg:
                tg.start_soon(consume)
                # Let a few chunks flow, then pull the plug like a disconnect.
                while len(chunks) < 3:
                    await asyncio.sleep(0.005)
                tg.cancel_scope.cancel()
            # Give any (wrongly) detached background work a moment.
            await asyncio.sleep(0.05)

        return {
            "log_usage_calls": log_usage.await_count,
            "finalized": persister.finalized,
            "release_calls": release.await_count,
            "output": b"".join(chunks).decode(),
            "log_kwargs": log_usage.await_args.kwargs if log_usage.await_args else {},
            "consumer_error": consumer_error,
        }

    result = await run()

    assert result["log_usage_calls"] == 1, "settlement must run once even when cancelled"
    assert result["finalized"] == {"success": False, "error_message": "Request cancelled"}
    assert result["release_calls"] == 1
    assert result["log_kwargs"]["success"] is False
    assert result["log_kwargs"]["error_message"] == "Request cancelled"
    assert "[DONE]" not in result["output"], "nothing may be yielded after cancellation"
    assert isinstance(result["consumer_error"], asyncio.CancelledError)


async def test_generator_aclose_still_settles() -> None:
    """ASGI server closes the generator (GeneratorExit path)."""

    async def run() -> dict:
        provider = _SlowProvider()
        persister = _FakePersister()
        log_usage = AsyncMock(return_value=42)
        release = AsyncMock(return_value=True)
        chunks: list[bytes] = []

        with _enter_all(_patches(provider, persister, log_usage, release)):
            agen = proxy_service.stream_chat(
                _request(),
                _body(),
                user_id=1,
                username="admin",
                source="alpha_router_chat",
                skip_budget=False,
                resolved=_resolved(),
            )
            async for chunk in agen:
                chunks.append(chunk)
                if len(chunks) >= 3:
                    break
            # Must not raise "async generator ignored GeneratorExit".
            await agen.aclose()

        return {
            "log_usage_calls": log_usage.await_count,
            "finalized": persister.finalized,
            "release_calls": release.await_count,
            "output": b"".join(chunks).decode(),
        }

    result = await run()

    assert result["log_usage_calls"] == 1
    assert result["finalized"] == {"success": False, "error_message": "Request cancelled"}
    assert result["release_calls"] == 1
    assert "[DONE]" not in result["output"]


async def test_detected_disconnect_stops_consuming_upstream() -> None:
    """request.is_disconnected() -> break out of the provider stream immediately."""

    async def run() -> dict:
        provider = _SlowProvider()
        persister = _FakePersister()
        log_usage = AsyncMock(return_value=42)
        release = AsyncMock(return_value=True)
        chunks: list[bytes] = []
        calls = {"n": 0}

        async def disconnected() -> bool:
            calls["n"] += 1
            return calls["n"] > 3

        with _enter_all(_patches(provider, persister, log_usage, release)):
            async for chunk in proxy_service.stream_chat(
                _request(AsyncMock(side_effect=disconnected)),
                _body(),
                user_id=1,
                username="admin",
                source="alpha_router_chat",
                skip_budget=False,
                resolved=_resolved(),
            ):
                chunks.append(chunk)

        return {
            "provider_yielded": provider.yielded,
            "provider_closed": provider.closed,
            "log_usage_calls": log_usage.await_count,
            "finalized": persister.finalized,
            "output": b"".join(chunks).decode(),
        }

    result = await run()

    # Without the early break the fake provider would be drained forever
    # (it never ends); a handful of chunks proves we stopped at the disconnect.
    assert result["provider_yielded"] <= 6
    assert result["provider_closed"] is True
    assert result["log_usage_calls"] == 1
    assert result["finalized"] is not None
    assert "[DONE]" not in result["output"]


@pytest.mark.parametrize("attr", ["aclose"])
async def test_close_upstream_stream_is_best_effort(attr: str) -> None:
    class Broken:
        async def aclose(self):
            raise RuntimeError("boom")

    await proxy_service._close_upstream_stream(Broken())
    await proxy_service._close_upstream_stream(object())
    await proxy_service._close_upstream_stream(None)
