"""Typed, fail-closed validation for immutable Agent-version policies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.config import get_settings
from app.models.agent import AgentVersion

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_GUARDRAIL_HOOKS = frozenset(
    {
        "pre_retrieval",
        "pre_provider_egress",
        "pre_tool_call",
        "post_generation",
        "pre_persistence",
    }
)


class AgentPolicyValidationError(ValueError):
    """Raised when a published Agent policy cannot be trusted by runtime."""


class _StrictPolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    @model_validator(mode="before")
    @classmethod
    def reject_coerced_booleans(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        for name, field_info in cls.model_fields.items():
            if (
                field_info.annotation is bool
                and name in value
                and not isinstance(value[name], bool)
            ):
                raise ValueError(f"{name} must be a JSON boolean")
        return value


def _clean_model_ref(value: str) -> str:
    normalized = " ".join((value or "").split())
    if not normalized or len(normalized) > 512:
        raise ValueError("model references must contain 1 to 512 characters")
    return normalized


def _clean_slug(value: str) -> str:
    normalized = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    if not normalized or len(normalized) > 128 or not _SLUG_RE.fullmatch(normalized):
        raise ValueError(
            "tool and Agent slugs must use lowercase letters, numbers, and hyphens"
        )
    return normalized


class AgentModelPolicy(_StrictPolicy):
    primary_model_id: str = ""
    fallback_model_ids: tuple[str, ...] = ()
    max_output_tokens: int = Field(default=4096, ge=1, le=65_536)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    allow_auto_router: bool = False

    @field_validator("primary_model_id")
    @classmethod
    def validate_primary_model(cls, value: str) -> str:
        return _clean_model_ref(value) if value else ""

    @field_validator("fallback_model_ids")
    @classmethod
    def validate_fallback_models(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 8:
            raise ValueError("at most 8 fallback models may be configured")
        cleaned = tuple(_clean_model_ref(value) for value in values)
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("fallback model references must be unique")
        return cleaned

    @model_validator(mode="after")
    def primary_not_repeated(self) -> AgentModelPolicy:
        if self.primary_model_id and self.primary_model_id in self.fallback_model_ids:
            raise ValueError("the primary model cannot also be a fallback")
        return self

    @property
    def candidates(self) -> tuple[str, ...]:
        return (
            (self.primary_model_id,) + self.fallback_model_ids
            if self.primary_model_id
            else self.fallback_model_ids
        )


class AgentToolGrant(_StrictPolicy):
    slug: str
    version_id: str | None = Field(default=None, min_length=1, max_length=36)
    required: bool = True

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        return _clean_slug(value)


class AgentToolPolicy(_StrictPolicy):
    tools: tuple[AgentToolGrant, ...] = ()
    denied_tools: tuple[str, ...] = ()
    max_calls_per_turn: int = Field(default=8, ge=0, le=32)
    max_hops_per_turn: int = Field(default=3, ge=0, le=8)
    max_total_seconds: int = Field(default=120, ge=1, le=600)
    max_cost_usd: float = Field(default=1.0, ge=0.0, le=100.0)
    require_user_approval_for_side_effects: bool = True

    @field_validator("denied_tools")
    @classmethod
    def validate_denied_tools(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_clean_slug(value) for value in values)
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("denied tool slugs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_grants(self) -> AgentToolPolicy:
        slugs = [grant.slug for grant in self.tools]
        if len(slugs) > 32:
            raise ValueError("at most 32 tools may be bound to an Agent version")
        if len(set(slugs)) != len(slugs):
            raise ValueError("tool grants must use unique slugs")
        overlap = set(slugs) & set(self.denied_tools)
        if overlap:
            raise ValueError(
                f"tools cannot be both allowed and denied: {sorted(overlap)}"
            )
        return self


class AgentRetrievalPolicy(_StrictPolicy):
    enabled: bool = True
    allow_in_private_mode: bool = False
    require_evidence: bool = False
    candidate_limit: int | None = Field(default=None, ge=1, le=200)
    final_limit: int | None = Field(default=None, ge=1, le=32)
    rrf_k: int | None = Field(default=None, ge=1, le=1_000)
    max_chunks_per_document: int | None = Field(default=None, ge=1, le=10)
    context_token_budget: int | None = Field(default=None, ge=128, le=32_768)
    minimum_answerability_score: float | None = Field(default=None, ge=0.0, le=1.0)
    dense_weight: float | None = Field(default=None, ge=0.0, le=10.0)
    sparse_weight: float | None = Field(default=None, ge=0.0, le=10.0)
    dense_score_threshold: float | None = Field(default=None, ge=-1.0, le=1.0)
    sparse_score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1_000_000.0,
    )
    citations_required: bool = True
    fail_closed: bool = True

    @model_validator(mode="after")
    def evidence_requires_retrieval(self) -> AgentRetrievalPolicy:
        if self.require_evidence and not self.enabled:
            raise ValueError(
                "require_evidence cannot be used when retrieval is disabled"
            )
        if self.require_evidence and not self.fail_closed:
            raise ValueError("evidence-required Agents must fail closed")
        return self


class AgentMemoryPolicy(_StrictPolicy):
    enabled: bool = False
    max_items: int = Field(default=10, ge=0, le=50)
    allow_write: bool = False


class AgentProfilePolicy(_StrictPolicy):
    enabled: bool = False
    allowed_fields: tuple[
        Literal[
            "display_name",
            "department",
            "job_title",
            "location",
            "preferred_language",
        ],
        ...,
    ] = ()


class AgentRoutingPolicy(_StrictPolicy):
    enabled: bool = True
    explicit_only: bool = False
    keywords: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    priority: int = Field(default=0, ge=-100, le=100)
    minimum_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    minimum_margin: float | None = Field(default=None, ge=0.0, le=1.0)
    allowed_handoff_targets: tuple[str, ...] = ()
    require_handoff_consent: bool = True
    max_handoffs_per_turn: int | None = Field(default=None, ge=0, le=4)
    transfer_history_messages: int = Field(default=2, ge=0, le=10)
    allow_assistant_context: bool = False

    @field_validator("keywords", "examples")
    @classmethod
    def validate_route_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 128:
            raise ValueError("routing text lists are limited to 128 entries")
        cleaned = tuple(" ".join(value.split()) for value in values if value.strip())
        if any(len(value) > 500 for value in cleaned):
            raise ValueError("routing text entries are limited to 500 characters")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("routing text entries must be unique")
        return cleaned

    @field_validator("allowed_handoff_targets")
    @classmethod
    def validate_handoff_targets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_clean_slug(value) for value in values)
        if len(cleaned) > 32 or len(set(cleaned)) != len(cleaned):
            raise ValueError(
                "handoff targets must be a unique list of at most 32 slugs"
            )
        return cleaned


class AgentEscalationPolicy(_StrictPolicy):
    enabled: bool = False
    allow_human_escalation: bool = False
    reason_codes: tuple[str, ...] = ()
    require_user_consent: bool = True

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip().lower() for value in values if value.strip())
        if len(cleaned) > 32 or any(
            not _PERMISSION_RE.fullmatch(value) for value in cleaned
        ):
            raise ValueError("escalation reason codes are invalid or exceed the limit")
        return cleaned


class AgentDisclaimerPolicy(_StrictPolicy):
    required: bool = False
    text: str = Field(default="", max_length=4_000)
    localized_text: dict[str, str] = Field(default_factory=dict)
    placement: Literal["before_answer", "after_answer"] = "after_answer"

    @model_validator(mode="after")
    def required_text_present(self) -> AgentDisclaimerPolicy:
        if self.required and not self.text and not self.localized_text:
            raise ValueError("a required disclaimer must contain text")
        if len(self.localized_text) > 16 or any(
            not key.strip() or len(value) > 4_000
            for key, value in self.localized_text.items()
        ):
            raise ValueError("localized disclaimer entries are invalid")
        return self


class AgentGuardrailPolicy(_StrictPolicy):
    fail_closed: bool = True
    require_evidence: bool = False
    allow_external_provider: bool = True
    allow_client_system_messages: bool = False
    hooks: tuple[str, ...] = _GUARDRAIL_HOOKS

    @field_validator("hooks")
    @classmethod
    def validate_hooks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            value not in _GUARDRAIL_HOOKS for value in values
        ):
            raise ValueError(
                "guardrail hooks contain an unsupported or duplicate value"
            )
        return values


class AgentLocalePolicy(_StrictPolicy):
    default_locale: str = Field(default="auto", min_length=2, max_length=32)
    supported_locales: tuple[str, ...] = ("fa", "en")
    mirror_user_language: bool = True

    @field_validator("supported_locales")
    @classmethod
    def validate_locales(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip().lower() for value in values if value.strip())
        if not cleaned or len(cleaned) > 16 or len(set(cleaned)) != len(cleaned):
            raise ValueError("supported locales must be a unique non-empty list")
        return cleaned


@dataclass(frozen=True)
class ResolvedAgentPolicies:
    model: AgentModelPolicy
    tools: AgentToolPolicy
    retrieval: AgentRetrievalPolicy
    memory: AgentMemoryPolicy
    profile: AgentProfilePolicy
    routing: AgentRoutingPolicy
    escalation: AgentEscalationPolicy
    disclaimer: AgentDisclaimerPolicy
    guardrail: AgentGuardrailPolicy
    locale: AgentLocalePolicy


def _parse(model: type[_StrictPolicy], value: Any, field: str) -> _StrictPolicy:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise AgentPolicyValidationError(f"Invalid {field}: expected a JSON object")
    try:
        return model.model_validate(value)
    except (TypeError, ValidationError, ValueError) as exc:
        raise AgentPolicyValidationError(f"Invalid {field}: {exc}") from exc


def resolve_agent_policies(version: AgentVersion) -> ResolvedAgentPolicies:
    """Parse policy JSON and clamp per-version limits to deployment ceilings."""

    settings = get_settings()
    model = _parse(AgentModelPolicy, version.model_policy, "model_policy")
    tools = _parse(AgentToolPolicy, version.tool_policy, "tool_policy")
    retrieval = _parse(
        AgentRetrievalPolicy,
        version.retrieval_policy,
        "retrieval_policy",
    )
    memory = _parse(AgentMemoryPolicy, version.memory_policy, "memory_policy")
    profile = _parse(AgentProfilePolicy, version.profile_policy, "profile_policy")
    routing = _parse(AgentRoutingPolicy, version.routing_policy, "routing_policy")
    escalation = _parse(
        AgentEscalationPolicy,
        version.escalation_policy,
        "escalation_policy",
    )
    disclaimer = _parse(
        AgentDisclaimerPolicy,
        version.disclaimer_policy,
        "disclaimer_policy",
    )
    guardrail = _parse(
        AgentGuardrailPolicy,
        version.guardrail_policy,
        "guardrail_policy",
    )
    locale = _parse(AgentLocalePolicy, version.locale_policy, "locale_policy")

    assert isinstance(model, AgentModelPolicy)
    assert isinstance(tools, AgentToolPolicy)
    assert isinstance(retrieval, AgentRetrievalPolicy)
    assert isinstance(memory, AgentMemoryPolicy)
    assert isinstance(profile, AgentProfilePolicy)
    assert isinstance(routing, AgentRoutingPolicy)
    assert isinstance(escalation, AgentEscalationPolicy)
    assert isinstance(disclaimer, AgentDisclaimerPolicy)
    assert isinstance(guardrail, AgentGuardrailPolicy)
    assert isinstance(locale, AgentLocalePolicy)

    tools = tools.model_copy(
        update={
            "max_calls_per_turn": min(
                tools.max_calls_per_turn,
                max(0, min(32, settings.agent_max_tool_calls_per_turn)),
            ),
            "max_hops_per_turn": min(
                tools.max_hops_per_turn,
                max(0, min(8, settings.agent_max_tool_hops_per_turn)),
            ),
            "max_total_seconds": min(
                tools.max_total_seconds,
                max(1, min(600, settings.agent_turn_timeout_seconds)),
            ),
        }
    )
    configured_handoffs = (
        routing.max_handoffs_per_turn
        if routing.max_handoffs_per_turn is not None
        else settings.agent_max_handoffs_per_turn
    )
    routing = routing.model_copy(
        update={
            "minimum_confidence": (
                routing.minimum_confidence
                if routing.minimum_confidence is not None
                else max(0.0, min(1.0, settings.agent_router_minimum_confidence))
            ),
            "minimum_margin": (
                routing.minimum_margin
                if routing.minimum_margin is not None
                else max(0.0, min(1.0, settings.agent_router_minimum_margin))
            ),
            "max_handoffs_per_turn": min(
                configured_handoffs,
                max(0, min(4, settings.agent_max_handoffs_per_turn)),
            ),
        }
    )
    if guardrail.require_evidence and not retrieval.require_evidence:
        retrieval = retrieval.model_copy(update={"require_evidence": True})
    if retrieval.require_evidence and not retrieval.fail_closed:
        raise AgentPolicyValidationError(
            "Evidence-required Agent versions must use fail-closed retrieval"
        )
    return ResolvedAgentPolicies(
        model=model,
        tools=tools,
        retrieval=retrieval,
        memory=memory,
        profile=profile,
        routing=routing,
        escalation=escalation,
        disclaimer=disclaimer,
        guardrail=guardrail,
        locale=locale,
    )


def validate_agent_version_policies(
    version: AgentVersion,
    *,
    require_model: bool,
) -> ResolvedAgentPolicies:
    policies = resolve_agent_policies(version)
    settings = get_settings()
    if require_model and not policies.model.primary_model_id:
        raise AgentPolicyValidationError(
            "Published Agent versions require model_policy.primary_model_id"
        )
    prompt = (version.system_prompt or "").strip()
    if not prompt:
        raise AgentPolicyValidationError("Agent system_prompt cannot be empty")
    if len(prompt) > max(1, min(250_000, settings.agent_max_system_prompt_characters)):
        raise AgentPolicyValidationError(
            "Agent system_prompt exceeds the configured limit"
        )
    return policies
