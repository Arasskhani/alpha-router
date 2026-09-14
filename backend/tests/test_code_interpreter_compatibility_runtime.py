"""Runtime learning: failures/successes feed the Code Interpreter registry."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import proxy_service, turn_settlement
from app.services.usage_accounting_service import NormalizedUsage


def _pending_event(raw_usage: dict, upstream_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        usage=NormalizedUsage(
            prompt_tokens=0,
            completion_tokens=0,
            cached_tokens=0,
            cache_write_tokens=0,
            reasoning_tokens=0,
            upstream_request_id=upstream_id,
            raw_usage=raw_usage,
        )
    )


def test_router_selected_model_is_extracted_from_usage():
    event = _pending_event({"model": "openrouter/vendor/selected"})
    assert proxy_service._usage_event_model_id(event) == "vendor/selected"

    nested = _pending_event({"primary": {}, "fallback": {"model": "vendor/fallback"}})
    assert proxy_service._usage_event_model_id(nested) == "vendor/fallback"

    assert proxy_service._usage_event_model_id(None) is None
    assert proxy_service._usage_event_model_id(_pending_event({})) is None


async def _run_empty_completion_records_failure() -> tuple[list[dict], list[dict]]:
    calls = 0
    seen_kwargs: list[dict] = []

    async def fake_acompletion(**kwargs):
        nonlocal calls
        calls += 1
        seen_kwargs.append(dict(kwargs))

        async def _gen():
            if False:
                yield None

        return _gen()

    request = MagicMock()
    request.client = SimpleNamespace(host="127.0.0.1")
    request.is_disconnected = AsyncMock(return_value=False)
    resolved = SimpleNamespace(
        ai_model=SimpleNamespace(
            provider_type="openrouter",
            input_cost_per_1k=0.001,
            output_cost_per_1k=0.002,
            external_id="openrouter/auto",
            display_name="Auto Router",
            connection_id=7,
        ),
        api_key="sk-test",
        base_url="https://example.com/v1",
        provider_type="openrouter",
        model_id="openrouter/auto",
    )

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)
    tools = SimpleNamespace(code_interpreter=True)
    recorded: list[dict] = []

    async def fake_record(_db, **kwargs):
        recorded.append(kwargs)

    async def fake_plugin(db, *, connection_id, requested_model_id):
        del db
        return {
            "id": "auto-router",
            "allowed_models": ["vendor/good"],
            "excluded_models": ["vendor/bad"],
        }

    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(turn_settlement, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(proxy_service, "parse_tools_config", return_value=tools),
        patch.object(
            proxy_service,
            "augment_messages_with_tools",
            AsyncMock(side_effect=lambda db, m, t, **_kwargs: m),
        ),
        patch.object(proxy_service, "apply_prompt_cache_breakpoints", side_effect=lambda m: m),
        patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(10, 0, 0)),
        patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0),
        patch.object(proxy_service, "log_usage", side_effect=AsyncMock()),
        patch.object(turn_settlement, "log_usage", side_effect=AsyncMock()),
        patch.object(proxy_service, "openrouter_auto_plugin", side_effect=fake_plugin),
        patch.object(proxy_service, "record_compatibility_result", side_effect=fake_record),
        patch.object(
            proxy_service,
            "_openrouter_generation_outcome",
            AsyncMock(
                return_value={
                    "model": "vendor/bad",
                    "native_finish_reason": "MALFORMED_FUNCTION_CALL",
                }
            ),
        ),
    ):
        async for _chunk in proxy_service.stream_chat(
            request,
            {
                "model": "openrouter/auto",
                "messages": [{"role": "user", "content": "Analyze data"}],
            },
            user_id=1,
            username="admin",
            source="alpha_router_chat",
            skip_budget=False,
            resolved=resolved,
        ):
            pass

    assert calls == 2
    return recorded, seen_kwargs


async def test_empty_code_interpreter_turn_records_selected_model_failure():
    recorded, seen_kwargs = await _run_empty_completion_records_failure()

    assert recorded, "runtime failures must be recorded for the registry"
    first = recorded[0]
    assert first["external_model_id"] == "vendor/bad"
    assert first["success"] is False
    assert first["reason_code"] == "malformed_function_call"
    assert first["source"] == "runtime"
    assert first["requested_model_id"] == "openrouter/auto"

    # Every attempt carries the adaptive, evidence-derived Auto Router plugin.
    assert all(
        kwargs["extra_body"]
        == {
            "plugins": [
                {
                    "id": "auto-router",
                    "allowed_models": ["vendor/good"],
                    "excluded_models": ["vendor/bad"],
                }
            ]
        }
        for kwargs in seen_kwargs
    )


async def _run_missing_connection_is_noop() -> dict | None:
    ai_model = SimpleNamespace(external_id="openrouter/auto")
    return await proxy_service._adaptive_openrouter_extra_body(ai_model)


async def test_models_without_connection_skip_adaptive_routing():
    assert await _run_missing_connection_is_noop() is None


async def _run_alias_evidence_is_dropped() -> list[dict]:
    """A router alias must never accumulate its own score."""
    recorded: list[dict] = []

    async def fake_record(_db, **kwargs):
        recorded.append(kwargs)

    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)
    ai_model = SimpleNamespace(external_id="openrouter/auto", connection_id=7)

    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(turn_settlement, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(proxy_service, "record_compatibility_result", side_effect=fake_record),
    ):
        for alias in ("openrouter/auto", "auto", "~openrouter/auto-beta"):
            await proxy_service._record_runtime_compatibility(
                ai_model=ai_model,
                external_model_id=alias,
                success=False,
                reason_code="no_python_block",
            )
        await proxy_service._record_runtime_compatibility(
            ai_model=ai_model,
            external_model_id="vendor/real",
            success=True,
        )
    return recorded


async def test_router_alias_evidence_is_not_recorded():
    recorded = await _run_alias_evidence_is_dropped()
    assert [r["external_model_id"] for r in recorded] == ["vendor/real"]


async def _run_success_resolves_concrete_model() -> list[dict]:
    """A router success is credited to the model the router actually picked."""
    recorded: list[dict] = []

    async def fake_record(**kwargs):
        recorded.append(kwargs)

    ai_model = SimpleNamespace(external_id="openrouter/auto", connection_id=7)
    event = _pending_event({"model": "openrouter/auto"}, upstream_id="gen-1")

    with (
        patch.object(proxy_service, "_record_runtime_compatibility", side_effect=fake_record),
        patch.object(
            proxy_service,
            "_openrouter_generation_outcome",
            AsyncMock(return_value={"model": "vendor/picked"}),
        ),
    ):
        await proxy_service._record_code_interpreter_success(
            ai_model=ai_model,
            provider="openrouter",
            base_url="https://example.com/v1",
            api_key="sk-test",
            event=event,
            observed_model_ids=set(),
        )
    return recorded


async def test_router_success_is_credited_to_selected_model():
    recorded = await _run_success_resolves_concrete_model()
    assert len(recorded) == 1
    assert recorded[0]["external_model_id"] == "vendor/picked"
    assert recorded[0]["success"] is True


def _chunk(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))],
        usage=None,
    )


async def _run_final_answer_after_execution() -> tuple[list[dict], int]:
    """Turn 1 runs code, turn 2 answers: that is success, not a failure."""
    turns = [
        "Here you go:\n```python\nprint(2 + 2)\n```",
        "The answer is 4.",
    ]
    calls = 0

    async def fake_acompletion(**kwargs):
        nonlocal calls
        del kwargs
        index = min(calls, len(turns) - 1)
        calls += 1

        async def _gen():
            yield _chunk(turns[index])

        return _gen()

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
    fake_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_db)
    fake_ctx.__aexit__ = AsyncMock(return_value=None)
    recorded: list[dict] = []

    async def fake_record(_db, **kwargs):
        recorded.append(kwargs)

    with (
        patch.object(proxy_service, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(turn_settlement, "AsyncSessionLocal", return_value=fake_ctx),
        patch.object(proxy_service, "parse_tools_config", return_value=SimpleNamespace(code_interpreter=True)),
        patch.object(
            proxy_service,
            "augment_messages_with_tools",
            AsyncMock(side_effect=lambda db, m, t, **_kwargs: m),
        ),
        patch.object(proxy_service, "apply_prompt_cache_breakpoints", side_effect=lambda m: m),
        patch.object(proxy_service, "acompletion", side_effect=fake_acompletion),
        patch.object(proxy_service, "_usage_from_stream_wrapper", return_value=(10, 5, 0)),
        patch.object(proxy_service, "_compute_token_cost_usd", return_value=0.0),
        patch.object(proxy_service, "log_usage", side_effect=AsyncMock()),
        patch.object(turn_settlement, "log_usage", side_effect=AsyncMock()),
        patch.object(proxy_service, "record_compatibility_result", side_effect=fake_record),
        patch.object(
            proxy_service,
            "run_python_sandbox",
            AsyncMock(return_value=proxy_service.SandboxExecutionResult(output="4", exit_code=0)),
        ),
        patch.object(proxy_service, "openrouter_auto_plugin", AsyncMock(return_value=None)),
    ):
        async for _chunk_out in proxy_service.stream_chat(
            request,
            {
                "model": "vendor/good",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
            },
            user_id=1,
            username="admin",
            source="alpha_router_chat",
            skip_budget=False,
            resolved=resolved,
        ):
            pass

        # Success bookkeeping is deliberately off the response path.
        pending = list(proxy_service._background_compatibility_tasks)
        if pending:
            await asyncio.gather(*pending)

    return recorded, calls


async def test_final_answer_after_code_execution_is_not_a_failure():
    recorded, calls = await _run_final_answer_after_execution()

    # No third call: a completed flow must not be nudged for more Python.
    assert calls == 2
    assert recorded, "the successful execution must be recorded"
    assert all(entry["success"] for entry in recorded), f"a completed flow must not record failures: {recorded}"
    assert {entry["external_model_id"] for entry in recorded} == {"vendor/good"}
