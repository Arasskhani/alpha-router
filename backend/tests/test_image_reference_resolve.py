"""Tests for Alpharouter media URL → data URL resolution before upstream image APIs."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api import images
from app.api.images import parse_alpha_router_media_asset_id


def test_parse_alpha_router_media_asset_id_relative():
    assert parse_alpha_router_media_asset_id("/api/chat/media/3/file") == 3


def test_parse_alpha_router_media_asset_id_absolute():
    assert parse_alpha_router_media_asset_id("http://localhost:8080/api/chat/media/42/file") == 42


def test_parse_alpha_router_media_asset_id_with_query():
    assert parse_alpha_router_media_asset_id("/api/chat/media/7/file?token=x") == 7


def test_parse_alpha_router_media_asset_id_rejects_other_urls():
    assert parse_alpha_router_media_asset_id("https://cdn.example.com/a.png") is None
    assert parse_alpha_router_media_asset_id("data:image/png;base64,abc") is None


def test_remote_reference_is_fetched_by_alpha_router_not_forwarded_to_provider():
    async def run():
        with (
            patch.object(
                images,
                "resolve_media_blob",
                AsyncMock(return_value=(b"safe-image", "image/png")),
            ),
            patch(
                "app.services.image_decode_policy.image_dimensions",
                return_value=(16, 16),
            ),
        ):
            return await images.resolve_reference_image_for_upstream(
                object(),
                SimpleNamespace(id=1),
                "https://public.example/reference.png",
            )

    resolved = asyncio.run(run())
    assert resolved.startswith("data:image/png;base64,")
    assert "public.example" not in resolved
