"""Bounded asynchronous object-store adapter for Knowledge documents."""

from __future__ import annotations

import asyncio
from typing import Protocol

from app.services import object_storage_service


class KnowledgeObjectStoreProtocol(Protocol):
    async def put(self, key: str, body: bytes) -> None: ...

    async def get(self, key: str, *, max_bytes: int) -> bytes: ...

    async def delete(self, key: str) -> None: ...


class S3KnowledgeObjectStore:
    async def put(self, key: str, body: bytes) -> None:
        await asyncio.to_thread(
            object_storage_service.put_object,
            key,
            body,
            "application/octet-stream",
        )

    async def get(self, key: str, *, max_bytes: int) -> bytes:
        return await asyncio.to_thread(
            object_storage_service.get_object_bytes_bounded,
            key,
            max_bytes=max_bytes,
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(object_storage_service.delete_object, key)


def default_knowledge_object_store() -> KnowledgeObjectStoreProtocol:
    return S3KnowledgeObjectStore()
