"""Bounded embedding backend used by Knowledge indexing and retrieval."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from litellm import aembedding
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.connection import Connection
from app.models.model_catalog import AIModel
from app.services.llm_providers import (
    external_id_lookup_candidates,
    litellm_model_for_provider,
    resolve_litellm_provider,
)
from app.services.model_capabilities import model_kinds
from app.services.secret_crypto import decrypt_secret


def suggested_embedding_dimensions(external_id: str) -> int:
    """Best-known dense size for a catalog embedding model id.

    Keep in sync with frontend/src/lib/embeddingDimensions.ts.
    """
    lowered = (external_id or "").casefold()
    if "text-embedding-3-large" in lowered:
        return 3072
    if "text-embedding-3-small" in lowered or "ada-002" in lowered:
        return 1536
    if "gemini-embedding" in lowered:
        return 3072
    if "qwen3-embedding-8b" in lowered:
        return 4096
    if "qwen3-embedding" in lowered:
        return 2560
    if "mistral-embed" in lowered or "codestral-embed" in lowered:
        return 1024
    return 1536


class KnowledgeEmbeddingBackend(Protocol):
    async def embed(
        self,
        db: AsyncSession,
        *,
        provider: str,
        model: str,
        dimensions: int,
        texts: Sequence[str],
    ) -> list[list[float]]: ...


@dataclass(frozen=True)
class ResolvedEmbeddingModel:
    catalog_model: AIModel
    provider_type: str
    api_key: str
    base_url: str | None


async def resolve_embedding_model(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
) -> ResolvedEmbeddingModel:
    requested_model = (model or "").strip()
    requested_provider = (provider or "").strip().lower()
    if not requested_model or not requested_provider:
        raise ValueError("A provider and model are required for Knowledge embeddings")

    candidates = external_id_lookup_candidates(requested_model)
    row = (
        (
            await db.execute(
                select(AIModel).where(
                    AIModel.external_id.in_(candidates),
                    AIModel.is_enabled.is_(True),
                    AIModel.admin_disabled.is_(False),
                )
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise ValueError(f"Embedding model is not enabled in the catalog: {requested_model}")
    connection = await db.get(Connection, row.connection_id)
    if connection is None or not bool(connection.is_active):
        raise ValueError("Embedding model connection is unavailable")
    actual_provider = (connection.provider_type or row.provider_type or "").strip().lower()
    if requested_provider != actual_provider:
        raise ValueError("Knowledge index embedding provider does not match the model connection")
    kinds = model_kinds(
        external_id=row.external_id or "",
        is_image_model=bool(row.is_image_model),
        is_video_model=bool(getattr(row, "is_video_model", False)),
        pricing_raw=row.pricing_raw,
        provider_type=actual_provider,
    )
    if "embeddings" not in kinds:
        raise ValueError("Configured Knowledge model is not an embedding model")
    return ResolvedEmbeddingModel(
        catalog_model=row,
        provider_type=actual_provider,
        api_key=decrypt_secret(connection.api_key_encrypted),
        base_url=connection.base_url,
    )


def _response_vectors(response: object, *, expected: int, dimensions: int) -> list[list[float]]:
    if hasattr(response, "model_dump"):
        payload = response.model_dump()
    elif isinstance(response, dict):
        payload = response
    else:
        raise ValueError("Embedding provider returned an unsupported response")
    raw_data = payload.get("data")
    if not isinstance(raw_data, list) or len(raw_data) != expected:
        raise ValueError("Embedding provider returned an unexpected vector count")

    ordered: list[tuple[int, list[float]]] = []
    for fallback_index, item in enumerate(raw_data):
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
            raise TypeError("Embedding provider returned a malformed vector")
        index = int(item.get("index", fallback_index))
        vector = [float(value) for value in item["embedding"]]
        if len(vector) != dimensions:
            raise ValueError(f"Embedding dimension mismatch: expected {dimensions}, received {len(vector)}")
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("Embedding provider returned a non-finite vector")
        ordered.append((index, vector))
    ordered.sort(key=lambda item: item[0])
    if [index for index, _ in ordered] != list(range(expected)):
        raise ValueError("Embedding provider returned invalid vector indices")
    return [vector for _, vector in ordered]


class CatalogKnowledgeEmbeddingBackend:
    """Resolve an enabled catalog model and call it through LiteLLM."""

    async def embed(
        self,
        db: AsyncSession,
        *,
        provider: str,
        model: str,
        dimensions: int,
        texts: Sequence[str],
    ) -> list[list[float]]:
        settings = get_settings()
        bounded = [str(text or "") for text in texts]
        if not bounded:
            return []
        if len(bounded) > settings.knowledge_embedding_batch_size:
            raise ValueError("Knowledge embedding batch exceeds the configured limit")
        if any(not text.strip() or len(text) > settings.knowledge_embedding_max_input_characters for text in bounded):
            raise ValueError("Knowledge embedding input is empty or too large")
        if dimensions < 1 or dimensions > 65_536:
            raise ValueError("Knowledge embedding dimensions are outside the safe range")

        resolved = await resolve_embedding_model(db, provider=provider, model=model)
        kwargs: dict = {
            "model": litellm_model_for_provider(
                resolved.catalog_model.external_id,
                resolved.provider_type,
            ),
            "input": bounded,
            "api_key": resolved.api_key,
            "base_url": resolved.base_url,
            "dimensions": dimensions,
            "timeout": settings.knowledge_embedding_timeout_seconds,
            "caching": True,
        }
        litellm_provider = resolve_litellm_provider(resolved.provider_type)
        if litellm_provider:
            kwargs["custom_llm_provider"] = litellm_provider
        response = await aembedding(**kwargs)
        return _response_vectors(
            response,
            expected=len(bounded),
            dimensions=dimensions,
        )
