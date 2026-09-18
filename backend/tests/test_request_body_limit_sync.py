"""Request-body ceiling derived from Storage transfer limits."""

from __future__ import annotations

import json
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


def test_resolve_request_body_uses_max_plus_margin():
    assert resolve_request_body_limit_mb(upload_mb=100, chat_total_mb=200) == 200 + REQUEST_BODY_MARGIN_MB
    assert resolve_request_body_limit_mb(upload_mb=500, chat_total_mb=100) == 500 + REQUEST_BODY_MARGIN_MB


def test_resolve_request_body_respects_hard_max():
    assert resolve_request_body_limit_mb(upload_mb=1024, chat_total_mb=2048) == REQUEST_BODY_HARD_MAX_MB


def test_resolve_from_limits_dict():
    assert (
        resolve_request_body_limit_mb_from_limits({"max_upload_file_mb": 25, "max_chat_attachments_total_mb": 36})
        == 36 + REQUEST_BODY_MARGIN_MB
    )


def test_publish_and_read_shared_limit(monkeypatch, tmp_path):
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


def test_nginx_conf_embeds_body_mb_and_parser_reads_it(tmp_path):
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


async def test_sync_edge_body_limit_https_disabled_still_publishes(monkeypatch, tmp_path):
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
        result = await sync_edge_body_limit(db)

    assert result["reason"] == "https_disabled"
    assert result["body_mb"] == 44
    assert result["queued"] is False
    assert read_published_request_body_limit_mb() == 44
    db.commit.assert_not_awaited()


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.calls = 0

    async def set(self, key: str, value: str) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        self.calls += 1
        return self.store.get(key)


class _DownRedis:
    async def get(self, key: str) -> str | None:
        raise ConnectionError("redis down")

    async def set(self, key: str, value: str) -> None:
        raise ConnectionError("redis down")


async def test_redis_publish_reaches_other_workers(monkeypatch, tmp_path) -> None:
    import app.core.redis_client as redis_client
    import app.services.request_body_limit_service as svc

    monkeypatch.setattr(svc, "get_settings", lambda: SimpleNamespace(tls_state_dir=str(tmp_path)))
    monkeypatch.setattr("app.services.tls_edge_service.tls_state_dir", lambda: tmp_path)
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis", lambda: fake)
    svc.invalidate_published_cache()

    assert await svc.publish_request_body_limit_mb_async(256) == 256
    assert fake.store[svc.REQUEST_BODY_LIMIT_REDIS_KEY] == "256"
    # File fallback is still written for single-host installs.
    assert svc.read_published_request_body_limit_mb() == 256

    # "Another worker" (fresh cache) on a host without the file sees Redis.
    svc.invalidate_published_cache()
    (tmp_path / svc.REQUEST_BODY_LIMIT_FILENAME).unlink()
    assert await svc.refresh_request_body_limit_from_redis() == 256
    assert svc.effective_request_body_limit_bytes() == 256 * 1024 * 1024
    # Within the TTL no further Redis round-trip is made.
    calls = fake.calls
    assert await svc.refresh_request_body_limit_from_redis() == 256
    assert fake.calls == calls


async def test_redis_outage_falls_back_to_file_and_backs_off(monkeypatch, tmp_path) -> None:
    import app.core.redis_client as redis_client
    import app.services.request_body_limit_service as svc

    monkeypatch.setattr(svc, "get_settings", lambda: SimpleNamespace(tls_state_dir=str(tmp_path)))
    monkeypatch.setattr("app.services.tls_edge_service.tls_state_dir", lambda: tmp_path)
    monkeypatch.setattr(redis_client, "get_redis", lambda: _DownRedis())
    svc.invalidate_published_cache()

    assert await svc.publish_request_body_limit_mb_async(64) == 64  # file written, Redis error logged
    svc.invalidate_published_cache()
    assert await svc.refresh_request_body_limit_from_redis() is None
    assert svc.effective_request_body_limit_bytes() == 64 * 1024 * 1024
    # Failure arms the back-off: the next call returns without touching Redis.
    _, _, retry_at = svc._redis_cache
    assert retry_at > svc.time.monotonic()
