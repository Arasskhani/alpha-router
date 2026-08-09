"""Safe active probes for Code Interpreter model compatibility."""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Any

from litellm import acompletion
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel, ModelToolCompatibility
from app.services.code_interpreter_service import (
    code_interpreter_system_message,
    extract_last_python_block,
    format_code_output_for_chat,
    run_python_sandbox,
)
from app.services.llm_providers import (
    litellm_model_for_provider,
    resolve_litellm_provider,
)
from app.services.model_tool_compatibility_service import (
    CODE_INTERPRETER_TOOL,
    STATUS_DEGRADED,
    STATUS_INCOMPATIBLE,
    STATUS_PROBING,
    STATUS_UNKNOWN,
    classify_failure_reason,
    ensure_all_model_compatibility_rows,
    get_or_create_compatibility,
    is_auto_router_model_id,
    mark_probe_started,
    openrouter_auto_plugin,
    record_compatibility_result,
    utcnow,
)
from app.services.secret_crypto import decrypt_secret
from app.services.usage_accounting_service import (
    PendingUsageEvent,
    capture_usage_event,
    persist_usage_operation,
)

logger = logging.getLogger("app.services.code_interpreter_probe")

PROBE_WORKSPACE = {"probe.csv": "value\n1\n2\n"}
PROBE_SENTINEL = "ALPHA_CODE_INTERPRETER_READY"
PROBE_FINISH_SENTINEL = "ALPHA_PROBE_COMPLETE"
PROBE_BATCH_SIZE = 3

_PROBE_REQUEST = (
    "This is an automated capability check. Use the attached probe.csv with the "
    "Code Interpreter. Return exactly one runnable ```python fenced block that reads "
    "probe.csv, verifies the values sum to 3, prints "
    f"{PROBE_SENTINEL}, and writes probe.json containing {{\"total\": 3}}. "
    "Do not return prose before the Python block."
)


@dataclass(frozen=True)
class ProbeResult:
    compatibility_id: int
    model_id: int
    external_model_id: str
    success: bool
    status: str
    reason_code: str | None = None
    detail: str | None = None
    selected_model_id: str | None = None


def _content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return str(getattr(message, "content", None) or "")


def _response_model(response: Any) -> str | None:
    value = getattr(response, "model", None)
    return str(value) if value else None


def _call_kwargs(
    *,
    model: AIModel,
    connection: Connection,
    api_key: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    provider = (connection.provider_type or model.provider_type or "").lower()
    kwargs: dict[str, Any] = {
        "model": litellm_model_for_provider(model.external_id, provider),
        "messages": messages,
        "api_key": api_key,
        "stream": False,
        "temperature": 0,
        "max_tokens": 700,
        "timeout": 75,
        "caching": False,
    }
    if connection.base_url:
        kwargs["base_url"] = connection.base_url
    llm_provider = resolve_litellm_provider(provider)
    if llm_provider:
        kwargs["custom_llm_provider"] = llm_provider
    return kwargs


async def _record_probe_usage(
    db: AsyncSession,
    *,
    model: AIModel,
    connection: Connection,
    events: list[PendingUsageEvent],
    success: bool,
) -> None:
    if not events:
        return
    await persist_usage_operation(
        db,
        events=events,
        user_id=None,
        alpha_router_api_key_id=None,
        budget_reservation_id=None,
        request_log_id=None,
        operation_type="compatibility_probe",
        source="system_probe",
        client_app="model_tool_compatibility",
        success=success,
        metadata={
            "tool": CODE_INTERPRETER_TOOL,
            "model_id": model.external_id,
            "connection_id": connection.id,
        },
    )


async def probe_model_compatibility(
    db: AsyncSession,
    model: AIModel,
) -> ProbeResult:
    """Exercise code emission, sandbox execution, artifact egress, and follow-up."""
    connection = await db.get(Connection, model.connection_id)
    if connection is None or not connection.is_active:
        raise ValueError("Model connection is inactive")
    row = await get_or_create_compatibility(
        db,
        connection_id=connection.id,
        external_model_id=model.external_id,
        model_id=model.id,
    )
    await mark_probe_started(db, row)
    await db.commit()

    api_key = decrypt_secret(connection.api_key_encrypted)
    messages = [
        {
            "role": "system",
            "content": (
                code_interpreter_system_message()
                + "\n\nWorkspace files:\n- probe.csv (CSV text)"
            ),
        },
        {"role": "user", "content": _PROBE_REQUEST},
    ]
    usage_events: list[PendingUsageEvent] = []
    selected_model: str | None = None
    success = False
    reason_code: str | None = None
    detail: str | None = None
    evidence: dict[str, Any] = {}
    started_at = datetime.datetime.utcnow()

    try:
        first_kwargs = _call_kwargs(
            model=model,
            connection=connection,
            api_key=api_key,
            messages=messages,
        )
        if (
            (connection.provider_type or "").lower() == "openrouter"
            and is_auto_router_model_id(model.external_id)
        ):
            first_kwargs["extra_body"] = {
                "plugins": [
                    await openrouter_auto_plugin(
                        db,
                        connection_id=connection.id,
                        requested_model_id=model.external_id,
                    )
                ]
            }
        first = await acompletion(**first_kwargs)
        first_content = _content(first)
        selected_model = _response_model(first)
        usage_events.append(
            capture_usage_event(
                first,
                ai_model=model,
                provider_type=connection.provider_type,
                service_type="llm",
                operation_name="compatibility_probe_generate",
                model_id=model.external_id,
                attempt_index=0,
                status="succeeded" if first_content.strip() else "failed",
                started_at=started_at,
                completed_at=datetime.datetime.utcnow(),
                prompt=messages,
                completion=first_content,
                error_message=None if first_content.strip() else "Empty probe completion",
            )
        )
        if not first_content.strip():
            reason_code = "empty_content"
            detail = "The model returned no content for the probe request."
        else:
            code = extract_last_python_block(first_content)
            if not code:
                reason_code = "no_python_block"
                detail = "The model did not return a runnable Python fenced block."
            else:
                try:
                    execution = await run_python_sandbox(code, PROBE_WORKSPACE)
                except ValueError as exc:
                    reason_code = "invalid_python_block"
                    detail = str(exc)
                else:
                    evidence.update(
                        {
                            "sandbox_exit_code": execution.exit_code,
                            "artifact_names": [item.name for item in execution.artifacts],
                        }
                    )
                    probe_artifact = next(
                        (item for item in execution.artifacts if item.name == "probe.json"),
                        None,
                    )
                    artifact_valid = False
                    if probe_artifact is not None:
                        try:
                            artifact_valid = (
                                json.loads(probe_artifact.content.decode("utf-8")).get("total")
                                == 3
                            )
                        except (UnicodeDecodeError, ValueError, AttributeError):
                            artifact_valid = False
                    if (
                        execution.exit_code != 0
                        or PROBE_SENTINEL not in execution.output
                        or not artifact_valid
                    ):
                        reason_code = "sandbox_protocol_error"
                        detail = (
                            "Generated code did not complete the deterministic sandbox "
                            "and artifact checks."
                        )
                    else:
                        followup_messages = [
                            *messages,
                            {"role": "assistant", "content": first_content},
                            {
                                "role": "user",
                                "content": (
                                    format_code_output_for_chat(execution)
                                    + "\nThe execution succeeded. Reply with exactly "
                                    + PROBE_FINISH_SENTINEL
                                ),
                            },
                        ]
                        second_started = datetime.datetime.utcnow()
                        second_kwargs = _call_kwargs(
                            model=model,
                            connection=connection,
                            api_key=api_key,
                            messages=followup_messages,
                        )
                        if "extra_body" in first_kwargs:
                            second_kwargs["extra_body"] = first_kwargs["extra_body"]
                        second = await acompletion(**second_kwargs)
                        second_content = _content(second)
                        usage_events.append(
                            capture_usage_event(
                                second,
                                ai_model=model,
                                provider_type=connection.provider_type,
                                service_type="llm",
                                operation_name="compatibility_probe_followup",
                                model_id=model.external_id,
                                attempt_index=1,
                                status=(
                                    "succeeded"
                                    if PROBE_FINISH_SENTINEL in second_content
                                    else "failed"
                                ),
                                started_at=second_started,
                                completed_at=datetime.datetime.utcnow(),
                                prompt=followup_messages,
                                completion=second_content,
                                error_message=(
                                    None
                                    if PROBE_FINISH_SENTINEL in second_content
                                    else "Probe follow-up sentinel missing"
                                ),
                            )
                        )
                        if PROBE_FINISH_SENTINEL not in second_content:
                            reason_code = "empty_content"
                            detail = "The model did not complete the post-execution turn."
                        else:
                            success = True
                            evidence["followup_complete"] = True
    except Exception as exc:
        detail = str(exc)[:1000]
        reason_code = classify_failure_reason(detail)
        logger.warning(
            "Code Interpreter compatibility probe failed model=%s connection=%s reason=%s",
            model.external_id,
            connection.id,
            reason_code,
        )

    if selected_model:
        evidence["selected_model_id"] = selected_model
    result_row = await record_compatibility_result(
        db,
        connection_id=connection.id,
        external_model_id=model.external_id,
        model_id=model.id,
        success=success,
        source="probe",
        reason_code=reason_code,
        detail=detail,
        requested_model_id=model.external_id,
        evidence=evidence,
    )
    # Auto routers expose the concrete selected model in successful responses.
    if selected_model and selected_model != model.external_id:
        normalized_selected = selected_model.removeprefix("openrouter/")
        await record_compatibility_result(
            db,
            connection_id=connection.id,
            external_model_id=normalized_selected,
            success=success,
            source="probe",
            reason_code=reason_code,
            detail=detail,
            requested_model_id=model.external_id,
            evidence={"selected_by_router": True, **evidence},
        )
    await _record_probe_usage(
        db,
        model=model,
        connection=connection,
        events=usage_events,
        success=success,
    )
    await db.commit()
    return ProbeResult(
        compatibility_id=result_row.id,
        model_id=model.id,
        external_model_id=model.external_id,
        success=success,
        status=result_row.status,
        reason_code=reason_code,
        detail=detail,
        selected_model_id=selected_model,
    )


async def claim_due_probe_model_ids(
    db: AsyncSession,
    *,
    limit: int = PROBE_BATCH_SIZE,
) -> list[int]:
    """Claim a small due batch so multiple workers do not duplicate paid probes."""
    await ensure_all_model_compatibility_rows(db)
    now = utcnow()
    query = (
        select(ModelToolCompatibility)
        .join(AIModel, AIModel.id == ModelToolCompatibility.model_id)
        .join(Connection, Connection.id == ModelToolCompatibility.connection_id)
        .where(
            ModelToolCompatibility.tool == CODE_INTERPRETER_TOOL,
            ModelToolCompatibility.model_id.is_not(None),
            ModelToolCompatibility.status.in_(
                [
                    STATUS_UNKNOWN,
                    STATUS_PROBING,
                    STATUS_DEGRADED,
                    STATUS_INCOMPATIBLE,
                ]
            ),
            or_(
                ModelToolCompatibility.next_probe_at.is_(None),
                ModelToolCompatibility.next_probe_at <= now,
            ),
            AIModel.is_enabled.is_(True),
            AIModel.admin_disabled.is_(False),
            Connection.is_active.is_(True),
        )
        .order_by(
            case(
                (AIModel.external_id.in_(["auto", "openrouter/auto", "auto-beta"]), 0),
                else_=1,
            ),
            ModelToolCompatibility.next_probe_at.asc(),
            ModelToolCompatibility.id.asc(),
        )
        .limit(max(1, min(int(limit), 10)))
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    rows = (await db.execute(query)).scalars().all()
    claimed: list[int] = []
    for row in rows:
        row.status = STATUS_PROBING
        row.next_probe_at = now + datetime.timedelta(minutes=20)
        if row.model_id is not None:
            claimed.append(int(row.model_id))
    await db.commit()
    return claimed
