"""Unit tests for image size normalization and aspect-ratio mapping."""

import asyncio
import base64
import io

from PIL import Image

from app.api.images import (
    _aspect_ratio_to_default_size,
    _map_size_to_aspect_ratio,
    _normalize_aspect_ratio,
    _normalize_image_size,
    _reference_image_bytes,
    _resolve_generation_dimensions,
)
from app.services.openrouter_image_service import _gemini_image_size_tier


async def _resolve_from_aspect_ratio() -> None:
    aspect, size = await _resolve_generation_dimensions(
        reference_image=None,
        aspect_ratio="16:9",
        size="1024x1024",
    )
    assert aspect == "16:9"
    assert size == "1344x768"


async def _resolve_from_reference_image() -> None:
    img = Image.new("RGB", (640, 480), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    aspect, size = await _resolve_generation_dimensions(
        reference_image=data_url,
        aspect_ratio="1:1",
        size="1024x1024",
    )
    assert size == "640x480"
    assert aspect == "4:3"


def test_resolve_generation_dimensions_from_aspect_ratio():
    asyncio.run(_resolve_from_aspect_ratio())


def test_resolve_generation_dimensions_from_reference_image():
    asyncio.run(_resolve_from_reference_image())


def test_normalize_aspect_ratio():
    assert _normalize_aspect_ratio("16:9") == "16:9"
    assert _normalize_aspect_ratio(" 21 : 9 ") == "21:9"
    assert _normalize_aspect_ratio("invalid") is None


def test_aspect_ratio_to_default_size():
    assert _aspect_ratio_to_default_size("16:9") == "1344x768"
    assert _aspect_ratio_to_default_size("1:1") == "1024x1024"


def test_reference_image_bytes_roundtrip():
    raw = b"\x89PNG\r\n\x1a\n"
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    assert _reference_image_bytes(data_url) == raw


def test_normalize_image_size_rounds_to_multiples_of_8():
    assert _normalize_image_size("1281x721") == "1280x720"
    assert _normalize_image_size(" 1792 x 1024 ") == "1792x1024"


def test_normalize_image_size_clamps_bounds():
    assert _normalize_image_size("100x100") == "256x256"
    assert _normalize_image_size("4000x3000") == "2048x2048"


def test_normalize_image_size_invalid_fallback():
    assert _normalize_image_size("auto") == "1024x1024"
    assert _normalize_image_size("") == "1024x1024"


def test_map_size_to_aspect_ratio_known_presets():
    assert _map_size_to_aspect_ratio("1024x1024") == "1:1"
    assert _map_size_to_aspect_ratio("1344x768") == "16:9"
    assert _map_size_to_aspect_ratio("768x1344") == "9:16"
    assert _map_size_to_aspect_ratio("1792x1024") == "16:9"


def test_map_size_to_aspect_ratio_custom_sizes():
    assert _map_size_to_aspect_ratio("1280x720") == "16:9"
    assert _map_size_to_aspect_ratio("1920x1080") == "16:9"
    assert _map_size_to_aspect_ratio("1536x2048") == "3:4"
    assert _map_size_to_aspect_ratio("1000x800") == "5:4"


def test_gemini_image_size_tier():
    assert _gemini_image_size_tier("1024x1024") == "1K"
    assert _gemini_image_size_tier("1536x1024") == "2K"
    assert _gemini_image_size_tier("1792x1024") == "2K"
    assert _gemini_image_size_tier("2048x2048") == "4K"
