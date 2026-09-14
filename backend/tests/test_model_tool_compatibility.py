"""Model-tool compatibility registry, circuit breaker, and Auto Router constraints."""

import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.connection import Connection
from app.models.model_catalog import (
    AIModel,
    ModelToolCompatibility,
    ModelToolCompatibilityEvent,
)
from app.services.model_tool_compatibility_service import (
    CODE_INTERPRETER_TOOL,
    STATUS_COMPATIBLE,
    STATUS_DEGRADED,
    STATUS_INCOMPATIBLE,
    STATUS_UNKNOWN,
    assert_code_interpreter_model_available,
    classify_failure_reason,
    compatibility_map_for_models,
    compatibility_payload,
    effective_status,
    ensure_model_compatibility_rows,
    get_compatibility,
    get_or_create_compatibility,
    is_auto_router_model_id,
    is_code_interpreter_candidate,
    openrouter_auto_plugin,
    prune_compatibility_events,
    record_compatibility_result,
    set_manual_override,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _connection(db: AsyncSession) -> Connection:
    connection = Connection(
        name="openrouter",
        provider_type="openrouter",
        api_key_encrypted="enc",
        is_active=True,
    )
    db.add(connection)
    await db.flush()
    return connection


async def _model(
    db: AsyncSession,
    connection: Connection,
    external_id: str,
    *,
    is_image_model: bool = False,
) -> AIModel:
    model = AIModel(
        connection_id=connection.id,
        external_id=external_id,
        display_name=external_id,
        provider_type="openrouter",
        is_enabled=True,
        admin_disabled=False,
        is_image_model=is_image_model,
    )
    db.add(model)
    await db.flush()
    return model


def test_auto_router_ids_are_detected():
    assert is_auto_router_model_id("openrouter/auto")
    assert is_auto_router_model_id("auto")
    assert is_auto_router_model_id("~openrouter/auto-beta")
    assert not is_auto_router_model_id("google/gemini-3.6-flash")


def test_failure_reasons_are_classified_without_vendor_names():
    assert classify_failure_reason("MALFORMED_FUNCTION_CALL") == "malformed_function_call"
    assert classify_failure_reason("Rate limit exceeded") == "provider_rate_limit"
    assert classify_failure_reason("Request timed out") == "provider_timeout"
    assert classify_failure_reason("no usable content") == "empty_content"
    assert classify_failure_reason("boom") == "provider_error"
    assert (
        classify_failure_reason(
            'NotFoundError - {"error":{"message":"This model is only available via the Batch API"}}'
        )
        == "model_unavailable"
    )
    assert classify_failure_reason("No endpoints found for this model") == "model_unavailable"
    assert classify_failure_reason("Service temporarily unavailable") == "provider_unavailable"


async def _run_inconclusive_probe_error_keeps_model() -> None:
    """One unclassified upstream error must not remove a model from the picker."""
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-flaky")
            await db.commit()

            row = await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=False,
                source="probe",
                detail="boom",
            )
            await db.commit()

            assert row.reason_code == "provider_error"
            assert row.status == STATUS_UNKNOWN
            assert row.quarantine_until is None
            assert compatibility_payload(row)["selectable"] is True
            await assert_code_interpreter_model_available(db, model)

            # Repeated unclassified failures eventually do hide the model.
            for _ in range(3):
                row = await record_compatibility_result(
                    db,
                    connection_id=connection.id,
                    external_model_id=model.external_id,
                    model_id=model.id,
                    success=False,
                    source="probe",
                    detail="boom",
                )
            await db.commit()

            assert row.status == STATUS_INCOMPATIBLE
            with pytest.raises(HTTPException):
                await assert_code_interpreter_model_available(db, model)
    finally:
        await engine.dispose()


async def test_inconclusive_provider_error_does_not_block_model():
    await _run_inconclusive_probe_error_keeps_model()


async def _run_transient_failure_keeps_verified_status() -> None:
    """A rate limit must not revoke a model that already passed the flow."""
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-verified")
            await db.commit()

            await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=True,
                source="probe",
            )
            row = await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=False,
                source="runtime",
                reason_code="provider_rate_limit",
                detail="429 rate limit",
            )
            await db.commit()

            assert row.status == STATUS_COMPATIBLE
            assert row.quarantine_until is None
            assert compatibility_payload(row)["selectable"] is True
            await assert_code_interpreter_model_available(db, model)
    finally:
        await engine.dispose()


async def test_transient_failure_keeps_verified_model_selectable():
    await _run_transient_failure_keeps_verified_status()


async def _run_unavailable_model_backs_off() -> None:
    """Batch-only / retired ids block, but are not re-probed every day."""
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-x:batch")
            await db.commit()

            row = await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=False,
                source="probe",
                detail='NotFoundError - {"error":{"message":"This model is only available via the Batch API"}}',
            )
            await db.commit()

            assert row.reason_code == "model_unavailable"
            assert row.status == STATUS_INCOMPATIBLE
            assert row.quarantine_until is None
            assert row.next_probe_at is not None
            assert row.next_probe_at > datetime.datetime.utcnow() + datetime.timedelta(days=6)
            with pytest.raises(HTTPException):
                await assert_code_interpreter_model_available(db, model)
    finally:
        await engine.dispose()


async def test_unavailable_model_is_blocked_with_long_backoff():
    await _run_unavailable_model_backs_off()


async def _run_override_is_audited() -> list[ModelToolCompatibilityEvent]:
    """An override outranks measurement, so it must leave an attributed trail."""
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-pinned")
            await db.commit()

            row = await get_or_create_compatibility(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
            )
            await set_manual_override(db, row, STATUS_INCOMPATIBLE, actor="alice")
            # Re-applying the same value must not add noise.
            await set_manual_override(db, row, STATUS_INCOMPATIBLE, actor="alice")
            await set_manual_override(db, row, None, actor="bob")
            await db.commit()

            return list(
                (
                    await db.execute(
                        select(ModelToolCompatibilityEvent)
                        .where(ModelToolCompatibilityEvent.compatibility_id == row.id)
                        .order_by(ModelToolCompatibilityEvent.id)
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()


async def test_manual_override_records_attributed_audit_trail():
    events = await _run_override_is_audited()

    assert [e.reason_code for e in events] == ["admin_force_block", "admin_auto"]
    assert all(e.source == "admin" for e in events)
    assert "alice" in (events[0].detail or "")
    assert "bob" in (events[1].detail or "")


def test_unknown_models_stay_selectable():
    payload = compatibility_payload(None)
    assert payload["status"] == STATUS_UNKNOWN
    assert payload["selectable"] is True
    assert payload["compatible"] is False


def test_non_text_models_are_not_candidates():
    image_model = AIModel(
        connection_id=1,
        external_id="black-forest-labs/flux",
        provider_type="openrouter",
        is_enabled=True,
        admin_disabled=False,
        is_image_model=True,
    )
    assert not is_code_interpreter_candidate(image_model)
    payload = compatibility_payload(None, static_candidate=False)
    assert payload["status"] == STATUS_INCOMPATIBLE
    assert payload["selectable"] is False


async def _run_hard_failure_quarantine() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-a")
            await db.commit()

            row = await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=False,
                source="runtime",
                reason_code="malformed_function_call",
                detail="MALFORMED_FUNCTION_CALL",
            )
            await db.commit()

            assert row.status == STATUS_DEGRADED
            assert row.quarantine_until is not None
            assert effective_status(row) == STATUS_DEGRADED
            assert row.score < 0.5

            with pytest.raises(HTTPException) as blocked:
                await assert_code_interpreter_model_available(db, model)
            assert blocked.value.status_code == 409

            events = (
                (
                    await db.execute(
                        select(ModelToolCompatibilityEvent).where(
                            ModelToolCompatibilityEvent.compatibility_id == row.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(events) == 1
            assert events[0].source == "runtime"
    finally:
        await engine.dispose()


async def test_hard_runtime_failure_quarantines_model():
    await _run_hard_failure_quarantine()


async def _run_success_recovers_model() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-b")
            await db.commit()

            await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=False,
                source="runtime",
                reason_code="no_python_block",
                detail="no python emitted",
            )
            row = await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=True,
                source="probe",
            )
            await db.commit()

            assert row.status == STATUS_COMPATIBLE
            assert row.quarantine_until is None
            assert row.consecutive_failures == 0
            assert row.next_probe_at is not None
            # A verified model must not be blocked at request time.
            await assert_code_interpreter_model_available(db, model)
    finally:
        await engine.dispose()


async def test_success_clears_quarantine_and_marks_compatible():
    await _run_success_recovers_model()


async def _run_transient_failure_is_soft() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-c")
            await db.commit()

            row = await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=False,
                source="runtime",
                reason_code="provider_rate_limit",
                detail="429 rate limit",
            )
            await db.commit()

            assert row.status == STATUS_UNKNOWN
            assert row.quarantine_until is None
            # Transient provider issues must not hide a model from users.
            await assert_code_interpreter_model_available(db, model)
    finally:
        await engine.dispose()


async def test_transient_failure_does_not_block_model():
    await _run_transient_failure_is_soft()


async def _run_manual_override() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-d")
            await db.commit()

            row = await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=False,
                source="probe",
                reason_code="malformed_function_call",
                detail="probe failed",
            )
            assert effective_status(row) == STATUS_INCOMPATIBLE

            await set_manual_override(db, row, "compatible")
            await db.commit()
            assert effective_status(row) == STATUS_COMPATIBLE
            await assert_code_interpreter_model_available(db, model)

            await set_manual_override(db, row, "incompatible")
            await db.commit()
            assert effective_status(row) == STATUS_INCOMPATIBLE

            await set_manual_override(db, row, None)
            await db.commit()
            assert effective_status(row) == STATUS_INCOMPATIBLE

            with pytest.raises(ValueError):
                await set_manual_override(db, row, "maybe")
    finally:
        await engine.dispose()


async def test_manual_override_wins_over_measurements():
    await _run_manual_override()


async def _run_auto_router_plugin() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            auto = await _model(db, connection, "openrouter/auto")
            good = await _model(db, connection, "vendor/good")
            bad = await _model(db, connection, "vendor/bad")
            await db.commit()

            await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=good.external_id,
                model_id=good.id,
                success=True,
                source="probe",
            )
            await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=bad.external_id,
                model_id=bad.id,
                success=False,
                source="probe",
                reason_code="malformed_function_call",
                detail="MALFORMED_FUNCTION_CALL",
            )
            await db.commit()

            plugin = await openrouter_auto_plugin(
                db,
                connection_id=connection.id,
                requested_model_id=auto.external_id,
            )
            assert plugin["id"] == "auto-router"
            assert plugin["allowed_models"] == ["vendor/good"]
            assert plugin["excluded_models"] == ["vendor/bad"]

            beta_plugin = await openrouter_auto_plugin(
                db,
                connection_id=connection.id,
                requested_model_id="openrouter/auto-beta",
            )
            assert beta_plugin["id"] == "auto-beta-router"

            # Auto Router itself is never constrained away from routing.
            assert "openrouter/auto" not in beta_plugin.get("excluded_models", [])
            await assert_code_interpreter_model_available(db, auto)
    finally:
        await engine.dispose()


async def test_auto_router_constraints_come_from_recorded_evidence():
    await _run_auto_router_plugin()


async def _run_registry_bootstrap() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            text_model = await _model(db, connection, "vendor/text")
            image_model = await _model(db, connection, "vendor/flux", is_image_model=True)
            await db.commit()

            created = await ensure_model_compatibility_rows(db, [text_model, image_model])
            await db.commit()
            assert created == 1

            rows = (await db.execute(select(ModelToolCompatibility))).scalars().all()
            assert [row.external_model_id for row in rows] == ["vendor/text"]
            assert rows[0].tool == CODE_INTERPRETER_TOOL
            assert rows[0].status == STATUS_UNKNOWN

            # Re-running is idempotent.
            assert await ensure_model_compatibility_rows(db, [text_model]) == 0

            mapping = await compatibility_map_for_models(db, [text_model, image_model])
            assert (connection.id, "vendor/text") in mapping
    finally:
        await engine.dispose()


async def test_sync_registers_text_models_without_guessing():
    await _run_registry_bootstrap()


async def _run_event_pruning() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            connection = await _connection(db)
            model = await _model(db, connection, "vendor/model-e")
            await db.commit()

            row = await record_compatibility_result(
                db,
                connection_id=connection.id,
                external_model_id=model.external_id,
                model_id=model.id,
                success=True,
                source="probe",
            )
            event = (
                await db.execute(
                    select(ModelToolCompatibilityEvent).where(ModelToolCompatibilityEvent.compatibility_id == row.id)
                )
            ).scalar_one()
            event.created_at = datetime.datetime.utcnow() - datetime.timedelta(days=200)
            await db.commit()

            removed = await prune_compatibility_events(db, retention_days=90)
            await db.commit()
            assert removed == 1
            assert (
                await get_compatibility(
                    db,
                    connection_id=connection.id,
                    external_model_id=model.external_id,
                )
                is not None
            )
    finally:
        await engine.dispose()


async def test_old_compatibility_events_are_pruned():
    await _run_event_pruning()
