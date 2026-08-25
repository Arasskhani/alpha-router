"""Dedicated Qdrant collection for user-memory vectors (IDs only in payload)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.config import get_settings
from app.services.qdrant_service import (
    DENSE_VECTOR_NAME,
    create_qdrant_client,
    validate_collection_name,
)

KIND_MEMORY = "memory"
KIND_SUPPRESSION = "suppression"

SCOPE_USER = "user"
SCOPE_PROJECT = "project"
# Owner payload key per scope. It doubles as the tenant filter, so a project
# point never carries user_id and a personal point never carries project_id.
_OWNER_KEY = {SCOPE_USER: "user_id", SCOPE_PROJECT: "project_id"}


@dataclass(frozen=True)
class MemoryVectorPoint:
    point_id: str
    dense: Sequence[float]
    payload: dict[str, Any]


@dataclass(frozen=True)
class MemoryHit:
    point_id: str
    score: float
    payload: dict[str, Any]


def memory_collection_name(*, version: int) -> str:
    settings = get_settings()
    prefix = (settings.qdrant_memory_collection_prefix or "alpharouter-memory").strip()
    return validate_collection_name(f"{prefix}-v{int(version)}")


def memory_collection_alias() -> str:
    settings = get_settings()
    prefix = (settings.qdrant_memory_collection_prefix or "alpharouter-memory").strip()
    return validate_collection_name(f"{prefix}-active")


class MemoryVectorService:
    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        self.client = client or create_qdrant_client()

    async def close(self) -> None:
        await self.client.close()

    async def ensure_collection(self, *, collection_name: str, dims: int) -> bool:
        name = validate_collection_name(collection_name)
        dimensions = int(dims)
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
                quantization_config=models.ScalarQuantization(
                    scalar=models.ScalarQuantizationConfig(
                        type=models.ScalarType.INT8,
                        quantile=0.99,
                        always_ram=True,
                    )
                ),
                replication_factor=settings.qdrant_replication_factor,
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
                    f"Qdrant memory collection {name} has an incompatible dense vector schema"
                )

        await self._ensure_payload_indexes(name)
        return created

    async def _ensure_payload_indexes(self, name: str) -> None:
        tenant_schema: Any
        try:
            tenant_schema = models.KeywordIndexParams(
                type=models.KeywordIndexType.KEYWORD,
                is_tenant=True,
            )
        except Exception:
            tenant_schema = models.PayloadSchemaType.KEYWORD
        await self.client.create_payload_index(
            name, "user_id", field_schema=tenant_schema, wait=True
        )
        for field, schema in (
            ("project_id", models.PayloadSchemaType.KEYWORD),
            ("scope", models.PayloadSchemaType.KEYWORD),
            ("kind", models.PayloadSchemaType.KEYWORD),
            ("category", models.PayloadSchemaType.KEYWORD),
            ("sensitivity", models.PayloadSchemaType.KEYWORD),
            ("enabled", models.PayloadSchemaType.BOOL),
        ):
            await self.client.create_payload_index(
                name, field, field_schema=schema, wait=True
            )

    async def upsert(
        self,
        *,
        collection_name: str,
        points: Sequence[MemoryVectorPoint],
    ) -> int:
        name = validate_collection_name(collection_name)
        if not points:
            return 0
        structs: list[models.PointStruct] = []
        for point in points:
            payload = dict(point.payload)
            scope = str(payload.setdefault("scope", SCOPE_USER))
            owner_key = _OWNER_KEY.get(scope)
            if owner_key is None:
                raise ValueError(f"Unknown memory vector scope: {scope}")
            if not payload.get(owner_key):
                raise ValueError(f"Memory vector payload requires {owner_key}")
            structs.append(
                models.PointStruct(
                    id=point.point_id,
                    vector={DENSE_VECTOR_NAME: [float(v) for v in point.dense]},
                    payload=payload,
                )
            )
        await self.client.upsert(name, structs, wait=True)
        return len(structs)

    async def search(
        self,
        *,
        collection_name: str,
        vector: Sequence[float],
        limit: int,
        score_threshold: float,
        user_id: int | None = None,
        project_id: str | None = None,
        scope: str = SCOPE_USER,
        kind: str = KIND_MEMORY,
    ) -> list[MemoryHit]:
        if scope not in _OWNER_KEY:
            raise ValueError(f"Unknown memory vector scope: {scope}")
        if scope == SCOPE_PROJECT:
            owner_key = "project_id"
            owner_value = str(project_id or "")
        else:
            owner_key = "user_id"
            owner_value = "" if user_id is None else str(int(user_id))
        if not owner_value:
            raise ValueError(f"{owner_key} is required for memory vector search")
        bounded = max(1, min(int(limit), 1000))
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key=owner_key,
                    match=models.MatchValue(value=owner_value),
                ),
                models.FieldCondition(
                    key="kind",
                    match=models.MatchValue(value=kind),
                ),
            ]
        )
        if kind == KIND_MEMORY:
            query_filter.must.append(
                models.FieldCondition(
                    key="enabled",
                    match=models.MatchValue(value=True),
                )
            )
        response = await self.client.query_points(
            validate_collection_name(collection_name),
            query=[float(v) for v in vector],
            using=DENSE_VECTOR_NAME,
            query_filter=query_filter,
            limit=bounded,
            score_threshold=float(score_threshold),
            with_payload=True,
            with_vectors=False,
        )
        hits: list[MemoryHit] = []
        for point in response.points:
            payload = dict(point.payload or {})
            # Defence in depth: never leak across tenants if the filter is
            # bypassed by a missing payload index.
            if str(payload.get(owner_key) or "") != owner_value:
                continue
            hits.append(
                MemoryHit(
                    point_id=str(point.id),
                    score=float(point.score),
                    payload=payload,
                )
            )
        return hits

    async def delete_ids(self, *, collection_name: str, point_ids: Sequence[str]) -> None:
        ids = [pid for pid in point_ids if pid]
        if not ids:
            return
        await self.client.delete(
            validate_collection_name(collection_name),
            models.PointIdsList(points=list(ids)),
            wait=True,
        )

    async def delete_user(self, *, collection_name: str, user_id: int) -> None:
        await self._delete_by_owner(
            collection_name=collection_name,
            owner_key="user_id",
            owner_value=str(int(user_id)),
        )

    async def delete_project(self, *, collection_name: str, project_id: str) -> None:
        value = str(project_id or "")
        if not value:
            raise ValueError("project_id is required")
        await self._delete_by_owner(
            collection_name=collection_name,
            owner_key="project_id",
            owner_value=value,
        )

    async def _delete_by_owner(
        self, *, collection_name: str, owner_key: str, owner_value: str
    ) -> None:
        await self.client.delete(
            validate_collection_name(collection_name),
            models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key=owner_key,
                            match=models.MatchValue(value=owner_value),
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def activate_alias(self, *, collection_name: str) -> None:
        alias = memory_collection_alias()
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

    async def delete_collection(self, *, collection_name: str) -> None:
        name = validate_collection_name(collection_name)
        try:
            await self.client.delete_collection(name)
        except Exception as exc:  # noqa: BLE001
            message = str(exc).casefold()
            if "not found" in message or "doesn't exist" in message:
                return
            raise

    async def resolve_target_collection(self) -> str:
        alias = memory_collection_alias()
        try:
            aliases = await self.client.get_aliases()
            for item in aliases.aliases:
                if item.alias_name == alias:
                    return item.collection_name
        except Exception:
            pass
        return alias
