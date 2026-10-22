"""The images a ticket may carry: checked, cleaned and stored before a message keeps them.

Tickets take screenshots, nothing else. A file gets through only if its name
*and* its bytes are one of the image types the administrator allows (never
more than PNG, JPG, WEBP and GIF), it is within the size and side limits, it
decodes as an image, and the malware scan passes. What is stored is not the
upload but a fresh PNG drawn from its pixels: no EXIF, no GPS, no camera data,
no second frame of a GIF, nothing a crafted file could hide.

Images live under ``tickets/`` in object storage, outside every person's Media
quota, and are served only to the ticket's owner and the support staff.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import uuid
import warnings
from collections.abc import Sequence
from hashlib import sha256

from fastapi import UploadFile
from PIL import Image

from app.services import object_storage_service
from app.services.bounded_io import BoundedIOError, read_upload_bounded
from app.services.image_decode_policy import ImagePolicyError, normalize_image, platform_image_limits
from app.services.support_tickets import StoredImage, TicketError, TicketSettings
from app.services.upload_file_policy import UploadPolicyError, check_content
from app.services.upload_screening import UploadRejected, screen_upload

logger = logging.getLogger(__name__)

#: What the bytes must begin with for each type an administrator can allow.
_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
}
_TYPE_LABELS = {"png": "PNG", "jpg": "JPG", "webp": "WEBP", "gif": "GIF"}
_MAX_NAME = 255


def _extension(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
    return "jpg" if ext == "jpeg" else ext


def _sniff(head: bytes) -> str | None:
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    for kind, signatures in _SIGNATURES.items():
        if any(head.startswith(signature) for signature in signatures):
            return kind
    return None


def _display_name(filename: str) -> str:
    base = os.path.basename((filename or "").replace("\\", "/")).strip()
    base = " ".join(base.splitlines()) or "image"
    return base[:_MAX_NAME]


def _refuse(name: str, message: str, *, status_code: int = 422, code: str = "image_rejected") -> TicketError:
    return TicketError(code, f"{name}: {message}", status_code=status_code, extra={"file": name})


def _accepted(settings: TicketSettings) -> str:
    return ", ".join(_TYPE_LABELS.get(kind, kind.upper()) for kind in settings.image_types)


class _TooManyPixels(Exception):
    pass


def _side(raw: bytes) -> tuple[int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise _TooManyPixels from exc
    return int(width), int(height)


def _megapixels(pixels: int) -> str:
    return f"{pixels / 1_000_000:.1f}".rstrip("0").rstrip(".")


async def check_and_clean(upload: UploadFile, settings: TicketSettings) -> tuple[bytes, int, int, str]:
    """One upload, refused or turned into ``(png_bytes, width, height, display_name)``."""
    name = _display_name(upload.filename or "")
    allowed = set(settings.image_types)
    if _extension(name) not in allowed:
        raise _refuse(name, f"only images are accepted ({_accepted(settings)}).")
    limit = min(int(settings.max_image_mb) * 1024 * 1024, platform_image_limits()[0])
    try:
        raw = await read_upload_bounded(upload, max_bytes=limit)
    except BoundedIOError as exc:
        raise _refuse(
            name, f"larger than {settings.max_image_mb} MB.", status_code=413, code="image_too_large"
        ) from exc
    if not raw:
        raise _refuse(name, "the file is empty.")
    kind = _sniff(raw[:16])
    if kind is None or kind not in allowed:
        raise _refuse(name, f"its contents are not an image this form accepts ({_accepted(settings)}).")
    try:
        check_content(raw, ext=kind, kind="image")
    except UploadPolicyError as exc:
        raise _refuse(name, str(exc)) from exc
    _max_bytes, platform_side, max_pixels = platform_image_limits()
    too_many_pixels = f"too many pixels (more than {_megapixels(max_pixels)} million)."
    try:
        width, height = _side(raw)
    except _TooManyPixels as exc:
        raise _refuse(name, too_many_pixels) from exc
    except Exception as exc:  # noqa: BLE001 -- any decoder failure means "not an image we keep"
        raise _refuse(name, "it could not be read as an image.") from exc
    max_side = min(int(settings.max_side_px), platform_side)
    if max(width, height) > max_side:
        raise _refuse(name, f"larger than {max_side} px on its longest side.")
    if width * height > max_pixels:
        raise _refuse(name, too_many_pixels)
    try:
        await screen_upload(raw, name)
    except UploadRejected as exc:
        raise _refuse(name, str(exc), status_code=exc.status_code) from exc
    try:
        cleaned, _mime, _digest = await asyncio.to_thread(normalize_image, raw)
    except ImagePolicyError as exc:
        raise _refuse(name, str(exc)) from exc
    return cleaned, width, height, name


async def store_ticket_images(
    uploads: Sequence[UploadFile], settings: TicketSettings, *, owner_user_id: int
) -> list[StoredImage]:
    """Check, clean and store every upload, or refuse the lot: nothing is stored unless all of them pass."""
    files = [upload for upload in uploads if upload is not None and (upload.filename or "")]
    if len(files) > int(settings.max_images):
        raise TicketError(
            "too_many_images", f"Attach at most {settings.max_images} images to one message.", status_code=422
        )
    cleaned = [await check_and_clean(upload, settings) for upload in files]
    stored: list[StoredImage] = []
    try:
        for png, width, height, name in cleaned:
            digest = sha256(png).hexdigest()
            # Never shared: deleting one ticket's image must not take another's that happens to be the same picture.
            key = f"tickets/{int(owner_user_id)}/{uuid.uuid4().hex}.png"
            await asyncio.to_thread(object_storage_service.put_object, key, png, "image/png")
            stored.append(
                StoredImage(
                    storage_key=key,
                    mime="image/png",
                    bytes=len(png),
                    width=width,
                    height=height,
                    sha256=digest,
                    display_name=name,
                )
            )
    except BaseException:
        # All or nothing: a put that fails half way takes back the ones already stored.
        await forget_ticket_images(stored)
        raise
    return stored


async def forget_ticket_images(images: Sequence[StoredImage]) -> None:
    """Remove stored images no message kept (refused or failed after all); a leftover is logged, never raised."""
    for image in images:
        try:
            await asyncio.to_thread(object_storage_service.delete_object, image.storage_key)
        except Exception:  # noqa: BLE001 -- the refusal is the answer; a stray object is only logged
            logger.warning("A ticket image no message kept could not be removed: %s", image.storage_key, exc_info=True)


async def read_ticket_image(storage_key: str) -> bytes:
    """The stored PNG behind an attachment row."""
    return await asyncio.to_thread(object_storage_service.get_object_bytes, storage_key)
