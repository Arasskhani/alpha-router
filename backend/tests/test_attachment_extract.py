"""Tests for attachment image handling."""

import base64

import pytest

from app.services.attachment_extract import build_image_data_url, processed_attachment_payload
from app.services.attachment_policy import AttachmentPolicyError

# Minimal valid PNG (1x1 red pixel)
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_png_with_embedded_svg_string_in_metadata_is_allowed():
    """PNG text chunks may contain '<svg' — must not be rejected as SVG."""
    raw = _PNG_1X1 + b"\x00" + b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    url = build_image_data_url(raw, "image/png", "photo.png")
    assert url.startswith("data:image/png;base64,")


def test_real_svg_is_rejected():
    raw = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'
    with pytest.raises(AttachmentPolicyError, match="SVG"):
        build_image_data_url(raw, "image/svg+xml", "icon.svg")


def test_processed_attachment_payload_png():
    payload = processed_attachment_payload(
        filename="test.png",
        kind="image",
        mime_type="image/png",
        url="blob:test",
        raw=_PNG_1X1,
    )
    assert payload["data_url"].startswith("data:image/png;base64,")
