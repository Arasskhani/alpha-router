"""Ticket images: only allowed image types, within the limits, scanned, and stored as a clean PNG."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile
from PIL import Image

from app.services import support_ticket_images, upload_screening
from app.services.malware_scan_service import MalwareScanResult
from app.services.support_tickets import TicketError, TicketSettings


def _image(fmt: str, size=(40, 30), **save) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, format=fmt, **save)
    return out.getvalue()


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


@pytest.fixture
def stored(monkeypatch):
    puts: dict[str, bytes] = {}
    monkeypatch.setattr(
        support_ticket_images.object_storage_service, "put_object", lambda key, body, ct: puts.__setitem__(key, body)
    )
    monkeypatch.setattr(
        upload_screening,
        "scan_bytes",
        AsyncMock(return_value=MalwareScanResult(clean=True, signature=None, raw_response="stream: OK")),
    )
    return puts


async def test_a_jpeg_with_camera_data_is_kept_as_a_clean_png(stored):
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # Make
    jpeg = _image("JPEG", exif=exif.tobytes())
    [image] = await support_ticket_images.store_ticket_images(
        [_upload("shot.jpeg", jpeg)], TicketSettings(), owner_user_id=7
    )
    assert image.mime == "image/png" and (image.width, image.height) == (40, 30)
    assert image.storage_key.startswith("tickets/7/") and image.display_name == "shot.jpeg"
    body = stored[image.storage_key]
    assert body.startswith(b"\x89PNG") and b"SecretCam" not in body


async def test_the_same_picture_twice_gets_two_keys(stored):
    png = _image("PNG")
    first = await support_ticket_images.store_ticket_images([_upload("a.png", png)], TicketSettings(), owner_user_id=1)
    second = await support_ticket_images.store_ticket_images([_upload("a.png", png)], TicketSettings(), owner_user_id=1)
    assert first[0].storage_key != second[0].storage_key


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'),
        ("run.exe", b"MZ\x90\x00"),
        ("fake.png", b"MZ\x90\x00" + b"\x00" * 64),
        ("page.png", b"<html><script>alert(1)</script></html>"),
        ("shot.heic", b"\x00\x00\x00\x18ftypheic"),
    ],
)
async def test_anything_but_an_allowed_image_is_refused(stored, name, data):
    with pytest.raises(TicketError) as refused:
        await support_ticket_images.store_ticket_images([_upload(name, data)], TicketSettings(), owner_user_id=1)
    assert refused.value.code == "image_rejected" and refused.value.extra["file"] == name
    assert stored == {}


async def test_a_type_the_administrator_turned_off_is_refused(stored):
    settings = TicketSettings(image_types=["png"])
    with pytest.raises(TicketError) as refused:
        await support_ticket_images.store_ticket_images([_upload("a.gif", _image("GIF"))], settings, owner_user_id=1)
    assert "PNG" in refused.value.message


async def test_a_gif_named_png_is_refused_when_gif_is_off(stored):
    settings = TicketSettings(image_types=["png"])
    with pytest.raises(TicketError):
        await support_ticket_images.store_ticket_images([_upload("a.png", _image("GIF"))], settings, owner_user_id=1)


async def test_size_side_and_count_limits(stored):
    settings = TicketSettings(max_image_mb=1, max_images=2, max_side_px=512)
    big = _image("PNG", size=(600, 10))
    with pytest.raises(TicketError) as refused:
        await support_ticket_images.store_ticket_images([_upload("wide.png", big)], settings, owner_user_id=1)
    assert "512 px" in refused.value.message
    with pytest.raises(TicketError) as refused:
        await support_ticket_images.store_ticket_images(
            [_upload("huge.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * (1024 * 1024 + 10))], settings, owner_user_id=1
        )
    assert refused.value.status_code == 413 and refused.value.code == "image_too_large"
    with pytest.raises(TicketError) as refused:
        await support_ticket_images.store_ticket_images(
            [_upload(f"{n}.png", _image("PNG")) for n in range(3)], settings, owner_user_id=1
        )
    assert refused.value.code == "too_many_images"
    assert stored == {}


async def test_one_bad_file_stores_none_of_them(stored):
    with pytest.raises(TicketError):
        await support_ticket_images.store_ticket_images(
            [_upload("ok.png", _image("PNG")), _upload("bad.svg", b"<svg></svg>")], TicketSettings(), owner_user_id=1
        )
    assert stored == {}


async def test_malware_is_refused(stored, monkeypatch):
    monkeypatch.setattr(
        upload_screening,
        "scan_bytes",
        AsyncMock(return_value=MalwareScanResult(clean=False, signature="X", raw_response="stream: FOUND")),
    )
    with pytest.raises(TicketError) as refused:
        await support_ticket_images.store_ticket_images(
            [_upload("a.png", _image("PNG"))], TicketSettings(), owner_user_id=1
        )
    assert refused.value.code == "image_rejected" and stored == {}
