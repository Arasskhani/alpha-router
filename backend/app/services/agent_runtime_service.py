"""Controlled specialist Agent turn planning before chat/gateway execution."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.agent_policy_service import (
    ResolvedAgentPolicies,
    resolve_agent_policies,
)
from app.services.agent_prompt_service import (
    AgentPromptPlan,
    build_agent_prompt_plan,
    citation_validation_safe_response,
)
from app.services.agent_routing_service import (
    AgentExecutionTarget,
    AgentRoutingDecision,
    route_agent,
)
from app.services.agent_tool_registry_service import (
    ResolvedAgentTool,
    ToolPolicyDenied,
    assert_tool_model_compatible,
    resolve_agent_tools,
)
from app.services.knowledge_citation_service import (
    CitationVerification,
    verify_answer_citations,
)
from app.services.knowledge_embedding_service import KnowledgeEmbeddingBackend
from app.services.knowledge_rerank_service import KnowledgeReranker
from app.services.knowledge_retrieval_service import (
    KnowledgeRetrievalResult,
    KnowledgeRetrievalUnavailable,
    retrieve_knowledge,
)
from app.services.llm_providers import external_id_lookup_candidates
from app.services.model_access_service import (
    ModelAccessSubject,
    user_can_access_model,
)
from app.services.model_capabilities import model_kinds
from app.services.model_tool_compatibility_service import is_auto_router_model_id
from app.services.qdrant_service import QdrantVectorService
from app.services.resource_access_service import ResourceAccessSubject
from app.services.user_memory_service import (
    format_memory_system_block,
    retrieve_memories,
)
from app.services.user_profile_context_service import (
    format_profile_system_block,
    load_agent_profile_facts,
)


class AgentRuntimeError(RuntimeError):
    """Base error for a turn that cannot be planned safely."""


class AgentModelUnavailable(AgentRuntimeError):
    """No enabled, accessible text model satisfies immutable Agent policy."""


class AgentRuntimeUnavailable(AgentRuntimeError):
    """A fail-closed runtime dependency is unavailable."""


class AgentRuntimeDenied(PermissionError):
    """A mandatory Guardrail hook denied the operation."""


@dataclass(frozen=True)
class GuardrailRequest:
    hook: str
    agent_id: str
    agent_version_id: str
    user_id: int | None
    query_sha256: str
    metadata: dict[str, Any]
    content_blocks: tuple[str, ...]


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason_code: str
    metadata: dict[str, Any]


class AgentGuardrailHooks(Protocol):
    async def evaluate(self, request: GuardrailRequest) -> GuardrailDecision: ...


class AllowAuditGuardrailHooks:
    """Default extension point: allow current policy while returning auditable metadata."""

    async def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return GuardrailDecision(
            allowed=True,
            reason_code="policy_allow",
            metadata={
                "hook": request.hook,
                "policy_mode": "allow_with_audit",
            },
        )


class AgentKnowledgeRetriever(Protocol):
    async def retrieve(
        self,
        db: AsyncSession,
        *,
        agent_version_id: str,
        subject: ResourceAccessSubject,
        query: str,
    ) -> KnowledgeRetrievalResult: ...


@dataclass(frozen=True)
class QdrantAgentKnowledgeRetriever:
    qdrant: QdrantVectorService
    embedding_backend: KnowledgeEmbeddingBackend
    reranker: KnowledgeReranker | None = None

    async def retrieve(
        self,
        db: AsyncSession,
        *,
        agent_version_id: str,
        subject: ResourceAccessSubject,
        query: str,
    ) -> KnowledgeRetrievalResult:
        return await retrieve_knowledge(
            db,
            agent_version_id=agent_version_id,
            subject=subject,
            query=query,
            qdrant=self.qdrant,
            embedding_backend=self.embedding_backend,
            reranker=self.reranker,
        )


@dataclass(frozen=True)
class AgentEgressManifest:
    provider_type: str
    model_id: str
    knowledge_base_ids: tuple[str, ...]
    document_version_ids: tuple[str, ...]
    classifications: tuple[str, ...]
    prompt_character_count: int


@dataclass(frozen=True)
class AgentTurnPlan:
    status: str
    routing: AgentRoutingDecision
    target: AgentExecutionTarget | None
    model: AIModel | None
    policies: ResolvedAgentPolicies | None
    prompt: AgentPromptPlan | None
    retrieval: KnowledgeRetrievalResult | None
    tools: tuple[ResolvedAgentTool, ...]
    guardrail_decisions: tuple[GuardrailDecision, ...]
    egress_manifest: AgentEgressManifest | None
    safe_response: str | None
    plan_id: str
    routing_outcome: str
    routing_reason: str
    selected_agent_id: str | None
    selected_agent_version_id: str | None
    selected_provider_id: int | None
    selected_model_id: int | None
    retrieval_outcome: str
    retrieval_result_count: int
    tool_execution_ids: tuple[str, ...]
    handoff_event_ids: tuple[str, ...]
    provider_latency_ms: int | None
    total_planning_latency_ms: int
    retrieval_latency_ms: int
    query_sha256: str


@dataclass(frozen=True)
class AgentCompletionReview:
    status: str
    display_text: str | None
    safe_response: str | None
    reason_code: str
    guardrail_decisions: tuple[GuardrailDecision, ...]
    citation_verification: CitationVerification | None

    @property
    def guardrail_decision(self) -> GuardrailDecision | None:
        return self.guardrail_decisions[-1] if self.guardrail_decisions else None


def _last_user_query(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "").lower() != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return " ".join(content.split())
        if isinstance(content, list):
            text = "\n".join(
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if text.strip():
                return " ".join(text.split())
    return ""


def _text_model(model: AIModel) -> bool:
    if is_auto_router_model_id(model.external_id):
        return True
    return "text" in model_kinds(
        external_id=model.external_id or "",
        is_image_model=bool(model.is_image_model),
        is_video_model=bool(getattr(model, "is_video_model", False)),
        pricing_raw=model.pricing_raw,
        provider_type=model.provider_type,
    )


async def _model_for_reference(
    db: AsyncSession,
    reference: str,
) -> AIModel | None:
    clean_reference = (reference or "").strip()
    model: AIModel | None = None
    if clean_reference.startswith("model::"):
        try:
            primary_key = int(clean_reference.split("::", 1)[1])
        except (TypeError, ValueError):
            primary_key = None
        if primary_key is not None:
            model = (
                await db.execute(
                    select(AIModel)
                    .join(Connection, Connection.id == AIModel.connection_id)
                    .where(
                        AIModel.id == primary_key,
                        AIModel.is_enabled.is_(True),
                        AIModel.admin_disabled.is_(False),
                        Connection.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
    else:
        candidates = external_id_lookup_candidates(clean_reference)
        if candidates:
            model = (
                (
                    await db.execute(
                        select(AIModel)
                        .join(Connection, Connection.id == AIModel.connection_id)
                        .where(
                            AIModel.external_id.in_(candidates),
                            AIModel.is_enabled.is_(True),
                            AIModel.admin_disabled.is_(False),
                            Connection.is_active.is_(True),
                        )
                        .order_by(AIModel.id)
                    )
                )
                .scalars()
                .first()
            )
    return model


async def resolve_agent_model(
    db: AsyncSession,
    *,
    policies: ResolvedAgentPolicies,
    subject: ModelAccessSubject,
) -> AIModel:
    if not policies.model.candidates:
        raise AgentModelUnavailable("Agent model policy contains no model candidates")
    denied: list[str] = []
    for reference in policies.model.candidates:
        model = await _model_for_reference(db, reference)
        if model is None:
            denied.append(f"{reference}:unavailable")
            continue
        if is_auto_router_model_id(model.external_id) and not policies.model.allow_auto_router:
            denied.append(f"{reference}:auto_router_disabled")
            continue
        if not _text_model(model):
            denied.append(f"{reference}:not_text")
            continue
        if not await user_can_access_model(db, model, subject):
            denied.append(f"{reference}:access_denied")
            continue
        return model
    raise AgentModelUnavailable(
        "No Agent model candidate is enabled and accessible" + (f" ({', '.join(denied)})" if denied else "")
    )


def _route_response(decision: AgentRoutingDecision, query: str) -> str:
    persian = any("\u0600" <= character <= "\u06ff" for character in query)
    if decision.kind == "clarification":
        return (
            "برای انتخاب Agent مناسب، لطفاً موضوع درخواست را دقیق‌تر مشخص کنید."
            if persian
            else "Please clarify the topic so I can select the appropriate specialist Agent."
        )
    return (
        "Agent تخصصی مناسبی برای این درخواست پیدا نشد؛ لطفاً یک Agent را صریحاً انتخاب کنید."
        if persian
        else "No suitable specialist Agent was found; please select an Agent explicitly."
    )


async def _guard(
    hooks: AgentGuardrailHooks,
    *,
    hook: str,
    target: AgentExecutionTarget,
    subject: ResourceAccessSubject,
    query_sha256: str,
    metadata: dict[str, Any],
    content_blocks: tuple[str, ...],
    fail_closed: bool,
) -> GuardrailDecision:
    try:
        async with asyncio.timeout(max(1, min(get_settings().agent_guardrail_timeout_seconds, 30))):
            decision = await hooks.evaluate(
                GuardrailRequest(
                    hook=hook,
                    agent_id=target.agent.id,
                    agent_version_id=target.version.id,
                    user_id=subject.user_id,
                    query_sha256=query_sha256,
                    metadata=metadata,
                    content_blocks=content_blocks,
                )
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if fail_closed:
            raise AgentRuntimeUnavailable(f"Mandatory Guardrail hook failed: {hook}") from exc
        return GuardrailDecision(
            allowed=True,
            reason_code="hook_error_fail_open",
            metadata={"hook": hook, "error_type": type(exc).__name__},
        )
    if not isinstance(decision, GuardrailDecision):
        if fail_closed:
            raise AgentRuntimeUnavailable(f"Mandatory Guardrail hook returned an invalid decision: {hook}")
        return GuardrailDecision(
            allowed=True,
            reason_code="invalid_hook_result_fail_open",
            metadata={"hook": hook},
        )
    if not decision.allowed:
        raise AgentRuntimeDenied(f"Guardrail denied {hook}: {decision.reason_code}")
    return decision


def _egress_manifest(
    *,
    model: AIModel,
    prompt: AgentPromptPlan,
    retrieval: KnowledgeRetrievalResult | None,
) -> AgentEgressManifest:
    citations = retrieval.context.citations if retrieval is not None else ()
    return AgentEgressManifest(
        provider_type=(model.provider_type or "").strip().lower(),
        model_id=model.external_id,
        knowledge_base_ids=tuple(sorted({citation.knowledge_base_id for citation in citations})),
        document_version_ids=tuple(sorted({citation.document_version_id for citation in citations})),
        classifications=tuple(sorted({citation.classification for citation in citations})),
        prompt_character_count=sum(len(str(message.get("content") or "")) for message in prompt.messages),
    )


async def plan_agent_turn(
    db: AsyncSession,
    *,
    messages: list[dict[str, Any]],
    resource_subject: ResourceAccessSubject,
    model_subject: ModelAccessSubject,
    agent_id: str | None = None,
    agent_slug: str | None = None,
    pinned_version_id: str | None = None,
    query: str | None = None,
    private_mode: bool = False,
    personal_memory_allowed: bool = True,
    knowledge_retriever: AgentKnowledgeRetriever | None = None,
    guardrail_hooks: AgentGuardrailHooks | None = None,
) -> AgentTurnPlan:
    """Resolve one bounded turn without invoking the generation provider."""

    planning_started = time.perf_counter()
    plan_id = str(uuid.uuid4())
    clean_query = " ".join((query or _last_user_query(messages)).split())
    settings = get_settings()
    if not clean_query:
        raise AgentRuntimeError("Agent turn requires a user query")
    if len(clean_query) > settings.knowledge_retrieval_max_query_characters:
        raise AgentRuntimeError("Agent turn query exceeds the configured limit")
    query_sha256 = hashlib.sha256(clean_query.encode("utf-8")).hexdigest()
    routing = await route_agent(
        db,
        subject=resource_subject,
        query=clean_query,
        agent_id=agent_id,
        agent_slug=agent_slug,
        pinned_version_id=pinned_version_id,
    )
    if routing.target is None:
        return AgentTurnPlan(
            status="route_required",
            routing=routing,
            target=None,
            model=None,
            policies=None,
            prompt=None,
            retrieval=None,
            tools=(),
            guardrail_decisions=(),
            egress_manifest=None,
            safe_response=_route_response(routing, clean_query),
            plan_id=plan_id,
            routing_outcome=routing.kind,
            routing_reason=routing.reason,
            selected_agent_id=None,
            selected_agent_version_id=None,
            selected_provider_id=None,
            selected_model_id=None,
            retrieval_outcome="not_attempted",
            retrieval_result_count=0,
            tool_execution_ids=(),
            handoff_event_ids=(),
            provider_latency_ms=None,
            total_planning_latency_ms=max(
                0,
                int((time.perf_counter() - planning_started) * 1000),
            ),
            retrieval_latency_ms=0,
            query_sha256=query_sha256,
        )

    target = routing.target
    policies = resolve_agent_policies(target.version)
    model = await resolve_agent_model(db, policies=policies, subject=model_subject)
    resolved_tools = await resolve_agent_tools(db, policies.tools)
    compatible_tools: list[ResolvedAgentTool] = []
    for spec in resolved_tools:
        try:
            assert_tool_model_compatible(spec, model)
        except ToolPolicyDenied:
            if spec.required:
                raise
            continue
        compatible_tools.append(spec)

    hooks = guardrail_hooks or AllowAuditGuardrailHooks()
    decisions: list[GuardrailDecision] = []
    retrieval: KnowledgeRetrievalResult | None = None
    retrieval_outcome = "disabled"
    retrieval_started: float | None = None
    retrieval_allowed = bool(
        policies.retrieval.enabled and (not private_mode or policies.retrieval.allow_in_private_mode)
    )
    if policies.retrieval.enabled and not retrieval_allowed:
        retrieval_outcome = "private_mode_disabled"
    if retrieval_allowed:
        retrieval_started = time.perf_counter()
        retrieval_outcome = "not_configured"
        decisions.append(
            await _guard(
                hooks,
                hook="pre_retrieval",
                target=target,
                subject=resource_subject,
                query_sha256=query_sha256,
                metadata={"query_length": len(clean_query)},
                content_blocks=(clean_query,),
                fail_closed=policies.guardrail.fail_closed,
            )
        )
        if knowledge_retriever is None:
            if policies.retrieval.fail_closed:
                raise AgentRuntimeUnavailable("Knowledge retrieval is required but no retriever is configured")
        else:
            try:
                retrieval = await knowledge_retriever.retrieve(
                    db,
                    agent_version_id=target.version.id,
                    subject=resource_subject,
                    query=clean_query,
                )
                retrieval_outcome = "success"
            except KnowledgeRetrievalUnavailable as exc:
                retrieval_outcome = "unavailable_fail_open"
                if policies.retrieval.fail_closed:
                    raise AgentRuntimeUnavailable("Knowledge retrieval is unavailable") from exc
    retrieval_latency_ms = (
        max(0, int((time.perf_counter() - retrieval_started) * 1000)) if retrieval_started is not None else 0
    )

    runtime_context_blocks: list[str] = []
    if not private_mode and resource_subject.user_id is not None:
        try:
            if policies.profile.enabled and policies.profile.allowed_fields:
                profile_facts = await load_agent_profile_facts(
                    db,
                    user_id=resource_subject.user_id,
                    allowed_fields=policies.profile.allowed_fields,
                )
                if profile_facts:
                    runtime_context_blocks.append(format_profile_system_block(profile_facts))
            if personal_memory_allowed and policies.memory.enabled and policies.memory.max_items > 0:
                memories = await retrieve_memories(
                    db,
                    resource_subject.user_id,
                    query=clean_query,
                    max_items=policies.memory.max_items,
                )
                if memories:
                    runtime_context_blocks.append(format_memory_system_block(memories))
        except Exception as exc:
            raise AgentRuntimeUnavailable("Approved Agent personalization context is unavailable") from exc

    prompt = build_agent_prompt_plan(
        agent=target.agent,
        version=target.version,
        policies=policies,
        query=clean_query,
        messages=messages,
        retrieval=retrieval,
        runtime_context_blocks=tuple(runtime_context_blocks),
    )
    if not prompt.generation_allowed:
        return AgentTurnPlan(
            status="abstained",
            routing=routing,
            target=target,
            model=model,
            policies=policies,
            prompt=prompt,
            retrieval=retrieval,
            tools=tuple(compatible_tools),
            guardrail_decisions=tuple(decisions),
            egress_manifest=None,
            safe_response=prompt.safe_response,
            plan_id=plan_id,
            routing_outcome=routing.kind,
            routing_reason=routing.reason,
            selected_agent_id=target.agent.id,
            selected_agent_version_id=target.version.id,
            selected_provider_id=model.connection_id,
            selected_model_id=model.id,
            retrieval_outcome=retrieval_outcome,
            retrieval_result_count=len(retrieval.evidence) if retrieval else 0,
            tool_execution_ids=(),
            handoff_event_ids=(),
            provider_latency_ms=None,
            total_planning_latency_ms=max(
                0,
                int((time.perf_counter() - planning_started) * 1000),
            ),
            retrieval_latency_ms=retrieval_latency_ms,
            query_sha256=query_sha256,
        )
    if not policies.guardrail.allow_external_provider:
        raise AgentRuntimeDenied("Agent policy denies external provider egress")
    manifest = _egress_manifest(model=model, prompt=prompt, retrieval=retrieval)
    decisions.append(
        await _guard(
            hooks,
            hook="pre_provider_egress",
            target=target,
            subject=resource_subject,
            query_sha256=query_sha256,
            metadata={
                "provider_type": manifest.provider_type,
                "model_id": manifest.model_id,
                "knowledge_base_ids": list(manifest.knowledge_base_ids),
                "document_version_ids": list(manifest.document_version_ids),
                "classifications": list(manifest.classifications),
                "prompt_character_count": manifest.prompt_character_count,
            },
            content_blocks=tuple(str(message.get("content") or "") for message in prompt.messages),
            fail_closed=policies.guardrail.fail_closed,
        )
    )
    return AgentTurnPlan(
        status="ready",
        routing=routing,
        target=target,
        model=model,
        policies=policies,
        prompt=prompt,
        retrieval=retrieval,
        tools=tuple(compatible_tools),
        guardrail_decisions=tuple(decisions),
        egress_manifest=manifest,
        safe_response=None,
        plan_id=plan_id,
        routing_outcome=routing.kind,
        routing_reason=routing.reason,
        selected_agent_id=target.agent.id,
        selected_agent_version_id=target.version.id,
        selected_provider_id=model.connection_id,
        selected_model_id=model.id,
        retrieval_outcome=retrieval_outcome,
        retrieval_result_count=len(retrieval.evidence) if retrieval else 0,
        tool_execution_ids=(),
        handoff_event_ids=(),
        provider_latency_ms=None,
        total_planning_latency_ms=max(
            0,
            int((time.perf_counter() - planning_started) * 1000),
        ),
        retrieval_latency_ms=retrieval_latency_ms,
        query_sha256=query_sha256,
    )


async def finalize_agent_completion(
    *,
    plan: AgentTurnPlan,
    output_text: str,
    resource_subject: ResourceAccessSubject,
    guardrail_hooks: AgentGuardrailHooks | None = None,
) -> AgentCompletionReview:
    """Fail closed before any provider-generated text is displayed to a user."""

    if plan.status != "ready" or plan.target is None or plan.policies is None or plan.prompt is None:
        raise AgentRuntimeError("Only a ready Agent turn may finalize a completion")
    if not isinstance(output_text, str) or not output_text.strip():
        return AgentCompletionReview(
            status="blocked",
            display_text=None,
            safe_response="The model returned no displayable response.",
            reason_code="empty_provider_output",
            guardrail_decisions=(),
            citation_verification=None,
        )
    maximum_characters = max(
        1_024,
        min(1_048_576, int(plan.policies.model.max_output_tokens) * 16),
    )
    if len(output_text) > maximum_characters:
        return AgentCompletionReview(
            status="blocked",
            display_text=None,
            safe_response="The model response exceeded the configured safety limit.",
            reason_code="provider_output_too_large",
            guardrail_decisions=(),
            citation_verification=None,
        )

    hooks = guardrail_hooks or AllowAuditGuardrailHooks()
    try:
        decision = await _guard(
            hooks,
            hook="post_provider_output",
            target=plan.target,
            subject=resource_subject,
            query_sha256=plan.query_sha256,
            metadata={
                "output_character_count": len(output_text),
                "provider_type": (plan.egress_manifest.provider_type if plan.egress_manifest is not None else ""),
                "model_id": (plan.egress_manifest.model_id if plan.egress_manifest is not None else ""),
            },
            content_blocks=(output_text,),
            fail_closed=plan.policies.guardrail.fail_closed,
        )
    except AgentRuntimeDenied:
        return AgentCompletionReview(
            status="blocked",
            display_text=None,
            safe_response="The generated response was blocked by safety policy.",
            reason_code="post_provider_guardrail_denied",
            guardrail_decisions=(),
            citation_verification=None,
        )

    citations = plan.retrieval.context.citations if plan.retrieval is not None else ()
    verification = verify_answer_citations(
        output_text,
        citations,
        citations_required=bool(plan.policies.retrieval.enabled and plan.policies.retrieval.citations_required),
    )
    if not verification.valid:
        query = _last_user_query(list(plan.prompt.messages))
        return AgentCompletionReview(
            status="blocked",
            display_text=None,
            safe_response=citation_validation_safe_response(
                query=query,
                verification=verification,
            ),
            reason_code="citation_validation_failed",
            guardrail_decisions=(decision,),
            citation_verification=verification,
        )
    try:
        persistence_decision = await _guard(
            hooks,
            hook="pre_persistence",
            target=plan.target,
            subject=resource_subject,
            query_sha256=plan.query_sha256,
            metadata={
                "output_character_count": len(output_text),
                "citation_ids": list(verification.cited_ids),
            },
            content_blocks=(output_text,),
            fail_closed=plan.policies.guardrail.fail_closed,
        )
    except AgentRuntimeDenied:
        return AgentCompletionReview(
            status="blocked",
            display_text=None,
            safe_response="The generated response was blocked before persistence.",
            reason_code="pre_persistence_guardrail_denied",
            guardrail_decisions=(decision,),
            citation_verification=verification,
        )
    return AgentCompletionReview(
        status="ready",
        display_text=output_text,
        safe_response=None,
        reason_code="completion_verified",
        guardrail_decisions=(decision, persistence_decision),
        citation_verification=verification,
    )
