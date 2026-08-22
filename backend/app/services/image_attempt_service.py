"""Per-attempt image routing telemetry, separate from billing request logs."""

from __future__ import annotations

import asyncio
import datetime
import logging

from app.database import AsyncSessionLocal
from app.models.logging import ImageGenerationAttempt

logger = logging.getLogger(__name__)


def image_attempt_outcome(exc: BaseException) -> str:
    """Normalize failures into stable routing telemetry categories."""
    detail = str(getattr(exc, "detail", exc) or "").lower()
    if "text instead of an image" in detail:
        return "text_only"
    if "empty response" in detail:
        return "empty"
    if "timed out" in detail or "timeout" in detail:
        return "timeout"
    if "disconnect" in detail or "closed the connection" in detail:
        return "disconnect"
    status = getattr(exc, "status_code", None)
    if status is not None:
        return f"http_{status}"
    return "error"


async def record_image_attempt(
    *,
    request_id: str,
    user_id: int | None,
    requested_model: str,
    model_id: str,
    operation: str,
    attempt_index: int,
    started_at: datetime.datetime,
    response_time_ms: float,
    success: bool,
    outcome: str,
    error_message: str | None = None,
    project_id: str | None = None,
) -> None:
    """Persist telemetry independently; telemetry failure must never fail generation."""
    try:
        async with asyncio.timeout(1.0):
            async with AsyncSessionLocal() as db:
                db.add(
                    ImageGenerationAttempt(
                        request_id=request_id,
                        user_id=user_id,
                        project_id=project_id,
                        requested_model=requested_model,
                        model_id=model_id,
                        operation=operation,
                        attempt_index=attempt_index,
                        started_at=started_at,
                        response_time_ms=max(0.0, float(response_time_ms)),
                        success=bool(success),
                        outcome=outcome,
                        error_message=(error_message or "")[:500] or None,
                    )
                )
                await db.commit()
    except Exception:
        logger.exception("Failed to record image generation attempt telemetry")
