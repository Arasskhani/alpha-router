"""Resolve auto-router catalog entries to a concrete image-capable model."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.model_capabilities import image_generation_capabilities
from app.services.openrouter_image_service import is_openrouter_auto_model


def score_image_model_candidate(
    external_id: str,
    *,
    is_image_model: bool = False,
    pricing_raw: str | None = None,
) -> int:
    """Higher score = better default for Auto Router image generation."""
    ext = (external_id or "").strip().lower()
    if is_openrouter_auto_model(ext):
        return -1

    caps = image_generation_capabilities(
        external_id=external_id,
        is_image_model=is_image_model,
        pricing_raw=pricing_raw,
    )
    if not caps.get("supports_text_to_image"):
        return 0

    if "gemini" in ext and "image" in ext and "flash" in ext:
        return 100
    if "gemini" in ext and "image" in ext:
        return 90
    if "flux" in ext:
        return 80
    if "dall-e" in ext or "dalle" in ext:
        return 70
    if "stable-diffusion" in ext or "sdxl" in ext:
        return 65
    if is_image_model:
        return 60
    if "image" in ext:
        return 50
    return 10


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

    rows = (await db.execute(stmt)).all()
    best: tuple[str, AIModel, Connection] | None = None
    best_rank: tuple[int, int, int, str] | None = None
    for model, conn in rows:
        score = score_image_model_candidate(
            model.external_id or "",
            is_image_model=bool(model.is_image_model),
            pricing_raw=model.pricing_raw,
        )
        if score <= 0:
            continue
        rank = _image_model_rank(model.external_id or "", score)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = (model.external_id, model, conn)
    return best


async def resolve_openrouter_auto_image_model(
    db: AsyncSession,
    *,
    connection_id: int | None = None,
) -> tuple[str, AIModel, Connection] | None:
    """Backward-compatible alias for OpenRouter auto-router image resolution."""
    return await resolve_auto_router_image_model(db, connection_id=connection_id)
