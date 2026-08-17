"""Incremental HTTP, static, and S3 Knowledge connector framework."""

from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import json
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

import boto3
import httpx
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.knowledge import (
    ConnectorSyncRun,
    IngestionJob,
    KnowledgeBase,
    KnowledgeConnector,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from app.services.bounded_io import BoundedIOError, read_http_response_bounded
from app.services.knowledge_ingestion_service import (
    DocumentSubmission,
    record_knowledge_audit,
    submit_document_bytes,
)
from app.services.knowledge_job_service import enqueue_knowledge_job
from app.services.knowledge_object_store import KnowledgeObjectStoreProtocol
from app.services.secret_crypto import decrypt_secret, encrypt_secret
from app.services.ssrf_guard import (
    assert_response_target_safe,
    assert_url_safe,
    safe_client,
)

CONNECTOR_SYNC_JOB = "connector.sync"
SUPPORTED_CONNECTOR_TYPES = frozenset({"static", "http", "s3"})
_SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "authorization",
        "password",
        "secret",
        "token",
        "api_key",
        "access_key",
        "secret_key",
        "session_token",
    }
)
_FORBIDDEN_HTTP_HEADERS = frozenset(
    {
        "host",
        "connection",
        "content-length",
        "transfer-encoding",
        "proxy-authorization",
    }
)


@dataclass(frozen=True)
class ConnectorItem:
    key: str
    title: str
    data: bytes
    mime_type: str
    source_uri: str
    fingerprint: str


def _contains_sensitive_key(value) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_CONFIG_KEYS or _contains_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _validate_connector_config(connector_type: str, config: dict) -> dict:
    normalized_type = (connector_type or "").strip().lower()
    if normalized_type not in SUPPORTED_CONNECTOR_TYPES:
        raise ValueError(f"Unsupported connector type: {normalized_type}")
    if _contains_sensitive_key(config):
        raise ValueError("Connector secrets must be supplied as encrypted credentials")
    clean = json.loads(json.dumps(config))
    if normalized_type == "static":
        items = clean.get("items")
        if not isinstance(items, list) or not items or len(items) > 500:
            raise ValueError("Static connector requires between 1 and 500 items")
    elif normalized_type == "http":
        urls = clean.get("urls")
        if not isinstance(urls, list) or not urls or len(urls) > 500:
            raise ValueError("HTTP connector requires between 1 and 500 URLs")
        for url in urls:
            assert_url_safe(str(url))
    else:
        bucket = str(clean.get("bucket") or "").strip()
        if not bucket:
            raise ValueError("S3 connector bucket is required")
        endpoint = str(clean.get("endpoint_url") or "").strip()
        if endpoint:
            assert_url_safe(endpoint)
        clean["max_objects"] = min(5_000, max(1, int(clean.get("max_objects") or 500)))
    return clean


def _encrypt_credentials(credentials: dict | None) -> str | None:
    if not credentials:
        return None
    serialized = json.dumps(credentials, sort_keys=True, separators=(",", ":"))
    return encrypt_secret(serialized)


def _decrypt_credentials(connector: KnowledgeConnector) -> dict:
    if not connector.credentials_encrypted:
        return {}
    plaintext = decrypt_secret(connector.credentials_encrypted)
    value = json.loads(plaintext or "{}")
    if not isinstance(value, dict):
        raise ValueError("Connector credentials are malformed")
    return value


async def create_connector(
    db: AsyncSession,
    *,
    knowledge_base_id: str,
    connector_type: str,
    name: str,
    config: dict,
    credentials: dict | None,
    created_by_user_id: int,
    sync_interval_minutes: int | None = None,
    activate: bool = False,
) -> KnowledgeConnector:
    clean_config = _validate_connector_config(connector_type, config)
    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or knowledge_base.status in {"suspended", "archived"}:
        raise ValueError("Knowledge Base is not available for connectors")
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Connector name is required")
    duplicate = (
        await db.execute(
            select(KnowledgeConnector.id).where(
                KnowledgeConnector.knowledge_base_id == knowledge_base_id,
                KnowledgeConnector.name == clean_name[:255],
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise ValueError("Connector name already exists in this Knowledge Base")
    interval = (
        min(43_200, max(5, int(sync_interval_minutes)))
        if sync_interval_minutes is not None
        else None
    )
    connector = KnowledgeConnector(
        id=str(uuid.uuid4()),
        knowledge_base_id=knowledge_base_id,
        connector_type=connector_type.strip().lower(),
        name=clean_name[:255],
        status="active" if activate else "draft",
        config_json=clean_config,
        credentials_encrypted=_encrypt_credentials(credentials),
        checkpoint_json={},
        sync_interval_minutes=interval,
        created_by_user_id=created_by_user_id,
    )
    db.add(connector)
    await db.flush()
    await record_knowledge_audit(
        db,
        knowledge_base_id=knowledge_base_id,
        document_id=None,
        event_type="knowledge.connector.created",
        actor_user_id=created_by_user_id,
        payload={
            "connector_id": connector.id,
            "connector_type": connector.connector_type,
            "active": activate,
        },
    )
    return connector


async def update_connector(
    db: AsyncSession,
    *,
    connector_id: str,
    actor_user_id: int | None,
    name: str | None = None,
    status: str | None = None,
    config: dict | None = None,
    sync_interval_minutes: int | None = None,
    clear_sync_interval: bool = False,
) -> KnowledgeConnector:
    connector = await db.get(KnowledgeConnector, connector_id)
    if connector is None:
        raise ValueError("Connector not found")
    changes: dict[str, object] = {}
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Connector name is required")
        duplicate = (
            await db.execute(
                select(KnowledgeConnector.id).where(
                    KnowledgeConnector.knowledge_base_id == connector.knowledge_base_id,
                    KnowledgeConnector.name == clean_name[:255],
                    KnowledgeConnector.id != connector.id,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ValueError("Connector name already exists in this Knowledge Base")
        connector.name = clean_name[:255]
        changes["name"] = connector.name
    if status is not None:
        normalized = status.strip().lower()
        if normalized not in {"draft", "active", "paused", "failed", "archived"}:
            raise ValueError("Unsupported connector status")
        connector.status = normalized
        changes["status"] = normalized
    if config is not None:
        connector.config_json = _validate_connector_config(
            connector.connector_type,
            config,
        )
        changes["config"] = True
    if clear_sync_interval:
        connector.sync_interval_minutes = None
        changes["sync_interval_minutes"] = None
    elif sync_interval_minutes is not None:
        connector.sync_interval_minutes = min(
            43_200, max(5, int(sync_interval_minutes))
        )
        changes["sync_interval_minutes"] = connector.sync_interval_minutes
    connector.updated_at = datetime.datetime.utcnow()
    await record_knowledge_audit(
        db,
        knowledge_base_id=connector.knowledge_base_id,
        document_id=None,
        event_type="knowledge.connector.updated",
        actor_user_id=actor_user_id,
        payload={"connector_id": connector.id, "fields": sorted(changes)},
    )
    return connector


async def list_connector_documents(
    db: AsyncSession,
    *,
    connector: KnowledgeConnector,
) -> list[KnowledgeDocument]:
    prefix = f"connector/{connector.id}/"
    return list(
        (
            await db.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_base_id == connector.knowledge_base_id,
                    KnowledgeDocument.canonical_key.like(f"{prefix}%"),
                    KnowledgeDocument.status != "deleted",
                )
            )
        )
        .scalars()
        .all()
    )


async def disable_connector(
    db: AsyncSession,
    *,
    connector_id: str,
    actor_user_id: int | None,
    reason: str,
    revoke_content: bool = True,
    archive: bool = True,
) -> tuple[KnowledgeConnector, list[KnowledgeDocument]]:
    from app.services.knowledge_ingestion_service import soft_revoke_document

    connector = await update_connector(
        db,
        connector_id=connector_id,
        actor_user_id=actor_user_id,
        status="archived" if archive else "paused",
    )
    revoked_documents: list[KnowledgeDocument] = []
    if revoke_content:
        for document in await list_connector_documents(db, connector=connector):
            if document.status == "revoked":
                revoked_documents.append(document)
                continue
            await soft_revoke_document(
                db,
                document=document,
                actor_user_id=actor_user_id,
                reason=reason,
            )
            revoked_documents.append(document)
    await record_knowledge_audit(
        db,
        knowledge_base_id=connector.knowledge_base_id,
        document_id=None,
        event_type="knowledge.connector.disabled",
        actor_user_id=actor_user_id,
        reason=(reason or "")[:8000],
        payload={
            "connector_id": connector.id,
            "status": connector.status,
            "revoked_document_count": len(revoked_documents),
        },
    )
    return connector, revoked_documents


async def schedule_connector_sync(
    db: AsyncSession,
    *,
    connector_id: str,
    requested_by_user_id: int | None,
) -> ConnectorSyncRun:
    connector_statement = select(KnowledgeConnector).where(
        KnowledgeConnector.id == connector_id
    )
    if db.get_bind().dialect.name == "postgresql":
        connector_statement = connector_statement.with_for_update()
    connector = (await db.execute(connector_statement)).scalar_one_or_none()
    if connector is None or connector.status != "active":
        raise ValueError("Connector must be active before synchronization")
    active_run = (
        await db.execute(
            select(ConnectorSyncRun)
            .where(
                ConnectorSyncRun.connector_id == connector.id,
                ConnectorSyncRun.status.in_(("pending", "running")),
            )
            .order_by(ConnectorSyncRun.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if active_run is not None:
        return active_run
    sync_run = ConnectorSyncRun(
        id=str(uuid.uuid4()),
        connector_id=connector.id,
        status="pending",
        checkpoint_json=dict(connector.checkpoint_json or {}),
    )
    db.add(sync_run)
    await db.flush()
    await enqueue_knowledge_job(
        db,
        knowledge_base_id=connector.knowledge_base_id,
        job_type=CONNECTOR_SYNC_JOB,
        idempotency_key=f"connector-sync:{connector.id}:{sync_run.id}",
        payload={
            "connector_id": connector.id,
            "sync_run_id": sync_run.id,
            "requested_by_user_id": requested_by_user_id,
        },
    )
    return sync_run


async def schedule_due_connectors(
    db: AsyncSession,
    *,
    now: datetime.datetime | None = None,
    limit: int = 100,
) -> int:
    current = now or datetime.datetime.utcnow()
    statement = (
        select(KnowledgeConnector)
        .where(
            KnowledgeConnector.status == "active",
            KnowledgeConnector.sync_interval_minutes.is_not(None),
        )
        .order_by(
            KnowledgeConnector.last_synced_at,
            KnowledgeConnector.created_at,
        )
        .limit(max(1, min(limit, 1000)))
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    connectors = (await db.execute(statement)).scalars().all()
    scheduled = 0
    for connector in connectors:
        interval = max(5, int(connector.sync_interval_minutes or 5))
        if (
            connector.last_synced_at is not None
            and connector.last_synced_at + datetime.timedelta(minutes=interval)
            > current
        ):
            continue
        active_run = (
            await db.execute(
                select(ConnectorSyncRun.id)
                .where(
                    ConnectorSyncRun.connector_id == connector.id,
                    ConnectorSyncRun.status.in_(("pending", "running")),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active_run is not None:
            continue
        await schedule_connector_sync(
            db,
            connector_id=connector.id,
            requested_by_user_id=None,
        )
        scheduled += 1
    return scheduled


def _static_items(connector: KnowledgeConnector) -> list[ConnectorItem]:
    output: list[ConnectorItem] = []
    for index, raw in enumerate(dict(connector.config_json or {}).get("items", [])):
        if not isinstance(raw, dict):
            raise ValueError("Static connector items must be objects")
        key = str(raw.get("key") or f"item-{index}").strip()
        title = str(raw.get("title") or key).strip()
        mime = str(raw.get("mime_type") or "text/plain").strip()
        if "content_base64" in raw:
            data = base64.b64decode(str(raw["content_base64"]), validate=True)
        else:
            data = str(raw.get("content") or "").encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        output.append(
            ConnectorItem(
                key=key,
                title=title,
                data=data,
                mime_type=mime,
                source_uri=f"static://{connector.id}/{key}",
                fingerprint=digest,
            )
        )
    return output


def _http_headers(credentials: dict) -> dict[str, str]:
    raw = credentials.get("headers") or {}
    if not isinstance(raw, dict):
        raise ValueError("HTTP connector headers must be an object")
    output: dict[str, str] = {}
    for key, value in raw.items():
        normalized = str(key).strip()
        if not normalized or normalized.lower() in _FORBIDDEN_HTTP_HEADERS:
            raise ValueError(f"HTTP connector header is not allowed: {normalized}")
        output[normalized] = str(value)
    return output


async def _fetch_http_item(
    client: httpx.AsyncClient,
    *,
    url: str,
    credentials: dict,
    previous: dict,
) -> tuple[ConnectorItem | None, dict]:
    headers = _http_headers(credentials)
    if previous.get("etag"):
        headers["If-None-Match"] = str(previous["etag"])
    if previous.get("last_modified"):
        headers["If-Modified-Since"] = str(previous["last_modified"])
    current_url = url
    response: httpx.Response | None = None
    for hop in range(5):
        assert_url_safe(current_url)
        async with client.stream("GET", current_url, headers=headers) as current:
            assert_response_target_safe(current)
            if current.status_code in {301, 302, 303, 307, 308}:
                location = current.headers.get("location")
                if not location or hop >= 4:
                    raise BoundedIOError("HTTP connector redirect limit exceeded")
                current_url = urljoin(current_url, location)
                continue
            if current.status_code == 304:
                return None, previous
            current.raise_for_status()
            data = await read_http_response_bounded(
                current,
                max_bytes=get_settings().knowledge_max_upload_bytes,
            )
            response = current
            break
    if response is None:
        raise BoundedIOError("HTTP connector redirect limit exceeded")
    parsed = urlparse(url)
    file_name = unquote(PurePosixPath(parsed.path).name) or "index.html"
    mime = (
        response.headers.get("content-type", "application/octet-stream")
        .split(";", 1)[0]
        .strip()
    )
    digest = hashlib.sha256(data).hexdigest()
    key = f"{hashlib.sha256(url.encode()).hexdigest()[:20]}-{file_name}"
    checkpoint = {
        "etag": response.headers.get("etag"),
        "last_modified": response.headers.get("last-modified"),
        "sha256": digest,
        "url": current_url,
    }
    if previous.get("sha256") == digest:
        return None, checkpoint
    return (
        ConnectorItem(
            key=key,
            title=file_name,
            data=data,
            mime_type=mime,
            source_uri=current_url,
            fingerprint=digest,
        ),
        checkpoint,
    )


def _s3_client(config: dict, credentials: dict):
    return boto3.client(
        "s3",
        endpoint_url=str(config.get("endpoint_url") or "").strip() or None,
        region_name=str(config.get("region") or "us-east-1"),
        aws_access_key_id=credentials.get("access_key"),
        aws_secret_access_key=credentials.get("secret_key"),
        aws_session_token=credentials.get("session_token"),
        use_ssl=bool(config.get("use_ssl", True)),
        config=Config(
            signature_version="s3v4",
            connect_timeout=10,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _list_s3_objects(config: dict, credentials: dict) -> list[dict]:
    client = _s3_client(config, credentials)
    bucket = str(config["bucket"])
    prefix = str(config.get("prefix") or "")
    maximum = int(config.get("max_objects") or 500)
    output: list[dict] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents") or []:
            if str(item.get("Key") or "").endswith("/"):
                continue
            output.append(
                {
                    "key": str(item["Key"]),
                    "etag": str(item.get("ETag") or "").strip('"'),
                    "size": int(item.get("Size") or 0),
                    "last_modified": (
                        item["LastModified"].isoformat()
                        if item.get("LastModified") is not None
                        else None
                    ),
                }
            )
            if len(output) >= maximum:
                return output
    return output


def _read_s3_object(config: dict, credentials: dict, key: str) -> tuple[bytes, str]:
    maximum = get_settings().knowledge_max_upload_bytes
    client = _s3_client(config, credentials)
    response = client.get_object(Bucket=str(config["bucket"]), Key=key)
    declared = int(response.get("ContentLength") or 0)
    if declared > maximum:
        response["Body"].close()
        raise BoundedIOError("S3 connector object exceeds the allowed limit")
    output = bytearray()
    body = response["Body"]
    try:
        while True:
            chunk = body.read(64 * 1024)
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > maximum:
                raise BoundedIOError("S3 connector object exceeds the allowed limit")
    finally:
        body.close()
    mime = str(response.get("ContentType") or "").strip()
    if not mime:
        mime = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return bytes(output), mime


def _canonical_item_key(connector_id: str, item_key: str) -> str:
    digest = hashlib.sha256(item_key.encode("utf-8")).hexdigest()[:20]
    file_name = PurePosixPath(item_key.replace("\\", "/")).name or "document"
    return f"connector/{connector_id}/{digest}-{file_name}"


async def _submit_connector_item(
    db: AsyncSession,
    connector: KnowledgeConnector,
    item: ConnectorItem,
    *,
    object_store: KnowledgeObjectStoreProtocol | None,
) -> DocumentSubmission:
    return await submit_document_bytes(
        db,
        knowledge_base_id=connector.knowledge_base_id,
        file_name=PurePosixPath(item.key.replace("\\", "/")).name or item.title,
        declared_mime=item.mime_type,
        data=item.data,
        uploaded_by_user_id=connector.created_by_user_id,
        title=item.title,
        canonical_key=_canonical_item_key(connector.id, item.key),
        source_type="connector",
        source_uri=item.source_uri,
        object_store=object_store,
    )


async def _propagate_deletions(
    db: AsyncSession,
    connector: KnowledgeConnector,
    *,
    discovered_canonical_keys: set[str],
) -> int:
    prefix = f"connector/{connector.id}/"
    documents = (
        (
            await db.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_base_id == connector.knowledge_base_id,
                    KnowledgeDocument.canonical_key.like(f"{prefix}%"),
                    KnowledgeDocument.status != "deleted",
                )
            )
        )
        .scalars()
        .all()
    )
    deleted = 0
    now = datetime.datetime.utcnow()
    for document in documents:
        if document.canonical_key in discovered_canonical_keys:
            continue
        document.status = "revoked"
        document.revoked_at = now
        active_versions = (
            (
                await db.execute(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.document_id == document.id,
                        KnowledgeDocumentVersion.active_scope_key.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for version in active_versions:
            version.status = "revoked"
            version.active_scope_key = None
            version.revoked_at = now
        deleted += 1
    return deleted


async def process_connector_sync(
    db: AsyncSession,
    job: IngestionJob,
    *,
    object_store: KnowledgeObjectStoreProtocol | None = None,
) -> None:
    payload = dict(job.payload_json or {})
    connector = await db.get(KnowledgeConnector, str(payload.get("connector_id") or ""))
    sync_run = await db.get(ConnectorSyncRun, str(payload.get("sync_run_id") or ""))
    if connector is None or sync_run is None:
        raise ValueError("Connector sync references a missing connector or run")
    if connector.status != "active":
        raise ValueError("Connector is not active")
    sync_run.status = "running"
    sync_run.started_at = sync_run.started_at or datetime.datetime.utcnow()
    await db.flush()

    config = dict(connector.config_json or {})
    credentials = _decrypt_credentials(connector)
    previous_checkpoint = dict(connector.checkpoint_json or {})
    next_checkpoint: dict = {"items": {}}
    discovered_keys: set[str] = set()
    created = updated = skipped = failures = 0
    retryable_failures = 0
    error_messages: list[str] = []

    async def submit(item: ConnectorItem) -> None:
        nonlocal created, updated, skipped, failures
        canonical = _canonical_item_key(connector.id, item.key)
        discovered_keys.add(canonical)
        try:
            async with db.begin_nested():
                result = await _submit_connector_item(
                    db,
                    connector,
                    item,
                    object_store=object_store,
                )
        except (BoundedIOError, ValueError) as exc:
            failures += 1
            error_messages.append(f"{item.key}: {str(exc)[:300]}")
            return
        if result.duplicate:
            skipped += 1
        elif result.version.version_number == 1:
            created += 1
        else:
            updated += 1

    if connector.connector_type == "static":
        for item in _static_items(connector):
            next_checkpoint["items"][item.key] = {"sha256": item.fingerprint}
            await submit(item)
    elif connector.connector_type == "http":
        previous_items = dict(previous_checkpoint.get("items") or {})
        async with safe_client() as client:
            for raw_url in config.get("urls", []):
                url = str(raw_url)
                source_file_name = (
                    unquote(PurePosixPath(urlparse(url).path).name) or "index.html"
                )
                source_key = (
                    f"{hashlib.sha256(url.encode()).hexdigest()[:20]}-"
                    f"{source_file_name}"
                )
                discovered_keys.add(_canonical_item_key(connector.id, source_key))
                try:
                    item, checkpoint = await _fetch_http_item(
                        client,
                        url=url,
                        credentials=credentials,
                        previous=dict(previous_items.get(url) or {}),
                    )
                    next_checkpoint["items"][url] = checkpoint
                    if item is None:
                        skipped += 1
                    else:
                        await submit(item)
                except (BoundedIOError, ValueError, httpx.HTTPError) as exc:
                    failures += 1
                    if isinstance(exc, httpx.TransportError) or (
                        isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code >= 500
                    ):
                        retryable_failures += 1
                    error_messages.append(f"{url}: {str(exc)[:300]}")
    elif connector.connector_type == "s3":
        previous_items = dict(previous_checkpoint.get("items") or {})
        objects = await asyncio.to_thread(_list_s3_objects, config, credentials)
        for descriptor in objects:
            key = descriptor["key"]
            discovered_keys.add(_canonical_item_key(connector.id, key))
            next_checkpoint["items"][key] = descriptor
            if previous_items.get(key) == descriptor:
                skipped += 1
                continue
            try:
                data, mime = await asyncio.to_thread(
                    _read_s3_object,
                    config,
                    credentials,
                    key,
                )
            except (BoundedIOError, BotoCoreError, ClientError, OSError) as exc:
                failures += 1
                if not isinstance(exc, (BoundedIOError, ValueError)):
                    retryable_failures += 1
                error_messages.append(f"{key}: {str(exc)[:300]}")
                continue
            await submit(
                ConnectorItem(
                    key=key,
                    title=PurePosixPath(key).name or key,
                    data=data,
                    mime_type=mime,
                    source_uri=f"s3://{config['bucket']}/{key}",
                    fingerprint=hashlib.sha256(data).hexdigest(),
                )
            )
    else:
        raise ValueError(f"Unsupported connector type: {connector.connector_type}")

    if retryable_failures and not (created or updated or skipped):
        raise RuntimeError("Connector synchronization failed for every source item")

    deleted = await _propagate_deletions(
        db,
        connector,
        discovered_canonical_keys=discovered_keys,
    )
    total = created + updated + skipped + failures
    now = datetime.datetime.utcnow()
    connector.checkpoint_json = next_checkpoint
    connector.last_synced_at = now
    sync_run.status = "partial" if failures else "succeeded"
    sync_run.discovered_count = total
    sync_run.created_count = created
    sync_run.updated_count = updated
    sync_run.deleted_count = deleted
    sync_run.skipped_count = skipped
    sync_run.checkpoint_json = next_checkpoint
    sync_run.error_message = "\n".join(error_messages)[:8000] or None
    sync_run.completed_at = now
    await record_knowledge_audit(
        db,
        knowledge_base_id=connector.knowledge_base_id,
        document_id=None,
        event_type="knowledge.connector.synced",
        actor_user_id=payload.get("requested_by_user_id"),
        payload={
            "connector_id": connector.id,
            "sync_run_id": sync_run.id,
            "status": sync_run.status,
            "created": created,
            "updated": updated,
            "deleted": deleted,
            "skipped": skipped,
            "failed": failures,
        },
    )
