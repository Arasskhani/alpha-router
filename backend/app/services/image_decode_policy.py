"""Fail-closed Pillow policy for untrusted image bytes."""

from __future__ import annotations

import io
import warnings
from hashlib import sha256

from PIL import Image

HARD_MAX_IMAGE_SIDE_PX = 8192
HARD_MAX_IMAGE_PIXELS = 32 * 1024 * 1024
MAX_IMAGE_DECODE_BYTES = 96 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = HARD_MAX_IMAGE_PIXELS


class ImagePolicyError(ValueError):
    pass


def _configured_limits() -> tuple[int, int, int]:
    from app.config import get_settings
    from app.services.bounded_io import clamp_limit

    settings = get_settings()
    compressed = clamp_limit(
        settings.max_media_input_bytes,
        minimum=1024 * 1024,
        maximum=50 * 1024 * 1024,
    )
    side = clamp_limit(
        settings.max_image_side_px,
        minimum=2048,
        maximum=HARD_MAX_IMAGE_SIDE_PX,
    )
    pixels = clamp_limit(
        settings.max_image_pixels,
        minimum=2048 * 2048,
        maximum=HARD_MAX_IMAGE_PIXELS,
    )
    return compressed, side, pixels


def _validate_dimensions(width: int, height: int, *, max_side: int, max_pixels: int) -> None:
    if width <= 0 or height <= 0:
        raise ImagePolicyError("Image dimensions are invalid")
    if width > max_side or height > max_side:
        raise ImagePolicyError(f"Image dimensions exceed {max_side}px")
    if width * height > max_pixels:
        raise ImagePolicyError("Image pixel count exceeds the allowed limit")


def image_dimensions(blob: bytes) -> tuple[int, int]:
    max_compressed, max_side, max_pixels = _configured_limits()
    if len(blob) > max_compressed:
        raise ImagePolicyError("Image file exceeds the allowed limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(blob)) as image:
                width, height = image.size
                _validate_dimensions(width, height, max_side=max_side, max_pixels=max_pixels)
                image.verify()
                return int(width), int(height)
    except ImagePolicyError:
        raise
    except Exception as exc:
        raise ImagePolicyError("Invalid or unsafe image") from exc


def normalize_image(blob: bytes) -> tuple[bytes, str, str]:
    max_compressed, max_side, max_pixels = _configured_limits()
    if len(blob) > max_compressed:
        raise ImagePolicyError("Image file exceeds the allowed limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(blob)) as image:
                width, height = image.size
                _validate_dimensions(width, height, max_side=max_side, max_pixels=max_pixels)
                rgb = image.convert("RGB")
                if width * height * 3 > MAX_IMAGE_DECODE_BYTES:
                    raise ImagePolicyError("Decoded image exceeds the allowed limit")
                pixels = rgb.tobytes()
                output = io.BytesIO()
                rgb.save(output, format="PNG", optimize=True)
                digest = sha256(
                    f"{width}x{height}".encode() + rgb.mode.encode() + pixels
                ).hexdigest()
                return output.getvalue(), "image/png", digest
    except ImagePolicyError:
        raise
    except Exception as exc:
        raise ImagePolicyError("Invalid or unsafe image") from exc
