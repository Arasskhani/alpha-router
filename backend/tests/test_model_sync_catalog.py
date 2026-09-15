"""Provider catalog request and response normalization tests."""

from unittest.mock import patch

from app.services.model_sync import (
    _openrouter_snapshot,
    fetch_openrouter_models,
    fetch_provider_models,
)


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    """Stands in for the shared provider client.

    The catalog fetchers no longer build a client per call -- they borrow the
    pooled, retrying one -- so the seam to patch is the accessor, not
    ``httpx.AsyncClient``. Deliberately not a context manager: closing the
    shared client would break every other provider request in flight, and this
    stub would raise if a caller tried.
    """

    response = _Response({"data": []})
    calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


async def test_openrouter_requests_complete_catalog():
    _Client.calls = []
    _Client.response = _Response({"data": [{"id": "runway/gen-4"}]})
    with patch("app.services.model_sync.get_provider_rest_client", _Client):
        result = await fetch_openrouter_models("sk-test", None)
    assert result == [{"id": "runway/gen-4"}]
    assert _Client.calls[0][1]["params"] == {"output_modalities": "all"}


async def test_google_catalog_normalizes_models_response_and_uses_api_key():
    _Client.calls = []
    _Client.response = _Response({"models": [{"name": "models/gemini-2.5-flash", "displayName": "Gemini"}]})
    with patch("app.services.model_sync.get_provider_rest_client", _Client):
        result = await fetch_provider_models("google", "google-key", "https://example.test/v1beta")
    assert result[0]["id"] == "gemini-2.5-flash"
    assert _Client.calls[0][1]["params"] == {"key": "google-key"}
    assert _Client.calls[0][1]["headers"]["Cache-Control"].startswith("no-cache")


def test_openrouter_general_catalog_does_not_mark_non_video_models_as_video():
    snapshot = _openrouter_snapshot(
        {
            "id": "provider/general-model",
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["text", "video"],
            },
        },
        None,
    )
    assert snapshot["architecture"]["output_modalities"] == ["text"]
    assert "video_generation" not in snapshot


def test_openrouter_snapshot_clears_stale_media_metadata():
    snapshot = _openrouter_snapshot(
        {
            "id": "provider/general-model",
            "architecture": {"output_modalities": ["text", "video", "image"]},
            "video_generation": {"id": "stale/video"},
            "video_capabilities": {"supported_durations": [4]},
            "image_generation": {"id": "stale/image"},
        },
        None,
        None,
    )
    assert snapshot["architecture"]["output_modalities"] == ["text"]
    assert "video_generation" not in snapshot
    assert "video_capabilities" not in snapshot
    assert "image_generation" not in snapshot


def test_openrouter_video_catalog_remains_video_authoritative():
    video_meta = {
        "id": "provider/video-model",
        "supported_durations": [5],
    }
    snapshot = _openrouter_snapshot(
        {
            "id": "provider/video-model",
            "architecture": {"output_modalities": ["video"]},
        },
        video_meta,
    )
    assert snapshot["video_generation"] is video_meta
    assert "video_capabilities" in snapshot
