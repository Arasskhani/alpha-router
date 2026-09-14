"""Shared HTTP request-body ceiling derived from Storage transfer limits.

Published to the TLS state volume so every Uvicorn worker and the edge nginx
config stay aligned without waiting for an edge reload inside API requests.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings

LOGGER = logging.getLogger("app.services.request_body_limit")

# Multipart overhead for multi-file chat uploads (boundaries + part headers).
REQUEST_BODY_MARGIN_MB = 8
# Align with transfer_limits_service.MAX_CHAT_ATTACHMENTS_TOTAL_MB.
REQUEST_BODY_HARD_MAX_MB = 2048
REQUEST_BODY_LIMIT_FILENAME = "request-body-limit.json"


def resolve_request_body_limit_mb(*, upload_mb: int, chat_total_mb: int) -> int:
    """Return the nginx/middleware request ceiling in MiB."""
    upload = max(1, int(upload_mb))
    chat_total = max(1, int(chat_total_mb))
    raw = max(upload, chat_total) + REQUEST_BODY_MARGIN_MB
    return max(1, min(REQUEST_BODY_HARD_MAX_MB, raw))


def resolve_request_body_limit_mb_from_limits(limits: dict[str, Any]) -> int:
    return resolve_request_body_limit_mb(
        upload_mb=int(limits.get("max_upload_file_mb") or 1),
        chat_total_mb=int(limits.get("max_chat_attachments_total_mb") or 1),
    )


def _state_dir() -> Path:
    raw = (getattr(get_settings(), "tls_state_dir", "") or "").strip()
    return Path(raw) if raw else Path("/app/tls")


def request_body_limit_path() -> Path:
    return _state_dir() / REQUEST_BODY_LIMIT_FILENAME


def publish_request_body_limit_mb(body_mb: int) -> int:
    """Atomically publish the shared ceiling for all app workers."""
    from app.services.tls_edge_service import atomic_write

    clamped = max(1, min(REQUEST_BODY_HARD_MAX_MB, int(body_mb)))
    payload = {
        "request_body_mb": clamped,
        "request_body_bytes": clamped * 1024 * 1024,
        "margin_mb": REQUEST_BODY_MARGIN_MB,
        "hard_max_mb": REQUEST_BODY_HARD_MAX_MB,
    }
    atomic_write(
        request_body_limit_path(),
        json.dumps(payload, indent=2) + "\n",
        mode=0o644,
    )
    # The publishing worker must see its own change at once; the others pick
    # it up within the cache TTL via the mtime check.
    invalidate_published_cache()
    return clamped


def read_published_request_body_limit_mb() -> int | None:
    path = request_body_limit_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        value = int(data.get("request_body_mb") or 0)
    except (TypeError, ValueError):
        return None
    if value < 1:
        return None
    return max(1, min(REQUEST_BODY_HARD_MAX_MB, value))


# Routes whose bodies are allowed to be as large as the upload ceiling:
# multipart file uploads, and the chat/gateway JSON bodies that carry inline
# base64 images for vision models. Everything else is ordinary JSON and gets
# ``max_json_body_bytes``.
LARGE_BODY_PATH_PREFIXES: tuple[str, ...] = (
    "/api/chat/",            # completions (inline images), attachments/process, voice
    "/v1/",                  # OpenAI-compatible gateway (inline images, embeddings input)
    "/api/images",           # image edit/reference payloads
    "/api/videos",           # reference images
    "/api/speech",           # long TTS inputs
    "/api/projects/",        # resource / media uploads
    "/api/user/media",       # media library uploads
    "/api/user/chats",       # full-session sync payloads
    "/api/user/chat-sessions",
    "/api/admin/knowledge/", # document uploads
    "/api/admin/security/tls/",  # certificate bundles
)

_PUBLISHED_CACHE_TTL_SECONDS = 5.0
# (checked_at, path, mtime, mb) - keyed by path so a settings change is not served stale.
_published_cache: tuple[float, str | None, float | None, int | None] = (0.0, None, None, None)


def invalidate_published_cache() -> None:
    global _published_cache
    _published_cache = (0.0, None, None, None)


def is_large_body_path(path: str) -> bool:
    return path.startswith(LARGE_BODY_PATH_PREFIXES)


def request_body_limit_for(path: str) -> int:
    """Per-request ceiling: upload ceiling for known large-body routes, else JSON ceiling."""
    if is_large_body_path(path):
        return effective_request_body_limit_bytes()
    settings = get_settings()
    json_limit = int(getattr(settings, "max_json_body_bytes", 8 * 1024 * 1024) or 0)
    # Never exceed the upload ceiling and never go below 64 KiB.
    return max(64 * 1024, min(json_limit, effective_request_body_limit_bytes()))


def _read_published_cached() -> int | None:
    """read_published_request_body_limit_mb() with an mtime-aware short cache.

    The middleware asks for the ceiling on every request; a stat() every 5s is
    fine, a stat()+read()+json.loads() per request is not.
    """
    global _published_cache
    import time

    now = time.monotonic()
    path = request_body_limit_path()
    key = str(path)
    checked_at, cached_key, cached_mtime, cached_mb = _published_cache
    if cached_key == key and now - checked_at < _PUBLISHED_CACHE_TTL_SECONDS:
        return cached_mb
    try:
        mtime: float | None = path.stat().st_mtime
    except OSError:
        mtime = None
    if cached_key == key and mtime is not None and mtime == cached_mtime:
        _published_cache = (now, key, cached_mtime, cached_mb)
        return cached_mb
    value = read_published_request_body_limit_mb() if mtime is not None else None
    _published_cache = (now, key, mtime, value)
    return value


def effective_request_body_limit_bytes() -> int:
    """Best-effort upload ceiling for RequestBodyLimitMiddleware (all workers)."""
    published = _read_published_cached()
    if published is not None:
        return published * 1024 * 1024

    try:
        from app.services.transfer_limits_service import peek_cached_transfer_limits

        cached = peek_cached_transfer_limits()
        if cached:
            return resolve_request_body_limit_mb_from_limits(cached) * 1024 * 1024
    except Exception:
        LOGGER.debug("transfer-limits cache unavailable for request body ceiling", exc_info=True)

    settings = get_settings()
    fallback = int(getattr(settings, "max_request_body_bytes", 1024 * 1024 * 1024) or 0)
    return max(1024 * 1024, min(REQUEST_BODY_HARD_MAX_MB * 1024 * 1024, fallback))
