"""Metadata-only persistence for Agent turn planning and execution outcomes."""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_runtime import (
    AgentCitation,
    AgentRetrievalTrace,
    AgentRun,
    AgentToolRun,
)
from app.models.chat import ChatSession
from app.models.logging import RequestLog
from app.services.agent_runtime_service import (
    AgentCompletionReview,
    AgentTurnPlan,
)
from app.services.agent_tool_registry_service import (
    ResolvedAgentTool,
    ToolExecutionContext,
    ToolExecutionResult,
)
from app.services.observability import record_agent_run


class AgentRunPersistenceError(RuntimeError):
    """Agent runtime evidence could not be persisted safely."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _bounded_text(value: str | None, maximum: int) -> str | None:
    clean = " ".join((value or "").split())
    return clean[:maximum] or None


def _guardrail_event(decision: Any, *, stage: str | None = None) -> dict[str, Any]:
    metadata = decision.metadata if isinstance(decision.metadata, dict) else {}
    return {
        "stage": stage or str(metadata.get("hook") or "unknown"),
        "allowed": bool(decision.allowed),
        "reason_code": str(decision.reason_code or "")[:64],
        "metadata": {
            str(key)[:64]: value
            for key, value in metadata.items()
            if isinstance(value, (str, int, float, bool, type(None)))
        },
    }


def _retrieval_results(plan: AgentTurnPlan) -> list[dict[str, Any]]:
    if plan.retrieval is None:
        return []
    return [
        {
            "rank": int(evidence.rank),
            "citation_id": evidence.citation.citation_id,
            "chunk_id": evidence.citation.chunk_id,
            "document_id": evidence.citation.document_id,
            "document_version_id": evidence.citation.document_version_id,
            "knowledge_base_id": evidence.citation.knowledge_base_id,
            "release_id": evidence.citation.release_id,
            "rerank_score": float(evidence.rerank_score),
            "rrf_score": float(evidence.rrf_score),
            "dense_score": (
                float(evidence.dense_score)
                if evidence.dense_score is not None
                else None
            ),
            "sparse_score": (
                float(evidence.sparse_score)
                if evidence.sparse_score is not None
                else None
            ),
            "content_hash": evidence.citation.content_hash,
            "classification": evidence.citation.classification,
        }
        for evidence in plan.retrieval.evidence
    ]


async def persist_agent_plan(
    db: AsyncSession,
    *,
    plan: AgentTurnPlan,
    source: str,
    client_app: str | None,
    user_id: int | None,
    alpha_router_api_key_id: int | None,
    chat_session_id: str | None,
    external_session_id: str | None,
    private_mode: bool = False,
) -> AgentRun:
    """Persist a plan, retrieval trace, citations, and optional session pin."""

    owned_session: ChatSession | None = None
    if chat_session_id:
        owned_session = (
            await db.execute(
                select(ChatSession)
                .where(
                    ChatSession.id == chat_session_id,
                    ChatSession.user_id == user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if owned_session is None:
            raise AgentRunPersistenceError(
                "Chat session is unavailable for Agent persistence"
            )

    retrieval = plan.retrieval
    release_ids = list(retrieval.knowledge_release_ids) if retrieval else []
    index_ids = list(retrieval.index_version_ids) if retrieval else []
    component_errors = list(retrieval.component_errors) if retrieval else []
    manifest = asdict(plan.egress_manifest) if plan.egress_manifest else {}
    status = {
        "ready": "planned",
        "route_required": "route_required",
        "abstained": "abstained",
    }.get(plan.status)
    if status is None:
        raise AgentRunPersistenceError(f"Unsupported Agent plan status: {plan.status}")
    query_digest = (
        hashlib.sha256(f"private:{plan.plan_id}".encode("utf-8")).hexdigest()
        if private_mode
        else plan.query_sha256
    )

    row = AgentRun(
        id=plan.plan_id,
        correlation_id=plan.plan_id,
        chat_session_id=owned_session.id if owned_session else None,
        external_session_id=_bounded_text(external_session_id, 128),
        user_id=user_id,
        alpha_router_api_key_id=alpha_router_api_key_id,
        agent_id=plan.selected_agent_id,
        agent_version_id=plan.selected_agent_version_id,
        connection_id=plan.selected_provider_id,
        model_catalog_id=plan.selected_model_id,
        source=_bounded_text(source, 32) or "unknown",
        client_app=_bounded_text(client_app, 128),
        status=status,
        routing_outcome=plan.routing_outcome[:32],
        routing_reason=_bounded_text(plan.routing_reason, 255),
        routing_confidence=float(plan.routing.confidence),
        provider_type=(
            _bounded_text(plan.model.provider_type, 64) if plan.model else None
        ),
        model_external_id=(
            _bounded_text(plan.model.external_id, 512) if plan.model else None
        ),
        query_sha256=query_digest,
        private_mode=private_mode,
        retrieval_outcome=plan.retrieval_outcome[:32],
        retrieval_result_count=plan.retrieval_result_count,
        knowledge_release_ids=release_ids,
        index_version_ids=index_ids,
        retrieval_error_codes=component_errors,
        tool_execution_ids=list(plan.tool_execution_ids),
        handoff_event_ids=list(plan.handoff_event_ids),
        guardrail_events=[
            _guardrail_event(decision) for decision in plan.guardrail_decisions
        ],
        egress_manifest=manifest,
        planning_latency_ms=plan.total_planning_latency_ms,
        retrieval_latency_ms=getattr(plan, "retrieval_latency_ms", None),
        completed_at=_now() if status in {"route_required", "abstained"} else None,
    )
    db.add(row)
    # Application-assigned PK + bare ForeignKey (no relationship()) means the
    # UnitOfWork will not parent-order these inserts. Flush the run first so
    # PostgreSQL accepts the retrieval/citation rows that reference it.
    await db.flush()
    db.add(
        AgentRetrievalTrace(
            id=str(uuid.uuid4()),
            agent_run_id=row.id,
            query_sha256=query_digest,
            outcome=plan.retrieval_outcome[:32],
            answerable=retrieval.answerable if retrieval else None,
            abstention_reason=(
                _bounded_text(retrieval.abstention_reason, 64) if retrieval else None
            ),
            candidate_count=retrieval.candidate_count if retrieval else 0,
            post_authorized_count=(retrieval.post_authorized_count if retrieval else 0),
            result_count=len(retrieval.evidence) if retrieval else 0,
            estimated_context_tokens=(
                retrieval.context.estimated_tokens if retrieval else 0
            ),
            context_truncated=bool(retrieval.context.truncated if retrieval else False),
            knowledge_release_ids=release_ids,
            index_version_ids=index_ids,
            component_errors=component_errors,
            results=_retrieval_results(plan),
            latency_ms=getattr(plan, "retrieval_latency_ms", None),
        )
    )
    if retrieval:
        for citation in retrieval.context.citations:
            db.add(
                AgentCitation(
                    id=str(uuid.uuid4()),
                    agent_run_id=row.id,
                    citation_id=citation.citation_id,
                    chunk_id=citation.chunk_id,
                    document_id=citation.document_id,
                    document_version_id=citation.document_version_id,
                    knowledge_base_id=citation.knowledge_base_id,
                    release_id=citation.release_id,
                    title=citation.title[:512],
                    file_name=citation.file_name[:512],
                    mime_type=citation.mime_type[:255],
                    page_number=citation.page_number,
                    section=(
                        citation.section[:512] if citation.section is not None else None
                    ),
                    authority=citation.authority[:64],
                    classification=citation.classification[:64],
                    effective_from=citation.effective_from,
                    effective_to=citation.effective_to,
                    content_hash=citation.content_hash,
                )
            )
    if owned_session is not None and plan.target is not None:
        owned_session.current_agent_id = plan.target.agent.id
        owned_session.current_agent_version_id = plan.target.version.id
        owned_session.agent_selected_at = _now()
    await db.flush()
    return row


async def mark_agent_run_started(db: AsyncSession, run_id: str) -> None:
    row = (
        await db.execute(
            select(AgentRun).where(AgentRun.id == run_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise AgentRunPersistenceError("Agent run does not exist")
    if row.status == "planned":
        row.status = "running"
        row.started_at = _now()
    await db.flush()


async def finalize_agent_run(
    db: AsyncSession,
    *,
    run_id: str,
    status: str,
    review: AgentCompletionReview | None = None,
    request_log_id: int | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
    total_cost_usd: float = 0.0,
    provider_latency_ms: int | None = None,
    total_latency_ms: int | None = None,
    output_displayed: bool = False,
    error_code: str | None = None,
    error_message: str | None = None,
) -> AgentRun:
    if status not in {
        "route_required",
        "abstained",
        "succeeded",
        "blocked",
        "failed",
        "cancelled",
    }:
        raise AgentRunPersistenceError(f"Invalid terminal Agent run status: {status}")
    row = (
        await db.execute(
            select(AgentRun).where(AgentRun.id == run_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise AgentRunPersistenceError("Agent run does not exist")

    row.status = status
    row.request_log_id = request_log_id
    row.prompt_tokens = max(0, int(prompt_tokens))
    row.completion_tokens = max(0, int(completion_tokens))
    row.cached_tokens = max(0, int(cached_tokens))
    row.total_cost_usd = Decimal(str(max(0.0, float(total_cost_usd or 0.0))))
    row.provider_latency_ms = (
        max(0, int(provider_latency_ms)) if provider_latency_ms is not None else None
    )
    row.total_latency_ms = (
        max(0, int(total_latency_ms)) if total_latency_ms is not None else None
    )
    row.output_displayed = bool(output_displayed)
    row.error_code = _bounded_text(error_code, 64)
    row.error_message = _bounded_text(error_message, 500)
    row.completed_at = _now()
    if request_log_id is not None:
        request_log = await db.get(RequestLog, request_log_id)
        row.usage_operation_id = (
            request_log.usage_operation_id if request_log is not None else None
        )
    if review is not None:
        row.completion_reason_code = review.reason_code[:64]
        events = list(row.guardrail_events or [])
        for decision in review.guardrail_decisions:
            events.append(
                _guardrail_event(
                    decision,
                    stage=str(
                        (decision.metadata or {}).get("hook") or "post_generation"
                    ),
                )
            )
        row.guardrail_events = events
    await db.flush()
    record_agent_run(
        status=row.status,
        routing_outcome=row.routing_outcome,
        retrieval_outcome=row.retrieval_outcome,
        private_mode=bool(row.private_mode),
        latency_ms=row.total_latency_ms,
        cost_usd=float(row.total_cost_usd or 0),
    )
    return row


async def persist_agent_tool_result(
    db: AsyncSession,
    *,
    agent_run_id: str,
    spec: ResolvedAgentTool,
    context: ToolExecutionContext,
    arguments: dict[str, Any],
    result: ToolExecutionResult,
) -> AgentToolRun:
    """Persist hashes and execution metadata; never persist raw Tool payloads."""

    canonical_arguments = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    canonical_output = json.dumps(
        result.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    row = AgentToolRun(
        id=result.execution_id,
        agent_run_id=agent_run_id,
        tool_id=spec.tool.id,
        tool_version_id=spec.version.id,
        user_id=context.user_id,
        status="cached" if result.cached else "succeeded",
        effect_type=spec.version.effect_type,
        arguments_sha256=hashlib.sha256(
            canonical_arguments.encode("utf-8")
        ).hexdigest(),
        output_sha256=hashlib.sha256(canonical_output.encode("utf-8")).hexdigest(),
        idempotency_key_sha256=(
            hashlib.sha256(context.idempotency_key.encode("utf-8")).hexdigest()
            if context.idempotency_key
            else None
        ),
        approval_recorded=bool(context.user_approved),
        attempts=result.attempts,
        elapsed_ms=max(0, int(result.elapsed_seconds * 1000)),
        cost_usd=Decimal(str(max(0.0, float(result.cost_usd)))),
        redacted_paths=list(result.redacted_paths),
        guardrail_reason_codes=list(result.guardrail_reason_codes),
        completed_at=_now(),
    )
    db.add(row)
    run = await db.get(AgentRun, agent_run_id)
    if run is None:
        raise AgentRunPersistenceError("Agent run does not exist")
    execution_ids = list(run.tool_execution_ids or [])
    if row.id not in execution_ids:
        execution_ids.append(row.id)
        run.tool_execution_ids = execution_ids
    await db.flush()
    return row
