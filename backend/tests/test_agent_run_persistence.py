"""Regression tests for Agent run / retrieval-trace persistence ordering."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.agent_runtime import AgentRetrievalTrace, AgentRun
from app.services.agent_routing_service import AgentRoutingDecision
from app.services.agent_run_service import persist_agent_plan
from app.services.agent_runtime_service import AgentTurnPlan
from app.services.knowledge_retrieval_service import (
    KnowledgeContextPack,
    KnowledgeRetrievalResult,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    ), engine


def _abstained_plan() -> AgentTurnPlan:
    plan_id = str(uuid.uuid4())
    retrieval = KnowledgeRetrievalResult(
        evidence=(),
        context=KnowledgeContextPack(
            text="",
            citations=(),
            estimated_tokens=0,
            truncated=False,
        ),
        answerable=False,
        abstention_reason="no_evidence",
        knowledge_release_ids=(),
        index_version_ids=(),
        candidate_count=0,
        post_authorized_count=0,
        component_errors=(),
    )
    return AgentTurnPlan(
        status="abstained",
        routing=AgentRoutingDecision(
            kind="explicit",
            target=None,
            confidence=1.0,
            alternatives=(),
            reason="test",
        ),
        target=None,
        model=None,
        policies=None,
        prompt=None,
        retrieval=retrieval,
        tools=(),
        guardrail_decisions=(),
        egress_manifest=None,
        safe_response="No governed evidence is available.",
        plan_id=plan_id,
        routing_outcome="explicit",
        routing_reason="test",
        selected_agent_id=None,
        selected_agent_version_id=None,
        selected_provider_id=None,
        selected_model_id=None,
        retrieval_outcome="no_evidence",
        retrieval_result_count=0,
        tool_execution_ids=(),
        handoff_event_ids=(),
        provider_latency_ms=None,
        total_planning_latency_ms=5,
        retrieval_latency_ms=2,
        query_sha256="a" * 64,
    )


def test_persist_agent_plan_inserts_run_before_trace_under_fk_enforcement():
    async def _run() -> None:
        session_factory, engine = await _session_factory()
        try:
            async with session_factory() as db:
                plan = _abstained_plan()
                row = await persist_agent_plan(
                    db,
                    plan=plan,
                    source="chat",
                    client_app="test",
                    user_id=None,
                    alpha_router_api_key_id=None,
                    chat_session_id=None,
                    external_session_id=None,
                    private_mode=False,
                )
                await db.commit()
                assert row.id == plan.plan_id
                runs = (
                    await db.execute(select(AgentRun).where(AgentRun.id == row.id))
                ).scalars().all()
                traces = (
                    await db.execute(
                        select(AgentRetrievalTrace).where(
                            AgentRetrievalTrace.agent_run_id == row.id
                        )
                    )
                ).scalars().all()
                assert len(runs) == 1
                assert len(traces) == 1
                assert traces[0].outcome == "no_evidence"
        finally:
            await engine.dispose()

    asyncio.run(_run())
