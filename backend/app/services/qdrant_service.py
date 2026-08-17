"""Qdrant collection lifecycle and ACL-safe point writes."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.config import get_settings

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"
_COLLECTION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,254}$")

_KEYWORD_PAYLOAD_FIELDS = (
    "knowledge_base_id",
    "release_id",
    "document_id",
    "document_version_id",
    "chunk_id",
    "status",
    "classification",
    "language",
    "authority",
    "access_scope",
    "kb_access_scope",
    "document_access_scope",
    "content_hash",
    "index_version_id",
    "allow_principal_tokens",
    "kb_allow_principal_tokens",
    "document_allow_principal_tokens",
    "deny_principal_tokens",
)
_INTEGER_PAYLOAD_FIELDS = ("acl_version", "chunk_index", "page_number")
_DATETIME_PAYLOAD_FIELDS = ("effective_from", "effective_to", "revoked_at")


@dataclass(frozen=True)
class SparseValues:
    indices: Sequence[int]
    values: Sequence[float]


@dataclass(frozen=True)
class KnowledgeVectorPoint:
    point_id: str
    dense: Sequence[float]
    sparse: SparseValues
    payload: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeSearchHit:
    point_id: str
    score: float
    payload: dict[str, Any]
    channel: str


def create_qdrant_client() -> AsyncQdrantClient:
    settings = get_settings()
    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=max(1, int(settings.qdrant_timeout_seconds)),
        prefer_grpc=False,
        check_compatibility=True,
    )


def validate_collection_name(name: str) -> str:
    normalized = (name or "").strip()
    if not _COLLECTION_RE.fullmatch(normalized):
        raise ValueError("Invalid Qdrant collection or alias name")
    return normalized


def versioned_collection_name(
    *,
    knowledge_base_id: str,
    index_version: int,
) -> str:
    settings = get_settings()
    safe_kb = re.sub(r"[^a-zA-Z0-9_-]+", "-", knowledge_base_id).strip("-")
    return validate_collection_name(
        f"{settings.qdrant_collection_prefix}-{safe_kb}-v{int(index_version)}"
    )


def collection_alias(*, knowledge_base_id: str) -> str:
    settings = get_settings()
    safe_kb = re.sub(r"[^a-zA-Z0-9_-]+", "-", knowledge_base_id).strip("-")
    return validate_collection_name(
        f"{settings.qdrant_collection_prefix}-{safe_kb}-active"
    )


class QdrantVectorService:
    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        self.client = client or create_qdrant_client()

    async def close(self) -> None:
        await self.client.close()

    async def healthcheck(self) -> bool:
        await self.client.get_collections()
        return True

    async def ensure_collection(
        self,
        *,
        collection_name: str,
        dense_dimensions: int,
        replication_factor: int | None = None,
    ) -> bool:
        """Create one immutable hybrid collection and required payload indexes."""

        name = validate_collection_name(collection_name)
        dimensions = int(dense_dimensions)
        if dimensions < 1 or dimensions > 65_536:
            raise ValueError("dense_dimensions must be between 1 and 65536")

        created = False
        if not await self.client.collection_exists(name):
            settings = get_settings()
            await self.client.create_collection(
                collection_name=name,
                vectors_config={
                    DENSE_VECTOR_NAME: models.VectorParams(
                        size=dimensions,
                        distance=models.Distance.COSINE,
                        on_disk=True,
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        index=models.SparseIndexParams(on_disk=True),
                        modifier=models.Modifier.IDF,
                    )
                },
                replication_factor=(
                    replication_factor
                    if replication_factor is not None
                    else settings.qdrant_replication_factor
                ),
                write_consistency_factor=1,
                on_disk_payload=True,
            )
            created = True
        else:
            info = await self.client.get_collection(name)
            vectors = info.config.params.vectors
            dense_config = (
                vectors.get(DENSE_VECTOR_NAME) if isinstance(vectors, dict) else None
            )
            if dense_config is None or int(dense_config.size) != dimensions:
                raise ValueError(
                    f"Qdrant collection {name} has an incompatible dense vector schema"
                )
            sparse = info.config.params.sparse_vectors or {}
            if SPARSE_VECTOR_NAME not in sparse:
                raise ValueError(
                    f"Qdrant collection {name} is missing sparse vector configuration"
                )

        for field in _KEYWORD_PAYLOAD_FIELDS:
            await self.client.create_payload_index(
                name,
                field,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )
        for field in _INTEGER_PAYLOAD_FIELDS:
            await self.client.create_payload_index(
                name,
                field,
                field_schema=models.PayloadSchemaType.INTEGER,
                wait=True,
            )
        for field in _DATETIME_PAYLOAD_FIELDS:
            await self.client.create_payload_index(
                name,
                field,
                field_schema=models.PayloadSchemaType.DATETIME,
                wait=True,
            )
        return created

    async def activate_alias(
        self,
        *,
        alias_name: str,
        collection_name: str,
    ) -> None:
        alias = validate_collection_name(alias_name)
        collection = validate_collection_name(collection_name)
        if not await self.client.collection_exists(collection):
            raise ValueError(f"Qdrant collection does not exist: {collection}")
        aliases = await self.client.get_aliases()
        exists = any(item.alias_name == alias for item in aliases.aliases)
        actions: list[models.CreateAliasOperation | models.DeleteAliasOperation] = []
        if exists:
            actions.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=alias)
                )
            )
        actions.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=collection,
                    alias_name=alias,
                )
            )
        )
        await self.client.update_collection_aliases(actions)

    async def upsert_points(
        self,
        *,
        collection_name: str,
        points: Sequence[KnowledgeVectorPoint],
    ) -> int:
        name = validate_collection_name(collection_name)
        if not points:
            return 0
        structs: list[models.PointStruct] = []
        for point in points:
            payload = dict(point.payload)
            required = {
                "knowledge_base_id",
                "release_id",
                "document_id",
                "document_version_id",
                "chunk_id",
                "acl_version",
                "status",
                "allow_principal_tokens",
                "deny_principal_tokens",
            }
            missing = sorted(required - payload.keys())
            if missing:
                raise ValueError(
                    "Qdrant point payload is missing required fields: "
                    + ", ".join(missing)
                )
            if len(point.sparse.indices) != len(point.sparse.values):
                raise ValueError(
                    "Sparse vector indices and values must have equal length"
                )
            structs.append(
                models.PointStruct(
                    id=point.point_id,
                    vector={
                        DENSE_VECTOR_NAME: list(point.dense),
                        SPARSE_VECTOR_NAME: models.SparseVector(
                            indices=[int(value) for value in point.sparse.indices],
                            values=[float(value) for value in point.sparse.values],
                        ),
                    },
                    payload=payload,
                )
            )
        await self.client.upsert(name, structs, wait=True)
        return len(structs)

    async def delete_by_filter(
        self,
        *,
        collection_name: str,
        query_filter: models.Filter,
    ) -> None:
        await self.client.delete(
            validate_collection_name(collection_name),
            models.FilterSelector(filter=query_filter),
            wait=True,
        )

    async def delete_collection(self, *, collection_name: str) -> None:
        name = validate_collection_name(collection_name)
        try:
            await self.client.delete_collection(name)
        except Exception as exc:  # noqa: BLE001 - Qdrant client raises varied errors
            message = str(exc).casefold()
            if "not found" in message or "doesn't exist" in message:
                return
            raise

    async def count_points(
        self,
        *,
        collection_name: str,
        query_filter: models.Filter | None = None,
    ) -> int:
        result = await self.client.count(
            validate_collection_name(collection_name),
            count_filter=query_filter,
            exact=True,
        )
        return int(result.count)

    async def _query_channel(
        self,
        *,
        collection_name: str,
        query: Sequence[float] | SparseValues,
        channel: str,
        query_filter: models.Filter,
        limit: int,
        score_threshold: float | None,
    ) -> list[KnowledgeSearchHit]:
        if limit < 1 or limit > 1_000:
            raise ValueError("Qdrant Knowledge query limit must be between 1 and 1000")
        if channel == DENSE_VECTOR_NAME:
            vector: list[float] | models.SparseVector = [
                float(value) for value in query
            ]
        elif channel == SPARSE_VECTOR_NAME and isinstance(query, SparseValues):
            if not query.indices:
                return []
            if len(query.indices) != len(query.values):
                raise ValueError(
                    "Sparse query indices and values must have equal length"
                )
            vector = models.SparseVector(
                indices=[int(value) for value in query.indices],
                values=[float(value) for value in query.values],
            )
        else:
            raise ValueError("Unsupported Qdrant Knowledge query channel")
        response = await self.client.query_points(
            validate_collection_name(collection_name),
            query=vector,
            using=channel,
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        return [
            KnowledgeSearchHit(
                point_id=str(point.id),
                score=float(point.score),
                payload=dict(point.payload or {}),
                channel=channel,
            )
            for point in response.points
        ]

    async def hybrid_candidates(
        self,
        *,
        collection_name: str,
        dense: Sequence[float],
        sparse: SparseValues,
        query_filter: models.Filter,
        limit: int,
        dense_score_threshold: float | None = None,
        sparse_score_threshold: float | None = None,
    ) -> tuple[list[KnowledgeSearchHit], list[KnowledgeSearchHit]]:
        """Run independent dense and sparse searches for explicit RRF fusion."""

        dense_hits, sparse_hits = await asyncio.gather(
            self._query_channel(
                collection_name=collection_name,
                query=dense,
                channel=DENSE_VECTOR_NAME,
                query_filter=query_filter,
                limit=limit,
                score_threshold=dense_score_threshold,
            ),
            self._query_channel(
                collection_name=collection_name,
                query=sparse,
                channel=SPARSE_VECTOR_NAME,
                query_filter=query_filter,
                limit=limit,
                score_threshold=sparse_score_threshold,
            ),
        )
        return dense_hits, sparse_hits
