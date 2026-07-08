"""Tests for NITRO media URL → data URL resolution before upstream image APIs."""

from app.api.images import parse_nitro_media_asset_id


def test_parse_nitro_media_asset_id_relative():
    assert parse_nitro_media_asset_id("/api/chat/media/3/file") == 3


def test_parse_nitro_media_asset_id_absolute():
    assert parse_nitro_media_asset_id("http://localhost:8080/api/chat/media/42/file") == 42


def test_parse_nitro_media_asset_id_with_query():
    assert parse_nitro_media_asset_id("/api/chat/media/7/file?token=x") == 7


def test_parse_nitro_media_asset_id_rejects_other_urls():
    assert parse_nitro_media_asset_id("https://cdn.example.com/a.png") is None
    assert parse_nitro_media_asset_id("data:image/png;base64,abc") is None
