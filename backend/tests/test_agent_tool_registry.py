"""Versioned Tool Registry, schema safety, policy, and bounded execution tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.agent import AgentVersion
from app.models.agent_tool import AgentToolAuditEvent
from app.models.model_catalog import AIModel
from app.models.user import User
from app.services.agent_policy_service import resolve_agent_policies
from app.services.agent_tool_registry_service import (
    APPROVAL_REQUIRED,
    EFFECT_SIDE_EFFECTING,
    ResolvedAgentTool,
    ToolApprovalRequired,
    ToolExecutionBudget,
    ToolExecutionContext,
    ToolGuardrailDecision,
    ToolHandlerResult,
    ToolPolicyDenied,
    ToolRegistryError,
    ToolTransientError,
    create_agent_tool,
    create_agent_tool_version,
    execute_agent_tool,
    publish_agent_tool_version,
    resolve_agent_tools,
    submit_agent_tool_version,
    update_agent_tool_draft,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    ), engine


async def _user(db: AsyncSession, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


def _input_schema() -> dict:
    return {
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 1}},
        "required": ["query"],
        "additionalProperties": False,
    }


def _output_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "result": {"type": "string"},
            "api_key": {"type": "string"},
        },
        "required": ["result", "api_key"],
        "additionalProperties": False,
    }


async def _published_tool(db: AsyncSession):
    author = await _user(db, "tool-author")
    publisher = await _user(db, "tool-publisher")
    tool = await create_agent_tool(
        db,
        name="Policy Lookup",
        slug="Policy Lookup",
        created_by_user_id=author.id,
    )
    version = await create_agent_tool_version(
        db,
        tool,
        input_schema=_input_schema(),
        output_schema=_output_schema(),
        handler_key="builtin.policy_lookup",
        required_permission="policy.read",
        max_retries=1,
        idempotent=True,
        cost_policy={"estimated_cost_usd": 0.01, "maximum_cost_usd": 0.02},
        created_by_user_id=author.id,
    )
    await submit_agent_tool_version(db, version, actor_user_id=author.id)
    with pytest.raises(ToolRegistryError, match="Maker-checker"):
        await publish_agent_tool_version(db, version, actor_user_id=author.id)
    await publish_agent_tool_version(db, version, actor_user_id=publisher.id)
    await db.flush()
    return tool, version, author, publisher


async def _test_registry_lifecycle_and_schema_guards() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            tool, version, author, publisher = await _published_tool(db)
            assert tool.status == "active"
            assert version.status == "published"
            assert version.active_scope_key == f"tool:{tool.id}"
            with pytest.raises(ToolRegistryError, match="Only draft"):
                await update_agent_tool_draft(
                    db,
                    version,
                    actor_user_id=author.id,
                    timeout_seconds=30,
                )

            unsafe = await create_agent_tool(
                db,
                name="Unsafe Credentials",
                slug="unsafe-credentials",
                created_by_user_id=author.id,
            )
            unsafe_schema = {
                "type": "object",
                "properties": {"api_key": {"type": "string"}},
                "required": ["api_key"],
                "additionalProperties": False,
            }
            with pytest.raises(ToolRegistryError, match="Credentials"):
                await create_agent_tool_version(
                    db,
                    unsafe,
                    input_schema=unsafe_schema,
                    output_schema=_output_schema(),
                    handler_key="builtin.unsafe",
                    created_by_user_id=author.id,
                )
            with pytest.raises(ToolRegistryError, match="Side-effecting"):
                await create_agent_tool_version(
                    db,
                    unsafe,
                    input_schema=_input_schema(),
                    output_schema=_output_schema(),
                    handler_key="builtin.unsafe",
                    effect_type=EFFECT_SIDE_EFFECTING,
                    approval_mode="never",
                    created_by_user_id=author.id,
                )

            checker = await _user(db, "tool-checker")
            reviewed_tool = await create_agent_tool(
                db,
                name="Reviewed Tool",
                slug="reviewed-tool",
                created_by_user_id=author.id,
            )
            reviewed_version = await create_agent_tool_version(
                db,
                reviewed_tool,
                input_schema=_input_schema(),
                output_schema=_output_schema(),
                handler_key="builtin.reviewed",
                created_by_user_id=author.id,
            )
            await update_agent_tool_draft(
                db,
                reviewed_version,
                actor_user_id=publisher.id,
                timeout_seconds=25,
            )
            await submit_agent_tool_version(
                db,
                reviewed_version,
                actor_user_id=publisher.id,
            )
            with pytest.raises(ToolRegistryError, match="Maker-checker"):
                await publish_agent_tool_version(
                    db,
                    reviewed_version,
                    actor_user_id=publisher.id,
                )
            await publish_agent_tool_version(
                db,
                reviewed_version,
                actor_user_id=checker.id,
            )
            assert reviewed_version.published_by_user_id == checker.id

            events = (
                (await db.execute(select(AgentToolAuditEvent.event_type).where(AgentToolAuditEvent.tool_id == tool.id)))
                .scalars()
                .all()
            )
            assert events == [
                "agent_tool.created",
                "agent_tool.version.created",
                "agent_tool.version.submitted",
                "agent_tool.version.published",
            ]
    finally:
        await engine.dispose()


async def _test_agent_policy_resolves_pinned_tool_version() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            tool, version, _, _ = await _published_tool(db)
            agent_version = AgentVersion(
                id="agent-version",
                agent_id="agent-id",
                version_number=1,
                status="published",
                system_prompt="Use approved tools.",
                model_policy={"primary_model_id": "model::1"},
                tool_policy={
                    "tools": [
                        {
                            "slug": tool.slug,
                            "version_id": version.id,
                            "required": True,
                        }
                    ],
                    "max_calls_per_turn": 2,
                },
                fingerprint="f" * 64,
            )
            policy = resolve_agent_policies(agent_version).tools
            resolved = await resolve_agent_tools(db, policy)
            assert len(resolved) == 1
            assert resolved[0].version.id == version.id
            assert resolved[0].as_openai_tool()["function"]["name"] == "policy_lookup"
    finally:
        await engine.dispose()


@dataclass
class FakeLedger:
    completed: dict[tuple[str, str], dict] = field(default_factory=dict)
    claimed: set[tuple[str, str]] = field(default_factory=set)
    failed: list[str] = field(default_factory=list)

    async def load_completed(self, *, idempotency_key: str, tool_version_id: str):
        return self.completed.get((idempotency_key, tool_version_id))

    async def claim(
        self,
        *,
        idempotency_key: str,
        tool_version_id: str,
        correlation_id: str,
    ) -> bool:
        del correlation_id
        key = (idempotency_key, tool_version_id)
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True

    async def complete(
        self,
        *,
        idempotency_key: str,
        tool_version_id: str,
        result: dict,
    ) -> None:
        self.completed[(idempotency_key, tool_version_id)] = result

    async def fail(
        self,
        *,
        idempotency_key: str,
        tool_version_id: str,
        error_code: str,
    ) -> None:
        del idempotency_key, tool_version_id
        self.failed.append(error_code)


@dataclass
class RecordingGuardrails:
    denied_stage: str | None = None
    stages: list[str] = field(default_factory=list)

    async def evaluate(self, request):
        self.stages.append(request.stage)
        return ToolGuardrailDecision(
            allowed=request.stage != self.denied_stage,
            reason_code=f"{request.stage}_test",
        )


async def _test_executor_retries_redacts_and_enforces_approval() -> None:
    factory, engine = await _session_factory()
    try:
        async with factory() as db:
            tool, version, _, _ = await _published_tool(db)
            spec = ResolvedAgentTool(tool=tool, version=version, required=True)
            model = AIModel(
                id=1,
                connection_id=1,
                external_id="vendor/text-model",
                provider_type="openai",
                is_enabled=True,
                admin_disabled=False,
            )
            calls = 0

            async def flaky_handler(arguments, context):
                nonlocal calls
                del context
                calls += 1
                if calls == 1:
                    raise ToolTransientError("retry")
                return ToolHandlerResult(
                    payload={
                        "result": arguments["query"],
                        "api_key": "sk-this-must-never-reach-the-model",
                    },
                    cost_usd=0.015,
                )

            context = ToolExecutionContext(
                correlation_id="turn-1",
                user_id=1,
                permissions=frozenset({"policy.read"}),
            )
            budget = ToolExecutionBudget(
                max_calls=2,
                max_hops=2,
                max_total_seconds=30,
                max_cost_usd=1.0,
            )
            result = await execute_agent_tool(
                spec=spec,
                model=model,
                arguments={"query": "leave policy"},
                context=context,
                handler=flaky_handler,
                budget=budget,
                hop=0,
            )
            assert result.attempts == 2
            assert result.payload["result"] == "leave policy"
            assert result.payload["api_key"] == "[REDACTED]"
            assert result.redacted_paths == ("$.api_key",)
            assert len(result.execution_id) == 36
            assert result.guardrail_reason_codes == (
                "pre_tool_execution_policy_allow",
                "post_tool_execution_policy_allow",
            )

            denied_guardrails = RecordingGuardrails(denied_stage="pre_tool_execution")
            calls_before_denial = calls
            with pytest.raises(ToolPolicyDenied, match="pre_tool_execution"):
                await execute_agent_tool(
                    spec=spec,
                    model=model,
                    arguments={"query": "blocked by guardrail"},
                    context=context,
                    handler=flaky_handler,
                    budget=budget,
                    hop=0,
                    guardrails=denied_guardrails,
                )
            assert calls == calls_before_denial
            assert denied_guardrails.stages == ["pre_tool_execution"]

            with pytest.raises(ToolPolicyDenied, match="Credential-like"):
                await execute_agent_tool(
                    spec=spec,
                    model=model,
                    arguments={"query": "Bearer very-secret-token-value"},
                    context=context,
                    handler=flaky_handler,
                    budget=budget,
                    hop=0,
                )

            version.effect_type = EFFECT_SIDE_EFFECTING
            version.approval_mode = APPROVAL_REQUIRED
            with pytest.raises(ToolApprovalRequired):
                await execute_agent_tool(
                    spec=spec,
                    model=model,
                    arguments={"query": "create ticket"},
                    context=context,
                    handler=flaky_handler,
                    budget=budget,
                    hop=0,
                    ledger=FakeLedger(),
                )
            approved = ToolExecutionContext(
                correlation_id="turn-2",
                user_id=1,
                permissions=frozenset({"policy.read"}),
                user_approved=True,
                idempotency_key="ticket-123",
            )
            ledger = FakeLedger()

            async def side_effect_handler(arguments, context):
                del context
                return {
                    "result": arguments["query"],
                    "api_key": "safe-public-value",
                }

            side_effect_budget = ToolExecutionBudget(
                max_calls=3,
                max_hops=2,
                max_total_seconds=30,
                max_cost_usd=1.0,
            )
            first = await execute_agent_tool(
                spec=spec,
                model=model,
                arguments={"query": "create ticket"},
                context=approved,
                handler=side_effect_handler,
                budget=side_effect_budget,
                hop=0,
                ledger=ledger,
            )
            second = await execute_agent_tool(
                spec=spec,
                model=model,
                arguments={"query": "create ticket"},
                context=approved,
                handler=side_effect_handler,
                budget=side_effect_budget,
                hop=0,
                ledger=ledger,
            )
            assert not first.cached
            assert second.cached

            denied_context = ToolExecutionContext(
                correlation_id="turn-3",
                user_id=1,
            )
            with pytest.raises(ToolPolicyDenied, match="Missing required permission"):
                await execute_agent_tool(
                    spec=spec,
                    model=model,
                    arguments={"query": "x"},
                    context=denied_context,
                    handler=side_effect_handler,
                    budget=side_effect_budget,
                    hop=0,
                    ledger=ledger,
                )
    finally:
        await engine.dispose()


def test_registry_lifecycle_and_schema_guards():
    asyncio.run(_test_registry_lifecycle_and_schema_guards())


def test_agent_policy_resolves_pinned_tool_version():
    asyncio.run(_test_agent_policy_resolves_pinned_tool_version())


def test_executor_retries_redacts_and_enforces_approval():
    asyncio.run(_test_executor_retries_redacts_and_enforces_approval())
