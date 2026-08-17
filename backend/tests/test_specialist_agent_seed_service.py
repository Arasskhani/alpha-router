"""Regression tests for the idempotent Phase 10 specialist bootstrap."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.admin_agents import (
    ReasonBody,
    approve_domain_binding,
    approve_knowledge_binding,
)
from app.database import Base
from app.models.agent import Agent, AgentKnowledgeBinding, AgentVersion
from app.models.evaluation import EvaluationCase, EvaluationDataset
from app.models.governance import GovernanceAuditEvent
from app.models.knowledge import KnowledgeBase
from app.models.user import User
from app.services import specialist_agent_seed_service as seed_service
from app.services.agent_evaluation_service import activate_evaluation_dataset


async def _exercise_specialist_seed() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            actor = User(
                username="seed-actor",
                email="seed-actor@test",
                hashed_password="x",
                auth_provider="local",
            )
            knowledge_reviewer = User(
                username="knowledge-reviewer",
                email="knowledge-reviewer@test",
                hashed_password="x",
                auth_provider="local",
            )
            domain_reviewer = User(
                username="domain-reviewer",
                email="domain-reviewer@test",
                hashed_password="x",
                auth_provider="local",
            )
            db.add_all([actor, knowledge_reviewer, domain_reviewer])
            await db.flush()
            original_get_settings = seed_service.get_settings
            seed_service.get_settings = lambda: SimpleNamespace(
                seed_specialist_agents_enabled=True,
                seed_agent_primary_model_id="openrouter/auto",
            )
            try:
                first = await seed_service.seed_specialist_agents(
                    db,
                    actor_user_id=actor.id,
                )
                await db.flush()
                second = await seed_service.seed_specialist_agents(
                    db,
                    actor_user_id=actor.id,
                )
                await db.flush()
            finally:
                seed_service.get_settings = original_get_settings

            assert first["created_agents"] == 5
            assert first["created_versions"] == 5
            assert first["created_knowledge_bases"] == 5
            assert first["created_bindings"] == 5
            assert first["created_datasets"] == 5
            assert second["created_agents"] == 0
            assert second["created_versions"] == 0
            assert second["created_knowledge_bases"] == 0
            assert second["created_bindings"] == 0
            assert second["created_datasets"] == 0

            agents = (
                await db.execute(select(Agent).order_by(Agent.slug))
            ).scalars().all()
            assert {row.slug for row in agents} == {
                "finance-consultant",
                "hr-assistant",
                "it-helpdesk",
                "legal-consultant",
                "marketing-consultant",
            }
            assert all(row.is_system and row.status == "active" for row in agents)
            by_slug = {row.slug: row for row in agents}
            assert by_slug["it-helpdesk"].access_type == "public"
            assert by_slug["marketing-consultant"].access_type == "public"
            assert by_slug["hr-assistant"].access_type == "private"
            assert by_slug["legal-consultant"].access_type == "private"
            assert by_slug["finance-consultant"].access_type == "private"

            versions = (await db.execute(select(AgentVersion))).scalars().all()
            assert len(versions) == 5
            assert all(row.status == "published" for row in versions)
            assert all(row.retrieval_policy["fail_closed"] for row in versions)
            assert all(row.locale_policy["supported_locales"] == ["fa", "en"] for row in versions)
            version_by_agent = {row.agent_id: row for row in versions}
            assert version_by_agent[by_slug["it-helpdesk"].id].memory_policy["enabled"]
            assert version_by_agent[by_slug["marketing-consultant"].id].memory_policy[
                "enabled"
            ]
            assert not version_by_agent[
                by_slug["legal-consultant"].id
            ].memory_policy["enabled"]

            knowledge_bases = (
                await db.execute(select(KnowledgeBase))
            ).scalars().all()
            assert len(knowledge_bases) == 5
            assert {
                row.sensitivity for row in knowledge_bases
            } == {
                "internal",
                "hr_confidential",
                "legal_privileged",
                "finance_restricted",
            }
            bindings = (
                await db.execute(select(AgentKnowledgeBinding))
            ).scalars().all()
            assert len(bindings) == 5
            assert all(row.status == "pending_kb_approval" for row in bindings)
            assert all(row.release_mode == "latest" for row in bindings)
            knowledge_by_id = {row.id: row for row in knowledge_bases}
            binding_by_kb_slug = {
                knowledge_by_id[row.knowledge_base_id].slug: row for row in bindings
            }
            it_binding = binding_by_kb_slug["it-helpdesk-knowledge"]
            legal_binding = binding_by_kb_slug["legal-consultant-knowledge"]
            with pytest.raises(HTTPException) as same_actor_error:
                await approve_knowledge_binding(
                    it_binding.id,
                    ReasonBody(reason="Invalid self approval"),
                    db,
                    actor,
                )
            assert same_actor_error.value.status_code == 409
            await approve_knowledge_binding(
                it_binding.id,
                ReasonBody(reason="Knowledge owner approved the empty scope"),
                db,
                knowledge_reviewer,
            )
            assert it_binding.status == "published"
            await approve_knowledge_binding(
                legal_binding.id,
                ReasonBody(reason="Legal Knowledge owner approved the scope"),
                db,
                knowledge_reviewer,
            )
            assert legal_binding.status == "pending_domain_approval"
            with pytest.raises(HTTPException) as same_reviewer_error:
                await approve_domain_binding(
                    legal_binding.id,
                    ReasonBody(reason="Invalid repeated approval"),
                    db,
                    knowledge_reviewer,
                )
            assert same_reviewer_error.value.status_code == 409
            await approve_domain_binding(
                legal_binding.id,
                ReasonBody(reason="Independent Legal approver accepted the scope"),
                db,
                domain_reviewer,
            )
            assert legal_binding.status == "published"

            datasets = (
                await db.execute(select(EvaluationDataset))
            ).scalars().all()
            assert len(datasets) == 5
            assert all(row.status == "draft" for row in datasets)
            assert all(row.minimum_case_count == 100 for row in datasets)
            assert all(
                row.metadata_json["requires_knowledge_curation"] for row in datasets
            )
            with pytest.raises(ValueError, match="require Knowledge curation"):
                await activate_evaluation_dataset(
                    db,
                    datasets[0],
                    actor_user_id=actor.id,
                )
            case_count = (
                await db.execute(select(func.count()).select_from(EvaluationCase))
            ).scalar_one()
            assert case_count == 500
            completion_events = (
                await db.execute(
                    select(func.count())
                    .select_from(GovernanceAuditEvent)
                    .where(
                        GovernanceAuditEvent.event_type
                        == "governance.seed.specialist_agents.completed"
                    )
                )
            ).scalar_one()
            assert completion_events == 1
    finally:
        await engine.dispose()


def test_specialist_seed_is_idempotent_and_safe() -> None:
    asyncio.run(_exercise_specialist_seed())


async def _exercise_seed_does_not_restore_deleted_system_resources() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            actor = User(
                username="seed-restore-actor",
                email="seed-restore@test",
                hashed_password="x",
                auth_provider="local",
            )
            db.add(actor)
            await db.flush()
            original_get_settings = seed_service.get_settings
            seed_service.get_settings = lambda: SimpleNamespace(
                seed_specialist_agents_enabled=True,
                seed_agent_primary_model_id="openrouter/auto",
            )
            try:
                await seed_service.seed_specialist_agents(db, actor_user_id=actor.id)
                await db.flush()

                hr_id = seed_service._seed_uuid("knowledge-base:hr-assistant-knowledge")
                hr = await db.get(KnowledgeBase, hr_id)
                assert hr is not None
                hr.slug = f"purged-{hr.id}"
                hr.name = "[Deleted] HR Assistant Knowledge"
                hr.status = "archived"
                hr.description = None
                await db.flush()

                helpdesk = (
                    await db.execute(
                        select(Agent).where(Agent.slug == "it-helpdesk")
                    )
                ).scalar_one()
                helpdesk.slug = f"purged-{helpdesk.id}"
                helpdesk.name = "[Deleted] IT Helpdesk"
                helpdesk.status = "archived"
                helpdesk.is_system = False
                helpdesk.description = None
                await db.flush()

                legal = (
                    await db.execute(
                        select(Agent).where(Agent.slug == "legal-consultant")
                    )
                ).scalar_one()
                legal.status = "archived"
                await db.flush()

                again = await seed_service.seed_specialist_agents(
                    db,
                    actor_user_id=actor.id,
                )
                await db.flush()
            finally:
                seed_service.get_settings = original_get_settings

            assert again["created_agents"] == 0
            assert again["created_knowledge_bases"] == 0

            restored_hr = await db.get(KnowledgeBase, hr_id)
            assert restored_hr is not None
            assert restored_hr.slug == f"purged-{hr_id}"
            assert restored_hr.status == "archived"
            assert restored_hr.name == "[Deleted] HR Assistant Knowledge"
            assert (
                await db.execute(
                    select(func.count())
                    .select_from(KnowledgeBase)
                    .where(KnowledgeBase.slug == "hr-assistant-knowledge")
                )
            ).scalar_one() == 0
            assert (
                await db.execute(
                    select(func.count())
                    .select_from(KnowledgeBase)
                    .where(KnowledgeBase.id == hr_id)
                )
            ).scalar_one() == 1

            restored_helpdesk = await db.get(Agent, helpdesk.id)
            assert restored_helpdesk is not None
            assert restored_helpdesk.slug == f"purged-{helpdesk.id}"
            assert restored_helpdesk.status == "archived"
            assert restored_helpdesk.name == "[Deleted] IT Helpdesk"
            assert (
                await db.execute(
                    select(func.count())
                    .select_from(Agent)
                    .where(Agent.slug == "it-helpdesk")
                )
            ).scalar_one() == 0

            restored_legal = await db.get(Agent, legal.id)
            assert restored_legal is not None
            assert restored_legal.slug == "legal-consultant"
            assert restored_legal.status == "archived"

            remaining = (
                await db.execute(
                    select(Agent).where(Agent.status == "active")
                )
            ).scalars().all()
            assert {row.slug for row in remaining} == {
                "finance-consultant",
                "hr-assistant",
                "marketing-consultant",
            }
    finally:
        await engine.dispose()


def test_specialist_seed_does_not_restore_deleted_system_resources() -> None:
    asyncio.run(_exercise_seed_does_not_restore_deleted_system_resources())


async def _exercise_seed_preserves_operator_retention_days() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            actor = User(
                username="seed-retention-actor",
                email="seed-retention@test",
                hashed_password="x",
                auth_provider="local",
            )
            db.add(actor)
            await db.flush()
            original_get_settings = seed_service.get_settings
            seed_service.get_settings = lambda: SimpleNamespace(
                seed_specialist_agents_enabled=True,
                seed_agent_primary_model_id="openrouter/auto",
            )
            try:
                await seed_service.seed_specialist_agents(db, actor_user_id=actor.id)
                await db.flush()
                kb_id = seed_service._seed_uuid(
                    "knowledge-base:it-helpdesk-knowledge"
                )
                knowledge_base = await db.get(KnowledgeBase, kb_id)
                assert knowledge_base is not None
                assert knowledge_base.retention_days == 1095
                knowledge_base.retention_days = 1
                await db.flush()
                await seed_service.seed_specialist_agents(db, actor_user_id=actor.id)
                await db.flush()
            finally:
                seed_service.get_settings = original_get_settings

            kept = await db.get(KnowledgeBase, kb_id)
            assert kept is not None
            assert kept.retention_days == 1
    finally:
        await engine.dispose()


def test_specialist_seed_preserves_operator_retention_days() -> None:
    asyncio.run(_exercise_seed_preserves_operator_retention_days())
