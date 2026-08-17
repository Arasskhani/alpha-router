"""Redis Streams transport for durable PostgreSQL-backed Knowledge jobs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.config import effective_redis_url, get_settings


@dataclass(frozen=True)
class QueueMessage:
    stream_id: str
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]


def create_knowledge_redis() -> Redis:
    return Redis.from_url(
        effective_redis_url(),
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
        socket_connect_timeout=5,
        socket_timeout=10,
        retry_on_timeout=True,
    )


async def ensure_consumer_group(redis: Redis) -> None:
    settings = get_settings()
    try:
        await redis.xgroup_create(
            settings.knowledge_stream_name,
            settings.knowledge_consumer_group,
            id="0-0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def publish_outbox_message(
    redis: Redis,
    *,
    event_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> str:
    settings = get_settings()
    return str(
        await redis.xadd(
            settings.knowledge_stream_name,
            {
                "event_id": event_id,
                "event_type": event_type,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "payload_json": json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
            maxlen=100_000,
            approximate=True,
        )
    )


def _decode_message(stream_id: str, fields: dict[str, str]) -> QueueMessage:
    raw_payload = fields.get("payload_json") or "{}"
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        payload = {"_invalid_payload": raw_payload}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return QueueMessage(
        stream_id=str(stream_id),
        event_id=str(fields.get("event_id") or ""),
        event_type=str(fields.get("event_type") or ""),
        aggregate_type=str(fields.get("aggregate_type") or ""),
        aggregate_id=str(fields.get("aggregate_id") or ""),
        payload=payload,
    )


async def read_new_messages(
    redis: Redis,
    *,
    consumer_name: str,
) -> list[QueueMessage]:
    settings = get_settings()
    rows = await redis.xreadgroup(
        settings.knowledge_consumer_group,
        consumer_name,
        streams={settings.knowledge_stream_name: ">"},
        count=settings.knowledge_worker_batch_size,
        block=settings.knowledge_worker_block_ms,
    )
    messages: list[QueueMessage] = []
    for _stream_name, entries in rows or []:
        for stream_id, fields in entries:
            messages.append(_decode_message(str(stream_id), fields))
    return messages


async def reclaim_stale_messages(
    redis: Redis,
    *,
    consumer_name: str,
    start_id: str = "0-0",
) -> tuple[str, list[QueueMessage]]:
    settings = get_settings()
    response = await redis.xautoclaim(
        settings.knowledge_stream_name,
        settings.knowledge_consumer_group,
        consumer_name,
        min_idle_time=settings.knowledge_job_lease_seconds * 1000,
        start_id=start_id,
        count=settings.knowledge_worker_batch_size,
    )
    next_id = str(response[0]) if response else "0-0"
    entries = response[1] if len(response) > 1 else []
    return next_id, [
        _decode_message(str(stream_id), fields)
        for stream_id, fields in entries
    ]


async def acknowledge_message(redis: Redis, stream_id: str) -> None:
    settings = get_settings()
    await redis.xack(
        settings.knowledge_stream_name,
        settings.knowledge_consumer_group,
        stream_id,
    )


async def publish_dead_letter(
    redis: Redis,
    message: QueueMessage,
    *,
    error: str,
) -> str:
    settings = get_settings()
    return str(
        await redis.xadd(
            settings.knowledge_dead_letter_stream_name,
            {
                "source_stream_id": message.stream_id,
                "event_id": message.event_id,
                "event_type": message.event_type,
                "aggregate_type": message.aggregate_type,
                "aggregate_id": message.aggregate_id,
                "payload_json": json.dumps(message.payload, ensure_ascii=False),
                "error": error[:4000],
            },
            maxlen=50_000,
            approximate=True,
        )
    )
