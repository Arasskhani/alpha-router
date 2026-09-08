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


def effective_request_body_limit_bytes() -> int:
    """Best-effort ceiling for RequestBodyLimitMiddleware (all workers)."""
    published = read_published_request_body_limit_mb()
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
