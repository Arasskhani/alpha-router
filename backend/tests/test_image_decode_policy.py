"""Pillow decompression and dimension policy regression tests."""

import io

import pytest
from PIL import Image

from app.config import get_settings
from app.services.image_decode_policy import ImagePolicyError, image_dimensions, normalize_image
from app.services.storage_service import media_content_hash


def _png(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), (20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def test_safe_image_is_normalized_and_dimensioned() -> None:
    get_settings.cache_clear()
    blob = _png(32, 16)
    assert image_dimensions(blob) == (32, 16)
    normalized, mime, digest = normalize_image(blob)
    assert mime == "image/png"
    assert normalized.startswith(b"\x89PNG")
    assert len(digest) == 64


def test_image_over_configured_side_is_rejected_before_convert(monkeypatch) -> None:
    monkeypatch.setenv("MAX_IMAGE_SIDE_PX", "2048")
    get_settings.cache_clear()
    with pytest.raises(ImagePolicyError, match="dimensions"):
        normalize_image(_png(2049, 1))
    get_settings.cache_clear()


def test_invalid_image_cannot_fall_back_to_raw_storage() -> None:
    get_settings.cache_clear()
    with pytest.raises(ImagePolicyError):
        media_content_hash(b"not-an-image", "image/png", "image")
