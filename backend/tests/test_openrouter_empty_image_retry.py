"""Tests for transient empty OpenRouter image responses and retry helpers."""

import asyncio

import httpx

from app.services import openrouter_image_service as svc


def test_is_transient_empty_openrouter_image_response_detects_empty_shell():
    data = {
        "choices": [{"message": {"role": "assistant", "content": ""}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 0},
    }
    assert svc.is_transient_empty_openrouter_image_response(data, collected=None) is True


def test_is_transient_empty_openrouter_image_response_with_images():
    data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "images": [{"image_url": {"url": "data:image/png;base64,abc"}}],
                }
            }
        ],
    }
    assert svc.is_transient_empty_openrouter_image_response(data, collected=None) is False


def test_is_transient_empty_openrouter_image_response_text_is_not_transient_empty():
    data = {
        "choices": [{"message": {"role": "assistant", "content": "I cannot draw that."}}],
    }
    assert svc.is_transient_empty_openrouter_image_response(data, collected=None) is False


def test_build_openrouter_payload_omits_sort_when_disabled():
    payload = svc.build_fast_openrouter_payload(
        model_id="google/gemini-2.5-flash-image-preview",
        prompt="A red cat",
        size="1024x1024",
        modalities=["image", "text"],
        aspect_ratio="1:1",
        apply_default_provider_sort=False,
    )
    assert "sort" not in payload["provider"]


def test_post_openrouter_json_retries_after_disconnect(monkeypatch):
    calls = {"n": 0}

    class FakeClient:
        is_closed = False

        async def post(self, url, headers, json, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
            req = httpx.Request("POST", url)
            return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(svc, "get_openrouter_http_client", lambda: FakeClient())
    closed = {"v": False}

    async def _close():
        closed["v"] = True

    monkeypatch.setattr(svc, "close_openrouter_http_client", _close)

    async def _run():
        return await svc.post_openrouter_json(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": "Bearer test"},
            json_payload={"model": "test"},
            max_attempts=2,
        )

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert calls["n"] == 2
    assert closed["v"] is True
