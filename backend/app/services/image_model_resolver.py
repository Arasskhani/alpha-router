"""Resolve auto-router catalog entries to concrete image-capable models.

Scoring is measurement-first: recent success rate, successful latency, user
feedback, and real capabilities. Marketing-name "strength" is intentionally
absent — labels like pro/flash do not predict reliability.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.logging import ImageGenerationAttempt, RequestLog
from app.models.model_catalog import AIModel
from app.services.chat_feedback_service import feedback_quality_signals
from app.services.model_capabilities import image_generation_capabilities
from app.services.openrouter_image_service import is_openrouter_auto_model

# Recent-window signals so a currently-flaky model can lose rank quickly.
_STABILITY_WINDOW = timedelta(hours=72)
_STABILITY_PRIOR_MEAN = 0.75
_STABILITY_PRIOR_WEIGHT = 5.0
_MIN_SAMPLES_FOR_HARD_THRESHOLD = 8
_HARD_SUCCESS_FLOOR = 0.70
# Latency score: ~5s → high, ~45s+ → low (successful requests only).
_LATENCY_HALF_LIFE_MS = 12_000.0
_AUTO_ROUTER_FAILOVER_LIMIT = 2
_AUTO_ROUTER_MAX_AVG_SUCCESS_MS = 20_000.0


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
    ratio = 0.7
    if caps.get("supports_image_to_image"):
        ratio += 0.2
    text = f"{external_id} {pricing_raw or ''}".lower()
    if "4k" in text or "4096" in text:
        ratio += 0.1
    elif "2k" in text or "2048" in text or "hd" in text:
        ratio += 0.05
    return min(1.0, ratio)


def _latency_ratio(avg_success_ms: float | None, *, sample_count: int) -> float:
    """Higher is better (faster). Neutral prior when we lack successful timings."""
    if sample_count <= 0 or avg_success_ms is None or avg_success_ms <= 0:
        return 0.55
    # 1 / (1 + t/half_life): 0ms→1.0, 12s→0.5, 36s→0.25
    return max(0.05, min(1.0, 1.0 / (1.0 + float(avg_success_ms) / _LATENCY_HALF_LIFE_MS)))


def image_model_score_details(
    external_id: str,
    *,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
    feedback_score: float = 0.75,
    feedback_count: int = 0,
    stability_score: float = _STABILITY_PRIOR_MEAN,
    stability_count: int = 0,
    latency_score: float = 0.55,
    latency_count: int = 0,
    avg_success_ms: float | None = None,
) -> dict[str, object]:
    """Measurement-first score for Auto Router image selection.

    Weights: stability 40%, latency 20%, user satisfaction 25%, capabilities 15%.
    Newness is a tiny tie-breaker only (5 points max). Name/marketing strength
    is not used.
    """
    ext = (external_id or "").strip().lower()
    if is_openrouter_auto_model(ext):
        return {"total": -1, "eligible": False, "policy": "measurement-first-v2"}
    capability = _capability_ratio(
        external_id,
        is_image_model=is_image_model,
        pricing_raw=pricing_raw,
    )
    if capability <= 0:
        return {"total": 0, "eligible": False, "policy": "measurement-first-v2"}

    stable = max(0.0, min(1.0, float(stability_score)))
    is_preview = any(x in ext for x in ("preview", "experimental"))
    # Preview builds are frequently text-only flakes on OpenRouter image routes.
    if is_preview:
        stable *= 0.55
    elif "beta" in ext:
        stable *= 0.85
    satisfaction = max(0.0, min(1.0, float(feedback_score)))
    speed = max(0.0, min(1.0, float(latency_score)))
    if avg_success_ms is not None and latency_count > 0:
        speed = _latency_ratio(avg_success_ms, sample_count=latency_count)
    newness = _newness_ratio(external_id, pricing_raw)

    components = {
        "stability": round(stable * 400),
        "latency": round(speed * 200),
        "user_satisfaction": round(satisfaction * 250),
        "capabilities": round(capability * 150),
        "newness": round(newness * 50),
    }
    total = int(sum(components.values()))
    below_floor = (
        int(stability_count) >= _MIN_SAMPLES_FOR_HARD_THRESHOLD
        and float(stability_score) < _HARD_SUCCESS_FLOOR
    )
    if below_floor:
        # Keep eligible for failover chains, but demote hard as a primary pick.
        total = max(1, int(total * 0.35))
    if is_preview:
        # Keep in the failover chain, but almost never pick as Auto Router primary.
        total = max(1, int(total * 0.25))

    return {
        "total": total,
        "eligible": True,
        "components": components,
        "feedback_count": int(feedback_count),
        "feedback_score": round(satisfaction, 4),
        "stability_count": int(stability_count),
        "stability_score": round(stable, 4),
        "latency_count": int(latency_count),
        "latency_score": round(speed, 4),
        "avg_success_ms": round(float(avg_success_ms), 1) if avg_success_ms else None,
        "below_success_floor": below_floor,
        "is_preview": is_preview,
        "policy": "measurement-first-v2",
        "cost_considered": False,
        "name_strength_considered": False,
    }


def score_image_model_candidate(
    external_id: str,
    *,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
    feedback_score: float = 0.75,
    feedback_count: int = 0,
    stability_score: float = _STABILITY_PRIOR_MEAN,
    stability_count: int = 0,
    latency_score: float = 0.55,
    latency_count: int = 0,
    avg_success_ms: float | None = None,
) -> int:
    """Higher score = better Auto Router candidate."""
    return int(
        image_model_score_details(
            external_id,
            is_image_model=is_image_model,
            pricing_raw=pricing_raw,
            feedback_score=feedback_score,
            feedback_count=feedback_count,
            stability_score=stability_score,
            stability_count=stability_count,
            latency_score=latency_score,
            latency_count=latency_count,
            avg_success_ms=avg_success_ms,
        )["total"]
    )


async def _model_runtime_signals(
    db: AsyncSession,
    model_ids: list[str],
) -> dict[str, dict[str, float | int | None]]:
    """Recent per-attempt image reliability, with image request logs as bootstrap."""
    if not model_ids:
        return {}
    cutoff = datetime.utcnow() - _STABILITY_WINDOW

    attempt_rows = (
        await db.execute(
            select(
                ImageGenerationAttempt.model_id,
                func.count(ImageGenerationAttempt.id),
                func.sum(case((ImageGenerationAttempt.success == True, 1), else_=0)),  # noqa: E712
                func.avg(
                    case(
                        (
                            ImageGenerationAttempt.success == True,  # noqa: E712
                            ImageGenerationAttempt.response_time_ms,
                        ),
                        else_=None,
                    )
                ),
                func.sum(
                    case(
                        (
                            (ImageGenerationAttempt.success == True)  # noqa: E712
                            & (ImageGenerationAttempt.response_time_ms.is_not(None))
                            & (ImageGenerationAttempt.response_time_ms > 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .where(
                ImageGenerationAttempt.model_id.in_(model_ids),
                ImageGenerationAttempt.started_at >= cutoff,
            )
            .group_by(ImageGenerationAttempt.model_id)
        )
    ).all()

    out: dict[str, dict[str, float | int | None]] = {}

    def add_rows(rows) -> None:
        for model_id, total, successes, avg_ms, latency_n in rows:
            count = int(total or 0)
            success_count = int(successes or 0)
            bayes = (
                success_count + _STABILITY_PRIOR_MEAN * _STABILITY_PRIOR_WEIGHT
            ) / (count + _STABILITY_PRIOR_WEIGHT)
            out[str(model_id)] = {
                "count": count,
                "score": bayes,
                "avg_success_ms": float(avg_ms) if avg_ms is not None else None,
                "latency_count": int(latency_n or 0),
            }

    add_rows(attempt_rows)

    # Existing installs initially have no attempt table history. Bootstrap only
    # missing models from actual image operations, never normal text chat.
    missing = [model_id for model_id in model_ids if model_id not in out]
    if missing:
        request_rows = (
            await db.execute(
                select(
                    RequestLog.model_id,
                    func.count(RequestLog.id),
                    func.sum(case((RequestLog.success == True, 1), else_=0)),  # noqa: E712
                    func.avg(
                        case(
                            (
                                RequestLog.success == True,  # noqa: E712
                                RequestLog.response_time_ms,
                            ),
                            else_=None,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                (RequestLog.success == True)  # noqa: E712
                                & (RequestLog.response_time_ms.is_not(None))
                                & (RequestLog.response_time_ms > 0),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                )
                .where(
                    RequestLog.model_id.in_(missing),
                    RequestLog.request_time >= cutoff,
                    RequestLog.client_app.like("Alpha Router Chat (image:%"),
                )
                .group_by(RequestLog.model_id)
            )
        ).all()
        add_rows(request_rows)

    return out


def _image_model_rank(external_id: str, score: int, *, below_floor: bool = False) -> tuple:
    """Lower tuple wins: above-floor, stable, lite fast-path, then measured score."""
    ext = (external_id or "").lower()
    floor_penalty = 1 if below_floor else 0
    preview_penalty = 2 if "preview" in ext else (1 if "experimental" in ext else 0)
    # Prefer flash-lite over heavier variants when scores are close — lite has been
    # the most reliable OpenRouter image path in production.
    non_lite_penalty = 0 if "lite" in ext else 1
    return (floor_penalty, preview_penalty, non_lite_penalty, -score, ext)


async def list_auto_router_image_candidates(
    db: AsyncSession,
    *,
    connection_id: int | None = None,
    limit: int = _AUTO_ROUTER_FAILOVER_LIMIT,
    access_user_id: int | None = None,
) -> list[ImageModelResolution]:
    """Ranked image models for Auto Router (primary + failover targets)."""
    from app.services.model_access_service import filter_models_for_subject, resolve_access_subject

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
    if access_user_id is not None:
        subject = await resolve_access_subject(db, user_id=access_user_id)
        allowed = {
            m.id
            for m in await filter_models_for_subject(
                db, [model for model, _ in rows], subject
            )
        }
        rows = [(model, conn) for model, conn in rows if model.id in allowed]
    feedback = await feedback_quality_signals(
        db,
        model_ids=[str(model.external_id) for model, _ in rows],
        output_kind="image",
    )
    runtime = await _model_runtime_signals(
        db,
        [str(model.external_id) for model, _ in rows],
    )
    ranked: list[tuple[tuple, ImageModelResolution]] = []
    for model, conn in rows:
        external_id = str(model.external_id or "")
        external_low = external_id.lower()
        # Auto Router is a fast image path, not a quality/slow-model selector.
        # Slow GPT image models remain available when users choose them directly.
        if "gemini" not in external_low:
            continue
        if "preview" in external_low or "experimental" in external_low:
            continue
        signal = feedback.get(str(model.external_id), {})
        runtime_signal = runtime.get(str(model.external_id), {})
        avg_ms = runtime_signal.get("avg_success_ms")
        latency_count = int(runtime_signal.get("latency_count", 0) or 0)
        if (
            latency_count > 0
            and avg_ms is not None
            and float(avg_ms) > _AUTO_ROUTER_MAX_AVG_SUCCESS_MS
        ):
            continue
        details = image_model_score_details(
            model.external_id or "",
            is_image_model=bool(model.is_image_model),
            pricing_raw=model.pricing_raw,
            feedback_score=float(signal.get("score", 0.75)),
            feedback_count=int(signal.get("count", 0)),
            stability_score=float(runtime_signal.get("score", _STABILITY_PRIOR_MEAN)),
            stability_count=int(runtime_signal.get("count", 0)),
            latency_score=_latency_ratio(
                float(avg_ms) if avg_ms is not None else None,
                sample_count=latency_count,
            ),
            latency_count=latency_count,
            avg_success_ms=float(avg_ms) if avg_ms is not None else None,
        )
        score = int(details["total"])
        if score <= 0 or not details.get("eligible"):
            continue
        resolution = ImageModelResolution(
            external_id=model.external_id,
            model=model,
            connection=conn,
            score=score,
            reason=details,
        )
        rank = _image_model_rank(
            model.external_id or "",
            score,
            below_floor=bool(details.get("below_success_floor")),
        )
        ranked.append((rank, resolution))
    ranked.sort(key=lambda item: item[0])
    return [item[1] for item in ranked[: max(1, int(limit))]]


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
    resolution = await resolve_auto_router_image_model_with_details(
        db,
        connection_id=connection_id,
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
    del statement  # kept for call-site compatibility; listing builds its own query
    candidates = await list_auto_router_image_candidates(
        db,
        connection_id=connection_id,
        limit=1,
    )
    return candidates[0] if candidates else None


async def resolve_openrouter_auto_image_model(
    db: AsyncSession,
    *,
    connection_id: int | None = None,
) -> tuple[str, AIModel, Connection] | None:
    """Backward-compatible alias for OpenRouter auto-router image resolution."""
    return await resolve_auto_router_image_model(db, connection_id=connection_id)


def is_image_model_failover_error(exc: BaseException) -> bool:
    """Errors that justify trying the next Auto Router candidate."""
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        low = detail.lower()
        if exc.status_code in {408, 429, 500, 502, 503, 504, 422}:
            return True
        if exc.status_code == 400:
            return any(
                token in low
                for token in ("invalid model", "no image data", "model not found")
            )
        return False
    # Transport failures before HTTPException wrapping
    from app.services.openrouter_image_service import is_retryable_openrouter_transport_error

    return is_retryable_openrouter_transport_error(exc)
