"""Resolve auto-router catalog entries to a concrete image-capable model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.models.logging import RequestLog
from app.services.chat_feedback_service import feedback_quality_signals
from app.services.model_capabilities import image_generation_capabilities
from app.services.openrouter_image_service import is_openrouter_auto_model


@dataclass(frozen=True)
class ImageModelResolution:
    external_id: str
    model: AIModel
    connection: Connection
    score: int
    reason: dict[str, object]


def _catalog_raw(pricing_raw: str | None) -> dict[str, object]:
    try:
        parsed = json.loads(pricing_raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _strength_ratio(external_id: str, pricing_raw: str | None) -> float:
    ext = external_id.lower()
    raw = _catalog_raw(pricing_raw)
    text = " ".join(
        [ext, str(raw.get("name") or ""), str(raw.get("description") or "")]
    ).lower()
    if any(term in text for term in ("ultra", "max", "pro", "gpt-image-1", "imagen")):
        return 1.0
    if any(term in text for term in ("lite", "mini", "small", "turbo")):
        return 0.42
    if "flash" in text:
        return 0.68
    return 0.78


def _newness_ratio(external_id: str, pricing_raw: str | None) -> float:
    raw = _catalog_raw(pricing_raw)
    created = raw.get("created")
    if created is not None:
        try:
            year = datetime.fromtimestamp(int(created), tz=timezone.utc).year
            return max(0.1, min(1.0, (year - 2021) / 6))
        except (TypeError, ValueError, OSError):
            pass
    versions = re.findall(r"(?<!\d)(\d{1,2})(?:[._-](\d{1,2}))?", external_id)
    for major_text, minor_text in versions:
        major = int(major_text)
        if 2 <= major <= 20:
            version = major + (int(minor_text or 0) / 10)
            return max(0.2, min(1.0, version / 4))
    return 0.5


def _capability_ratio(
    external_id: str,
    *,
    is_image_model: bool,
    pricing_raw: str | None,
) -> float:
    caps = image_generation_capabilities(
        external_id=external_id,
        is_image_model=is_image_model,
        pricing_raw=pricing_raw,
    )
    if not caps.get("supports_text_to_image"):
        return 0.0
    ratio = 0.65
    if caps.get("supports_image_to_image"):
        ratio += 0.15
    text = f"{external_id} {pricing_raw or ''}".lower()
    if "4k" in text or "4096" in text:
        ratio += 0.2
    elif "2k" in text or "2048" in text or "hd" in text:
        ratio += 0.1
    return min(1.0, ratio)


def image_model_score_details(
    external_id: str,
    *,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
    feedback_score: float = 0.75,
    feedback_count: int = 0,
    stability_score: float = 0.9,
    stability_count: int = 0,
) -> dict[str, object]:
    """Quality-first score: strength 35%, newness 20%, capabilities 15%,
    Bayesian user satisfaction 20%, and stability 10%. Cost is intentionally absent.
    """
    ext = (external_id or "").strip().lower()
    if is_openrouter_auto_model(ext):
        return {"total": -1, "eligible": False}
    capability = _capability_ratio(
        external_id,
        is_image_model=is_image_model,
        pricing_raw=pricing_raw,
    )
    if capability <= 0:
        return {"total": 0, "eligible": False}
    strength = _strength_ratio(ext, pricing_raw)
    newness = _newness_ratio(ext, pricing_raw)
    maturity = 0.65 if any(x in ext for x in ("preview", "experimental", "beta")) else 1.0
    stable = max(0.0, min(1.0, float(stability_score))) * maturity
    satisfaction = max(0.0, min(1.0, float(feedback_score)))
    components = {
        "strength": round(strength * 350),
        "newness": round(newness * 200),
        "capabilities": round(capability * 150),
        "user_satisfaction": round(satisfaction * 200),
        "stability": round(stable * 100),
    }
    return {
        "total": int(sum(components.values())),
        "eligible": True,
        "components": components,
        "feedback_count": int(feedback_count),
        "feedback_score": round(satisfaction, 4),
        "stability_count": int(stability_count),
        "stability_score": round(stable, 4),
        "policy": "quality-first-hybrid-v1",
        "cost_considered": False,
    }


def score_image_model_candidate(
    external_id: str,
    *,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
    feedback_score: float = 0.75,
    feedback_count: int = 0,
    stability_score: float = 0.9,
    stability_count: int = 0,
) -> int:
    """Higher score = better quality-first Auto Router candidate."""
    return int(
        image_model_score_details(
            external_id,
            is_image_model=is_image_model,
            pricing_raw=pricing_raw,
            feedback_score=feedback_score,
            feedback_count=feedback_count,
            stability_score=stability_score,
            stability_count=stability_count,
        )["total"]
    )


async def _model_stability_signals(
    db: AsyncSession,
    model_ids: list[str],
) -> dict[str, dict[str, float | int]]:
    if not model_ids:
        return {}
    rows = (
        await db.execute(
            select(
                RequestLog.model_id,
                func.count(RequestLog.id),
                func.sum(case((RequestLog.success == True, 1), else_=0)),  # noqa: E712
            )
            .where(RequestLog.model_id.in_(model_ids))
            .group_by(RequestLog.model_id)
        )
    ).all()
    out: dict[str, dict[str, float | int]] = {}
    prior_mean = 0.9
    prior_weight = 10.0
    for model_id, total, successes in rows:
        count = int(total or 0)
        success_count = int(successes or 0)
        out[str(model_id)] = {
            "count": count,
            "score": (success_count + prior_mean * prior_weight) / (count + prior_weight),
        }
    return out


def _image_model_rank(external_id: str, score: int) -> tuple[int, int, int, str]:
    """Lower tuple wins: higher score, then non-lite, then non-preview."""
    ext = (external_id or "").lower()
    lite_penalty = 1 if "lite" in ext else 0
    preview_penalty = 1 if "preview" in ext else 0
    return (-score, lite_penalty, preview_penalty, ext)


async def resolve_auto_router_image_model(
    db: AsyncSession,
    *,
    connection_id: int | None = None,
) -> tuple[str, AIModel, Connection] | None:
    """
    Pick an enabled image model on the same connection as an auto-router selection.

    Auto-router entries are text-only routing; image generation must target a concrete
    image-capable catalog model on that connection (any provider).
    """
    stmt = (
        select(AIModel, Connection)
        .join(Connection, Connection.id == AIModel.connection_id)
        .where(
            AIModel.is_enabled == True,  # noqa: E712
            Connection.is_active == True,  # noqa: E712
        )
    )
    if connection_id is not None:
        stmt = stmt.where(Connection.id == connection_id)

    resolution = await resolve_auto_router_image_model_with_details(
        db,
        connection_id=connection_id,
        statement=stmt,
    )
    if resolution is None:
        return None
    return resolution.external_id, resolution.model, resolution.connection


async def resolve_auto_router_image_model_with_details(
    db: AsyncSession,
    *,
    connection_id: int | None = None,
    statement=None,
) -> ImageModelResolution | None:
    if statement is None:
        statement = (
            select(AIModel, Connection)
            .join(Connection, Connection.id == AIModel.connection_id)
            .where(
                AIModel.is_enabled == True,  # noqa: E712
                Connection.is_active == True,  # noqa: E712
            )
        )
        if connection_id is not None:
            statement = statement.where(Connection.id == connection_id)
    rows = (await db.execute(statement)).all()
    feedback = await feedback_quality_signals(
        db,
        model_ids=[str(model.external_id) for model, _ in rows],
        output_kind="image",
    )
    stability = await _model_stability_signals(
        db,
        [str(model.external_id) for model, _ in rows],
    )
    best: ImageModelResolution | None = None
    best_rank: tuple[int, int, int, str] | None = None
    for model, conn in rows:
        signal = feedback.get(str(model.external_id), {})
        stability_signal = stability.get(str(model.external_id), {})
        details = image_model_score_details(
            model.external_id or "",
            is_image_model=bool(model.is_image_model),
            pricing_raw=model.pricing_raw,
            feedback_score=float(signal.get("score", 0.75)),
            feedback_count=int(signal.get("count", 0)),
            stability_score=float(stability_signal.get("score", 0.9)),
            stability_count=int(stability_signal.get("count", 0)),
        )
        score = int(details["total"])
        if score <= 0:
            continue
        rank = _image_model_rank(model.external_id or "", score)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = ImageModelResolution(
                external_id=model.external_id,
                model=model,
                connection=conn,
                score=score,
                reason=details,
            )
    return best


async def resolve_openrouter_auto_image_model(
    db: AsyncSession,
    *,
    connection_id: int | None = None,
) -> tuple[str, AIModel, Connection] | None:
    """Backward-compatible alias for OpenRouter auto-router image resolution."""
    return await resolve_auto_router_image_model(db, connection_id=connection_id)
