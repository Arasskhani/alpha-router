"""S3-compatible object storage (SeaweedFS) for media blobs."""

from __future__ import annotations

import logging
from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from app.config import get_settings

logger = logging.getLogger(__name__)


class ObjectNotFoundError(FileNotFoundError):
    """Raised when an object key is missing in the bucket."""


@lru_cache
def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        use_ssl=settings.s3_use_ssl,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )


def media_object_key(user_slug: str, content_hash: str, ext: str) -> str:
    """CDN layout: cdn/u/{username}/{sha256}{ext}"""
    prefix = get_settings().media_cdn_prefix.strip("/")
    slug = (user_slug or "").strip() or "unknown"
    safe_hash = (content_hash or "").strip() or "unknown"
    safe_ext = ext if ext.startswith(".") else f".{ext}" if ext else ".bin"
    return f"{prefix}/u/{slug}/{safe_hash}{safe_ext}"


def is_cdn_object_key(storage_path: str) -> bool:
    prefix = get_settings().media_cdn_prefix.strip("/")
    normalized = (storage_path or "").replace("\\", "/").lstrip("/")
    return normalized.startswith(f"{prefix}/")


def _normalize_key(key: str) -> str:
    return key.replace("\\", "/").lstrip("/")


def verify_connection() -> None:
    """Fail fast when object storage (S3 API) is unreachable."""
    try:
        _client().list_buckets()
    except (ClientError, EndpointConnectionError, OSError, ConnectionError) as exc:
        settings = get_settings()
        raise RuntimeError(
            f"Object storage unavailable at {settings.s3_endpoint_url}. "
            "Start SeaweedFS (docker compose up -d seaweedfs) and retry."
        ) from exc


def ensure_bucket() -> None:
    verify_connection()
    settings = get_settings()
    client = _client()
    bucket = settings.s3_bucket
    try:
        client.head_bucket(Bucket=bucket)
        return
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in ("404", "NoSuchBucket", "403", "400"):
            raise
    try:
        client.create_bucket(Bucket=bucket)
        logger.info("Created object storage bucket %s", bucket)
    except ClientError:
        client.head_bucket(Bucket=bucket)


def put_object(key: str, body: bytes, content_type: str) -> None:
    settings = get_settings()
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=_normalize_key(key),
        Body=body,
        ContentType=content_type or "application/octet-stream",
    )


def get_object_bytes(key: str) -> bytes:
    settings = get_settings()
    try:
        resp = _client().get_object(Bucket=settings.s3_bucket, Key=_normalize_key(key))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            raise ObjectNotFoundError(_normalize_key(key)) from exc
        raise
    return resp["Body"].read()


def object_exists(key: str) -> bool:
    settings = get_settings()
    try:
        _client().head_object(Bucket=settings.s3_bucket, Key=_normalize_key(key))
        return True
    except ClientError:
        return False


def delete_object(key: str) -> None:
    settings = get_settings()
    try:
        _client().delete_object(Bucket=settings.s3_bucket, Key=_normalize_key(key))
    except ClientError:
        logger.debug("Failed to delete object %s", _normalize_key(key), exc_info=True)


def cdn_user_prefix(user_slug: str) -> str:
    """Object key prefix for one user's media folder (includes trailing slash)."""
    prefix = get_settings().media_cdn_prefix.strip("/")
    slug = (user_slug or "").strip() or "unknown"
    return f"{prefix}/u/{slug}/"


def delete_objects_under_prefix(prefix: str) -> int:
    """Delete all objects under a key prefix; returns count removed."""
    settings = get_settings()
    normalized = _normalize_key(prefix)
    if not normalized:
        return 0
    if not normalized.endswith("/"):
        normalized = f"{normalized}/"

    client = _client()
    deleted = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=normalized):
        batch = [{"Key": obj["Key"]} for obj in (page.get("Contents") or []) if obj.get("Key")]
        if not batch:
            continue
        for i in range(0, len(batch), 1000):
            chunk = batch[i : i + 1000]
            client.delete_objects(
                Bucket=settings.s3_bucket,
                Delete={"Objects": chunk, "Quiet": True},
            )
            deleted += len(chunk)
    return deleted


def purge_user_cdn_objects(username_slug: str, user_id: int) -> int:
    """Remove all CDN blobs for a user (username path + legacy numeric id path)."""
    deleted = delete_objects_under_prefix(cdn_user_prefix(username_slug))
    deleted += delete_objects_under_prefix(cdn_user_prefix(str(user_id)))
    return deleted
