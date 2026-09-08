"""Request-body ceiling derived from Storage transfer limits."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.request_body_limit_service import (
    REQUEST_BODY_HARD_MAX_MB,
    REQUEST_BODY_MARGIN_MB,
    effective_request_body_limit_bytes,
    publish_request_body_limit_mb,
    read_published_request_body_limit_mb,
    resolve_request_body_limit_mb,
    resolve_request_body_limit_mb_from_limits,
)
from app.services.tls_edge_service import (
    read_nginx_client_max_body_mb,
    render_nginx_config,
    sync_edge_body_limit,
)


def _workdir() -> Path:
    root = Path(__file__).resolve().parent / "_tmp_request_body_limit"
    root.mkdir(parents=True, exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_resolve_request_body_uses_max_plus_margin():
    assert resolve_request_body_limit_mb(upload_mb=100, chat_total_mb=200) == 200 + REQUEST_BODY_MARGIN_MB
    assert resolve_request_body_limit_mb(upload_mb=500, chat_total_mb=100) == 500 + REQUEST_BODY_MARGIN_MB


def test_resolve_request_body_respects_hard_max():
    assert (
        resolve_request_body_limit_mb(upload_mb=1024, chat_total_mb=2048)
        == REQUEST_BODY_HARD_MAX_MB
    )


def test_resolve_from_limits_dict():
    assert (
        resolve_request_body_limit_mb_from_limits(
            {"max_upload_file_mb": 25, "max_chat_attachments_total_mb": 36}
        )
        == 36 + REQUEST_BODY_MARGIN_MB
    )


def test_publish_and_read_shared_limit(monkeypatch):
    tmp_path = _workdir()
    settings = SimpleNamespace(tls_state_dir=str(tmp_path))
    monkeypatch.setattr(
        "app.services.request_body_limit_service.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.services.tls_edge_service.tls_state_dir",
        lambda: tmp_path,
    )

    published = publish_request_body_limit_mb(128)
    assert published == 128
    assert read_published_request_body_limit_mb() == 128
    assert effective_request_body_limit_bytes() == 128 * 1024 * 1024
    data = json.loads((tmp_path / "request-body-limit.json").read_text(encoding="utf-8"))
    assert data["request_body_mb"] == 128


def test_nginx_conf_embeds_body_mb_and_parser_reads_it():
    tmp_path = _workdir()
    conf = render_nginx_config(
        https_port=443,
        http_mode="loopback_only",
        hsts_enabled=False,
        has_chain=False,
        max_body_mb=44,
    )
    path = tmp_path / "nginx.conf"
    path.write_text(conf, encoding="utf-8")
    assert "client_max_body_size 44m;" in conf
    assert read_nginx_client_max_body_mb(path) == 44


def test_sync_edge_body_limit_https_disabled_still_publishes(monkeypatch):
    tmp_path = _workdir()
    monkeypatch.setattr(
        "app.services.request_body_limit_service.get_settings",
        lambda: SimpleNamespace(tls_state_dir=str(tmp_path)),
    )
    monkeypatch.setattr("app.services.tls_edge_service.tls_state_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.services.tls_edge_service.read_desired_state",
        lambda: {"enabled": False, "generation": 0},
    )

    db = AsyncMock()
    with patch(
        "app.services.tls_edge_service._resolve_edge_body_mb",
        new=AsyncMock(return_value=44),
    ):
        result = asyncio.run(sync_edge_body_limit(db))

    assert result["reason"] == "https_disabled"
    assert result["body_mb"] == 44
    assert result["queued"] is False
    assert read_published_request_body_limit_mb() == 44
    db.commit.assert_not_awaited()
