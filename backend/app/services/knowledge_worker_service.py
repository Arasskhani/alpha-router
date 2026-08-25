"""At-least-once Redis consumer backed by idempotent PostgreSQL jobs."""

from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.knowledge import (
    ConnectorSyncRun,
    IngestionJob,
    KnowledgeDocumentVersion,
    KnowledgeIndexVersion,
)
from app.services.knowledge_job_handlers import (
    BUILTIN_KNOWLEDGE_JOB_HANDLERS,
    KnowledgeJobContext,
    KnowledgeJobHandler,
)
from app.services.knowledge_job_service import (
    claim_knowledge_job,
    complete_knowledge_job,
    fail_knowledge_job,
    heartbeat_knowledge_job,
)
from app.services.knowledge_queue import (
    QueueMessage,
    acknowledge_message,
    ensure_consumer_group,
    publish_dead_letter,
    read_new_messages,
    reclaim_stale_messages,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobProcessResult:
    outcome: str
    job_id: str | None = None
    error: str | None = None


class KnowledgeWorker:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        consumer_name: str,
        context: KnowledgeJobContext,
        handlers: dict[str, KnowledgeJobHandler] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.redis = redis
        self.consumer_name = consumer_name
        self.context = context
        self.handlers = dict(BUILTIN_KNOWLEDGE_JOB_HANDLERS)
        if handlers:
            self.handlers.update(handlers)

    async def _heartbeat_loop(self, job_id: str, stop: asyncio.Event) -> None:
        interval = max(1, get_settings().knowledge_job_lease_seconds // 3)
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                break
            except TimeoutError:
                pass
            try:
                async with self.session_factory() as db:
                    job = await db.get(IngestionJob, job_id)
                    if job is None or not await heartbeat_knowledge_job(
                        db,
                        job,
                        worker_id=self.consumer_name,
                    ):
                        await db.rollback()
                        return
                    await db.commit()
            except Exception:
                logger.exception("Knowledge job heartbeat failed for %s", job_id)

    async def process_message(self, message: QueueMessage) -> JobProcessResult:
        if message.event_type == "memory.job.ready":
            return await self._process_memory_job(message, scope="user")
        if message.event_type == "project_memory.job.ready":
            return await self._process_memory_job(message, scope="project")
        if message.event_type != "knowledge.job.ready":
            error = f"Unsupported Knowledge event type: {message.event_type}"
            await publish_dead_letter(self.redis, message, error=error)
            await acknowledge_message(self.redis, message.stream_id)
            return JobProcessResult(outcome="dead", error=error)
        return await self._process_knowledge_job(message)

    async def _process_memory_job(
        self, message: QueueMessage, *, scope: str
    ) -> JobProcessResult:
        from app.services.memory_extraction_service import ExtractionParseError
        from app.services.observability import observe_memory_extract_job

        if scope == "project":
            from app.models.project import ProjectMemoryJob as job_model
            from app.services.project_memory_extraction_service import (
                handle_project_memory_extraction as handle_extraction,
            )
            from app.services.project_memory_job_service import (
                claim_job,
                complete_job,
                fail_job,
                heartbeat_job,
            )
        else:
            from app.models.chat import UserMemoryJob as job_model
            from app.services.memory_extraction_service import (
                handle_memory_extraction as handle_extraction,
            )
            from app.services.memory_job_service import (
                claim_job,
                complete_job,
                fail_job,
                heartbeat_job,
            )

        job_id = str(message.payload.get("job_id") or message.aggregate_id or "")
        if not job_id:
            error = "Memory queue message does not identify a job"
            await publish_dead_letter(self.redis, message, error=error)
            await acknowledge_message(self.redis, message.stream_id)
            return JobProcessResult(outcome="dead", error=error)

        async with self.session_factory() as db:
            job = await claim_job(
                db,
                job_id=job_id,
                worker_id=self.consumer_name,
            )
            existing = job or await db.get(job_model, job_id)
            await db.commit()
        if job is None:
            if existing is None:
                error = f"Memory job not found: {job_id}"
                await publish_dead_letter(self.redis, message, error=error)
                await acknowledge_message(self.redis, message.stream_id)
                return JobProcessResult(outcome="dead", job_id=job_id, error=error)
            await acknowledge_message(self.redis, message.stream_id)
            observe_memory_extract_job(outcome="duplicate", scope=scope)
            return JobProcessResult(outcome="duplicate", job_id=job_id)

        stop_heartbeat = asyncio.Event()

        async def _heartbeat() -> None:
            interval = max(1, get_settings().memory_job_lease_seconds // 3)
            while not stop_heartbeat.is_set():
                try:
                    await asyncio.wait_for(stop_heartbeat.wait(), timeout=interval)
                    break
                except TimeoutError:
                    pass
                try:
                    async with self.session_factory() as db:
                        current = await db.get(job_model, job.id)
                        if current is None or not await heartbeat_job(
                            db, current, worker_id=self.consumer_name
                        ):
                            await db.rollback()
                            return
                        await db.commit()
                except Exception:
                    logger.exception("Memory job heartbeat failed for %s", job.id)

        heartbeat_task = asyncio.create_task(_heartbeat())
        failure: Exception | None = None
        retryable = True
        started = asyncio.get_running_loop().time()
        try:
            async with self.session_factory() as db:
                current = await db.get(job_model, job.id)
                if current is None:
                    raise ValueError("Memory job disappeared during execution")
                await handle_extraction(db, current)
                await db.commit()
        except ExtractionParseError as exc:
            failure = exc
            retryable = False
        except Exception as exc:
            failure = exc
        stop_heartbeat.set()
        await heartbeat_task
        duration = max(0.0, asyncio.get_running_loop().time() - started)

        if failure is None:
            async with self.session_factory() as db:
                current = await db.get(job_model, job.id)
                if current is None or not await complete_job(
                    db,
                    current,
                    worker_id=self.consumer_name,
                    extracted_sequence=int(current.extracted_sequence or 0),
                ):
                    await db.rollback()
                    failure = RuntimeError("Memory job lease was lost before completion")
                else:
                    await db.commit()

        if failure is not None:
            async with self.session_factory() as db:
                current = await db.get(job_model, job.id)
                if current is None:
                    result_status = "dead"
                else:
                    result = await fail_job(
                        db,
                        current,
                        worker_id=self.consumer_name,
                        error=failure,
                        retryable=retryable,
                    )
                    result_status = result.status
                    await db.commit()
            if result_status == "dead":
                await publish_dead_letter(self.redis, message, error=str(failure))
            await acknowledge_message(self.redis, message.stream_id)
            observe_memory_extract_job(
                outcome=result_status, duration_seconds=duration, scope=scope
            )
            return JobProcessResult(
                outcome=result_status,
                job_id=job.id,
                error=str(failure),
            )

        await acknowledge_message(self.redis, message.stream_id)
        observe_memory_extract_job(
            outcome="succeeded", duration_seconds=duration, scope=scope
        )
        return JobProcessResult(outcome="succeeded", job_id=job.id)

    async def _process_knowledge_job(self, message: QueueMessage) -> JobProcessResult:
        job_id = str(message.payload.get("job_id") or message.aggregate_id or "")
        if not job_id:
            error = "Knowledge queue message does not identify a job"
            await publish_dead_letter(self.redis, message, error=error)
            await acknowledge_message(self.redis, message.stream_id)
            return JobProcessResult(outcome="dead", error=error)

        async with self.session_factory() as db:
            job = await claim_knowledge_job(
                db,
                job_id=job_id,
                worker_id=self.consumer_name,
            )
            existing = job or await db.get(IngestionJob, job_id)
            await db.commit()
        if job is None:
            if existing is None:
                error = f"Knowledge job not found: {job_id}"
                await publish_dead_letter(self.redis, message, error=error)
                await acknowledge_message(self.redis, message.stream_id)
                return JobProcessResult(outcome="dead", job_id=job_id, error=error)
            await acknowledge_message(self.redis, message.stream_id)
            return JobProcessResult(outcome="duplicate", job_id=job_id)

        handler = self.handlers.get(job.job_type)
        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(job.id, stop_heartbeat)
        )
        failure: Exception | None = None
        retryable = True
        if handler is None:
            failure = ValueError(f"Unsupported Knowledge job type: {job.job_type}")
            retryable = False
        else:
            try:
                async with self.session_factory() as db:
                    current = await db.get(IngestionJob, job.id)
                    if current is None:
                        raise ValueError("Knowledge job disappeared during execution")
                    await handler(db, current, self.context)
                    await db.commit()
            except Exception as exc:
                failure = exc

        stop_heartbeat.set()
        await heartbeat_task

        if failure is None:
            async with self.session_factory() as db:
                current = await db.get(IngestionJob, job.id)
                if current is None or not await complete_knowledge_job(
                    db,
                    current,
                    worker_id=self.consumer_name,
                ):
                    await db.rollback()
                    failure = RuntimeError(
                        "Knowledge job lease was lost before completion"
                    )
                else:
                    await db.commit()

        if failure is not None:
            async with self.session_factory() as db:
                current = await db.get(IngestionJob, job.id)
                if current is None:
                    result_status = "dead"
                else:
                    result = await fail_knowledge_job(
                        db,
                        current,
                        worker_id=self.consumer_name,
                        error=failure,
                        retryable=retryable,
                    )
                    result_status = result.status
                    if result_status == "dead":
                        payload = dict(current.payload_json or {})
                        sync_run_id = str(payload.get("sync_run_id") or "")
                        if sync_run_id:
                            sync_run = await db.get(ConnectorSyncRun, sync_run_id)
                            if sync_run is not None:
                                sync_run.status = "failed"
                                sync_run.error_message = str(failure)[:8000]
                                sync_run.completed_at = datetime.datetime.utcnow()
                        if current.document_version_id:
                            version = await db.get(
                                KnowledgeDocumentVersion,
                                current.document_version_id,
                            )
                            if version is not None and version.status in {
                                "uploaded",
                                "quarantined",
                                "processing",
                            }:
                                version.status = "failed"
                                version.failure_reason = f"Processing retries exhausted: {str(failure)[:7900]}"
                        if current.index_version_id:
                            index_version = await db.get(
                                KnowledgeIndexVersion,
                                current.index_version_id,
                            )
                            if (
                                index_version is not None
                                and index_version.status != "active"
                            ):
                                index_version.status = "failed"
                                index_version.active_scope_key = None
                                index_version.failure_reason = (
                                    f"Indexing retries exhausted: {str(failure)[:7900]}"
                                )
                    await db.commit()
            if result_status == "dead":
                await publish_dead_letter(self.redis, message, error=str(failure))
            await acknowledge_message(self.redis, message.stream_id)
            return JobProcessResult(
                outcome=result_status,
                job_id=job.id,
                error=str(failure),
            )

        await acknowledge_message(self.redis, message.stream_id)
        return JobProcessResult(outcome="succeeded", job_id=job.id)

    async def run_forever(self, stop: asyncio.Event) -> None:
        await ensure_consumer_group(self.redis)
        reclaim_cursor = "0-0"
        while not stop.is_set():
            try:
                reclaim_cursor, reclaimed = await reclaim_stale_messages(
                    self.redis,
                    consumer_name=self.consumer_name,
                    start_id=reclaim_cursor,
                )
                for message in reclaimed:
                    await self.process_message(message)
                if reclaim_cursor == "0-0":
                    messages = await read_new_messages(
                        self.redis,
                        consumer_name=self.consumer_name,
                    )
                    for message in messages:
                        await self.process_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Knowledge worker loop failed")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1.0)
                except TimeoutError:
                    pass
