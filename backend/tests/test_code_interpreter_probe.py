"""Active Code Interpreter probes: end-to-end pass/fail classification."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services import code_interpreter_probe_service as probe_service
from app.services.code_interpreter_service import SandboxArtifact, SandboxExecutionResult
from app.services.model_tool_compatibility_service import (
    STATUS_COMPATIBLE,
    STATUS_INCOMPATIBLE,
    get_compatibility,
)


def _completion(content: str, model: str = "vendor/model") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        model=model,
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
    )


def _passing_execution() -> SandboxExecutionResult:
    payload = json.dumps({"total": 3}).encode("utf-8")
    return SandboxExecutionResult(
        output=f"{probe_service.PROBE_SENTINEL}\n",
        exit_code=0,
        artifacts=(
            SandboxArtifact(
                name="probe.json",
                mime_type="application/json",
                size_bytes=len(payload),
                sha256="0" * 64,
                content=payload,
            ),
        ),
    )


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _seed(db: AsyncSession, external_id: str) -> tuple[Connection, AIModel]:
    connection = Connection(
        name="openrouter",
        provider_type="openrouter",
        api_key_encrypted="enc",
        is_active=True,
    )
    db.add(connection)
    await db.flush()
    model = AIModel(
        connection_id=connection.id,
        external_id=external_id,
        display_name=external_id,
        provider_type="openrouter",
        is_enabled=True,
        admin_disabled=False,
    )
    db.add(model)
    await db.flush()
    await db.commit()
    return connection, model


async def _run_probe(
    external_id: str,
    completions: list[SimpleNamespace],
    execution: SandboxExecutionResult | None,
):
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection, model = await _seed(db, external_id)

            calls: list[dict] = []

            async def fake_acompletion(**kwargs):
                calls.append(dict(kwargs))
                if not completions:
                    raise AssertionError("probe requested more completions than expected")
                return completions.pop(0)

            async def fake_sandbox(code, files):
                del code, files
                if execution is None:
                    raise ValueError("blocked import")
                return execution

            with (
                patch.object(probe_service, "acompletion", side_effect=fake_acompletion),
                patch.object(probe_service, "run_python_sandbox", side_effect=fake_sandbox),
                patch.object(probe_service, "decrypt_secret", return_value="sk-test"),
                patch.object(
                    probe_service,
                    "persist_usage_operation",
                    AsyncMock(return_value=None),
                ),
            ):
                result = await probe_service.probe_model_compatibility(db, model)

            row = await get_compatibility(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
            )
            return result, row, calls
    finally:
        await engine.dispose()


async def test_probe_marks_model_compatible_after_full_flow():
    result, row, calls = await _run_probe(
        "vendor/model",
        [
            _completion("```python\nprint('x')\n```"),
            _completion(probe_service.PROBE_FINISH_SENTINEL),
        ],
        _passing_execution(),
    )
    assert result.success is True
    assert row is not None and row.status == STATUS_COMPATIBLE
    assert row.total_successes == 1
    # Two turns: generate the code, then continue after execution.
    assert len(calls) == 2
    assert all(call["stream"] is False for call in calls)


async def test_probe_marks_model_incompatible_when_no_python_block():
    result, row, calls = await _run_probe(
        "vendor/prose-only",
        [_completion("I cannot run code, but the total is 3.")],
        _passing_execution(),
    )
    assert result.success is False
    assert result.reason_code == "no_python_block"
    assert row is not None and row.status == STATUS_INCOMPATIBLE
    assert row.next_probe_at is not None
    assert len(calls) == 1


async def test_probe_fails_when_sandbox_contract_is_not_met():
    result, row, _calls = await _run_probe(
        "vendor/bad-artifacts",
        [_completion("```python\nprint('nothing')\n```")],
        SandboxExecutionResult(output="done", exit_code=0, artifacts=()),
    )
    assert result.success is False
    assert result.reason_code == "sandbox_protocol_error"
    assert row is not None and row.status == STATUS_INCOMPATIBLE


async def test_probe_records_router_selected_model_separately():
    factory_result = await _run_auto_router_probe()
    result, rows = factory_result
    assert result.success is True
    assert rows["openrouter/auto"] == STATUS_COMPATIBLE
    # The concrete model chosen by the router is learned too.
    assert rows["vendor/selected"] == STATUS_COMPATIBLE


async def _run_auto_router_probe():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection, model = await _seed(db, "openrouter/auto")
            completions = [
                _completion(
                    "```python\nprint('x')\n```",
                    model="openrouter/vendor/selected",
                ),
                _completion(
                    probe_service.PROBE_FINISH_SENTINEL,
                    model="openrouter/vendor/selected",
                ),
            ]

            async def fake_acompletion(**kwargs):
                del kwargs
                return completions.pop(0)

            with (
                patch.object(probe_service, "acompletion", side_effect=fake_acompletion),
                patch.object(
                    probe_service,
                    "run_python_sandbox",
                    AsyncMock(return_value=_passing_execution()),
                ),
                patch.object(probe_service, "decrypt_secret", return_value="sk-test"),
                patch.object(
                    probe_service,
                    "persist_usage_operation",
                    AsyncMock(return_value=None),
                ),
            ):
                result = await probe_service.probe_model_compatibility(db, model)

            statuses: dict[str, str] = {}
            for external_id in ("openrouter/auto", "vendor/selected"):
                row = await get_compatibility(
                    db,
                    connection_id=connection.id,
                    external_model_id=external_id,
                )
                statuses[external_id] = row.status if row else "missing"
            return result, statuses
    finally:
        await engine.dispose()


async def test_due_probe_batch_is_claimed_once():
    await _run_claim_batch()


async def _run_claim_batch():
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            await _seed(db, "vendor/a")
            first = await probe_service.claim_due_probe_model_ids(db, limit=5)
            assert first, "a newly synced text model must become probe-eligible"
            second = await probe_service.claim_due_probe_model_ids(db, limit=5)
            # Claimed rows are pushed out to avoid duplicate paid probes.
            assert second == []
    finally:
        await engine.dispose()
