"""Embedding wrapper for automatic user memory (normalized text)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge_embedding_service import (
    CatalogKnowledgeEmbeddingBackend,
    suggested_embedding_dimensions,
)
from app.services.memory_settings_service import get_memory_settings, parse_embedding_spec
from app.utils.text_normalize import normalize_memory_text

_backend = CatalogKnowledgeEmbeddingBackend()


class MemoryEmbeddingUnavailable(RuntimeError):
    """Embedding model is not configured or failed."""


def resolved_memory_embedding_dimensions(settings: dict, model: str) -> int:
    dims = int(settings.get("embedding_dimensions") or 0)
    if dims >= 1:
        return dims
    return suggested_embedding_dimensions(model)


async def memory_embedding_config(
    db: AsyncSession,
    *,
    settings: dict | None = None,
) -> tuple[str, str, int] | None:
    """``settings`` lets a caller that already holds them skip the re-read."""

    settings = settings if settings is not None else await get_memory_settings(db)
    spec = parse_embedding_spec(str(settings.get("embedding_model") or ""))
    if spec is None:
        return None
    provider, model = spec
    return provider, model, resolved_memory_embedding_dimensions(settings, model)


async def embed_memory_texts(
    db: AsyncSession,
    texts: Sequence[str],
    *,
    backend: CatalogKnowledgeEmbeddingBackend | None = None,
    settings: dict | None = None,
) -> list[list[float]]:
    cfg = await memory_embedding_config(db, settings=settings)
    if cfg is None:
        raise MemoryEmbeddingUnavailable("Memory embedding model is not configured")
    provider, model, dims = cfg
    cleaned = [normalize_memory_text(text) or " " for text in texts]
    impl = backend or _backend
    return await impl.embed(
        db,
        provider=provider,
        model=model,
        dimensions=dims,
        texts=cleaned,
    )
