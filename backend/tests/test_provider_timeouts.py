"""Provider calls: explicit timeouts, no resend after the body was delivered, configurable pool."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.services import openrouter_image_service as ois


def test_only_pre_send_failures_are_resent():
    assert ois.is_safe_to_resend_post(httpx.ConnectError("x"))
    assert ois.is_safe_to_resend_post(httpx.ConnectTimeout("x"))
    assert ois.is_safe_to_resend_post(httpx.WriteError("x"))
    assert not ois.is_safe_to_resend_post(httpx.ReadTimeout("x"))
    assert not ois.is_safe_to_resend_post(httpx.ReadError("x"))
    assert not ois.is_safe_to_resend_post(httpx.RemoteProtocolError("server disconnected"))
    # The broader predicate (used by strategy fallbacks) still treats these as transient.
    assert ois.is_retryable_openrouter_transport_error(httpx.ReadTimeout("x"))


async def test_post_is_not_resent_after_read_timeout_but_is_after_connect_error():
    calls = {"n": 0}

    class Client:
        async def post(self, url, **kw):
            calls["n"] += 1
            raise httpx.ReadTimeout("slow provider")

    class Client2:
        async def post(self, url, **kw):
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    with (
        patch.object(ois, "get_openrouter_http_client", lambda: Client()),
        patch.object(ois, "OPENROUTER_DISCONNECT_BACKOFF_SEC", (0.0,)),
    ):
        with pytest.raises(httpx.ReadTimeout):
            await ois.post_openrouter_json("https://o.test/x", headers={}, json_payload={}, max_attempts=5)
    assert calls["n"] == 1, "a paid POST that timed out on read must not be sent again"

    calls["n"] = 0
    with (
        patch.object(ois, "get_openrouter_http_client", lambda: Client2()),
        patch.object(ois, "OPENROUTER_DISCONNECT_BACKOFF_SEC", (0.0,)),
    ):
        resp = await ois.post_openrouter_json("https://o.test/x", headers={}, json_payload={}, max_attempts=5)
    assert resp.status_code == 200 and calls["n"] == 3


def test_pool_size_and_image_timeout_come_from_settings(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(openrouter_max_connections=5, image_request_timeout_seconds=42.0),
    )
    assert ois.openrouter_max_connections() == 5
    assert ois.image_request_timeout() == 42.0
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace())
    assert ois.openrouter_max_connections() == 32


def test_images_module_no_longer_hardcodes_180():
    import inspect

    from app.api import images

    src = inspect.getsource(images)
    assert 'kwargs["timeout"] = 180' not in src
    assert "OPENROUTER_FALLBACK_TIMEOUT" not in src


def test_chat_completion_carries_provider_timeout(monkeypatch):
    import inspect

    from app.services import proxy_service

    src = inspect.getsource(proxy_service)
    assert '"timeout": float(getattr(settings, "chat_provider_timeout_seconds"' in src


def test_video_duration_cap_is_enforced(monkeypatch):
    from app.api import videos

    src = __import__("inspect").getsource(videos)
    assert "video_max_duration_seconds" in src and "exceeds the deployment limit" in src
