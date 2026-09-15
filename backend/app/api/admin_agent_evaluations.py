"""Administrative golden datasets, scorecards, reviews, and publish gates."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_agent_permission
from app.database import get_db
from app.models.agent import Agent, AgentVersion
from app.models.evaluation import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
)
from app.models.user import User
from app.services.agent_evaluation_service import (
    activate_evaluation_dataset,
    create_evaluation_dataset,
    evaluation_publish_gate_status,
    replace_evaluation_cases,
    review_evaluation_run,
    run_evaluation,
)

router = APIRouter(
    prefix="/api/admin/agents/evaluations",
    tags=["admin-agent-evaluations"],
)


class EvaluationDatasetCreateBody(BaseModel):
    agent_id: str = Field(min_length=1, max_length=36)
    slug: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8_000)
    minimum_case_count: int = Field(default=100, ge=1, le=10_000)
    is_publish_gate: bool = True
    thresholds: dict[str, Any] = Field(default_factory=dict)


class EvaluationCaseBody(BaseModel):
    case_key: str = Field(min_length=1, max_length=160)
    category: str = Field(min_length=1, max_length=24)
    language: str = Field(min_length=1, max_length=16)
    prompt: str = Field(min_length=1, max_length=20_000)
    expected: dict[str, Any]
    tags: list[str] = Field(default_factory=list, max_length=50)
    weight: float = Field(default=1.0, gt=0, le=100)
    enabled: bool = True


class EvaluationCasesReplaceBody(BaseModel):
    cases: list[EvaluationCaseBody] = Field(min_length=1, max_length=10_000)


class EvaluationObservationBody(BaseModel):
    selected_agent_id: str | None = Field(default=None, max_length=128)
    retrieved_document_version_ids: list[str] = Field(
        default_factory=list,
        max_length=200,
    )
    cited_document_version_ids: list[str] = Field(
        default_factory=list,
        max_length=200,
    )
    abstained: bool | None = None
    escalated: bool | None = None
    injection_resisted: bool | None = None
    acl_leak_detected: bool | None = None
    quality_passed: bool | None = None
    latency_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    cost_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    output_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    judge: dict[str, Any] | None = None


class EvaluationRunCaseBody(BaseModel):
    case_key: str = Field(min_length=1, max_length=160)
    observation: EvaluationObservationBody


class EvaluationRunCreateBody(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=36)
    agent_version_id: str = Field(min_length=1, max_length=36)
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        min_length=1,
        max_length=128,
    )
    trigger_type: str = Field(
        default="manual",
        pattern=r"^(manual|publish_gate|ci|seed|scheduled)$",
    )
    observations: list[EvaluationRunCaseBody] = Field(
        min_length=1,
        max_length=10_000,
    )


class EvaluationRunReviewBody(BaseModel):
    approved: bool
    notes: str | None = Field(default=None, max_length=2_000)


def _dataset_payload(
    dataset: EvaluationDataset,
    *,
    case_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "agent_id": dataset.agent_id,
        "slug": dataset.slug,
        "name": dataset.name,
        "description": dataset.description,
        "version_number": dataset.version_number,
        "status": dataset.status,
        "minimum_case_count": dataset.minimum_case_count,
        "is_publish_gate": bool(dataset.is_publish_gate),
        "thresholds": dataset.thresholds_json or {},
        "case_count": int(case_count),
        "created_by_user_id": dataset.created_by_user_id,
        "activated_by_user_id": dataset.activated_by_user_id,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "activated_at": dataset.activated_at,
        "archived_at": dataset.archived_at,
    }


def _case_payload(case: EvaluationCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "case_key": case.case_key,
        "category": case.category,
        "language": case.language,
        "prompt": case.prompt,
        "expected": case.expected_json or {},
        "tags": case.tags_json or [],
        "weight": float(case.weight or 1.0),
        "enabled": bool(case.enabled),
        "created_at": case.created_at,
    }


def _run_payload(run: EvaluationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "dataset_id": run.dataset_id,
        "agent_version_id": run.agent_version_id,
        "dataset_snapshot_hash": run.dataset_snapshot_hash,
        "trigger_type": run.trigger_type,
        "status": run.status,
        "review_status": run.review_status,
        "case_count": run.case_count,
        "passed_case_count": run.passed_case_count,
        "failed_case_count": run.failed_case_count,
        "skipped_case_count": run.skipped_case_count,
        "metrics": run.metrics_json or {},
        "threshold_results": run.threshold_results_json or {},
        "deterministic_gate_passed": bool(run.deterministic_gate_passed),
        "error_code": run.error_code,
        "error_message": run.error_message,
        "created_by_user_id": run.created_by_user_id,
        "reviewed_by_user_id": run.reviewed_by_user_id,
        "review_notes": run.review_notes,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "reviewed_at": run.reviewed_at,
    }


async def _dataset_or_404(
    db: AsyncSession,
    dataset_id: str,
) -> EvaluationDataset:
    dataset = await db.get(EvaluationDataset, dataset_id)
    if dataset is None:
        raise HTTPException(404, "Evaluation dataset not found")
    return dataset


async def _run_or_404(db: AsyncSession, run_id: str) -> EvaluationRun:
    run = await db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(404, "Evaluation run not found")
    return run


@router.get("/datasets")
async def list_evaluation_datasets(
    agent_id: str | None = Query(default=None, max_length=36),
    status: str | None = Query(default=None, pattern=r"^(draft|active|archived)$"),
    limit: int = Query(default=250, ge=1, le=1_000),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("evaluation.read")),
):
    statement = (
        select(
            EvaluationDataset,
            Agent.name,
            func.count(EvaluationCase.id),
        )
        .join(Agent, Agent.id == EvaluationDataset.agent_id)
        .outerjoin(
            EvaluationCase,
            EvaluationCase.dataset_id == EvaluationDataset.id,
        )
        .group_by(EvaluationDataset.id, Agent.name)
        .order_by(Agent.name, EvaluationDataset.slug, EvaluationDataset.version_number.desc())
        .limit(limit)
    )
    if agent_id:
        statement = statement.where(EvaluationDataset.agent_id == agent_id)
    if status:
        statement = statement.where(EvaluationDataset.status == status)
    rows = (await db.execute(statement)).all()
    return {
        "items": [
            {
                **_dataset_payload(dataset, case_count=int(case_count or 0)),
                "agent_name": agent_name,
            }
            for dataset, agent_name, case_count in rows
        ]
    }


@router.post("/datasets")
async def create_dataset(
    body: EvaluationDatasetCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("evaluation.manage")),
):
    try:
        dataset = await create_evaluation_dataset(
            db,
            agent_id=body.agent_id,
            slug=body.slug,
            name=body.name,
            description=body.description,
            minimum_case_count=body.minimum_case_count,
            is_publish_gate=body.is_publish_gate,
            thresholds=body.thresholds,
            actor_user_id=user.id,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _dataset_payload(dataset)


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("evaluation.read")),
):
    dataset = await _dataset_or_404(db, dataset_id)
    cases = (
        (
            await db.execute(
                select(EvaluationCase).where(EvaluationCase.dataset_id == dataset.id).order_by(EvaluationCase.case_key)
            )
        )
        .scalars()
        .all()
    )
    return {
        **_dataset_payload(dataset, case_count=len(cases)),
        "cases": [_case_payload(case) for case in cases],
    }


@router.put("/datasets/{dataset_id}/cases")
async def replace_dataset_cases(
    dataset_id: str,
    body: EvaluationCasesReplaceBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("evaluation.manage")),
):
    dataset = await _dataset_or_404(db, dataset_id)
    try:
        rows = await replace_evaluation_cases(
            db,
            dataset,
            cases=[case.model_dump() for case in body.cases],
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"dataset_id": dataset.id, "case_count": len(rows)}


@router.post("/datasets/{dataset_id}/activate")
async def activate_dataset(
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("evaluation.manage")),
):
    dataset = await _dataset_or_404(db, dataset_id)
    try:
        await activate_evaluation_dataset(
            db,
            dataset,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _dataset_payload(dataset)


@router.get("/runs")
async def list_evaluation_runs(
    dataset_id: str | None = Query(default=None, max_length=36),
    agent_version_id: str | None = Query(default=None, max_length=36),
    status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=250, ge=1, le=1_000),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("evaluation.read")),
):
    statement = select(EvaluationRun).order_by(
        EvaluationRun.created_at.desc(),
        EvaluationRun.id.desc(),
    )
    if dataset_id:
        statement = statement.where(EvaluationRun.dataset_id == dataset_id)
    if agent_version_id:
        statement = statement.where(EvaluationRun.agent_version_id == agent_version_id)
    if status:
        statement = statement.where(EvaluationRun.status == status)
    rows = (await db.execute(statement.limit(limit))).scalars().all()
    return {"items": [_run_payload(row) for row in rows]}


@router.post("/runs")
async def create_evaluation_run(
    body: EvaluationRunCreateBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("evaluation.run")),
):
    dataset = await _dataset_or_404(db, body.dataset_id)
    version = await db.get(AgentVersion, body.agent_version_id)
    if version is None:
        raise HTTPException(404, "Agent version not found")
    try:
        run = await run_evaluation(
            db,
            dataset=dataset,
            agent_version=version,
            observations=[
                {
                    "case_key": item.case_key,
                    "observation": item.observation.model_dump(exclude_none=True),
                }
                for item in body.observations
            ],
            idempotency_key=body.idempotency_key,
            trigger_type=body.trigger_type,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _run_payload(run)


@router.get("/runs/{run_id}")
async def get_evaluation_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("evaluation.read")),
):
    run = await _run_or_404(db, run_id)
    results = (
        await db.execute(
            select(EvaluationResult, EvaluationCase)
            .join(EvaluationCase, EvaluationCase.id == EvaluationResult.case_id)
            .where(EvaluationResult.run_id == run.id)
            .order_by(EvaluationCase.case_key)
        )
    ).all()
    return {
        **_run_payload(run),
        "results": [
            {
                "id": result.id,
                "case_id": case.id,
                "case_key": case.case_key,
                "category": case.category,
                "language": case.language,
                "status": result.status,
                "evaluator_type": result.evaluator_type,
                "metrics": result.metrics_json or {},
                "failure_codes": result.failure_codes_json or [],
                "latency_ms": result.latency_ms,
                "cost_usd": float(result.cost_usd or 0),
                "output_sha256": result.output_sha256,
                "judge": result.judge_metadata_json or {},
            }
            for result, case in results
        ],
    }


@router.post("/runs/{run_id}/review")
async def review_run(
    run_id: str,
    body: EvaluationRunReviewBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_agent_permission("evaluation.manage")),
):
    run = await _run_or_404(db, run_id)
    try:
        await review_evaluation_run(
            db,
            run,
            approved=body.approved,
            notes=body.notes,
            actor_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _run_payload(run)


@router.get("/versions/{agent_version_id}/gate")
async def get_version_evaluation_gate(
    agent_version_id: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_agent_permission("evaluation.read")),
):
    version = await db.get(AgentVersion, agent_version_id)
    if version is None:
        raise HTTPException(404, "Agent version not found")
    status = await evaluation_publish_gate_status(db, version)
    return {
        "agent_version_id": version.id,
        "required": status.required,
        "ready": status.ready,
        "datasets": [
            {
                "dataset_id": item.dataset_id,
                "dataset_name": item.dataset_name,
                "snapshot_hash": item.snapshot_hash,
                "passing_run_id": item.passing_run_id,
                "ready": item.ready,
                "reason": item.reason,
            }
            for item in status.datasets
        ],
    }
