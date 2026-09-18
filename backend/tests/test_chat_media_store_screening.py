"""Client-supplied media bytes go through the same screening as every upload.

``POST /api/chat/media/store`` accepts a base64 ``data_url`` or a URL to fetch,
and handed the result straight to object storage. ``upload_screening``'s own
docstring calls itself "the one place all of them call" - this path was the
exception, so ClamAV and the archive-bomb check never saw those bytes.

``store_generated_blob`` is deliberately not screened: its callers are the
image, video and speech generators, whose bytes came from a provider, not from
a browser.
"""

from __future__ import annotations

import base64

import pytest

from app.services import storage_service
from app.services.upload_screening import UploadRejected

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 64).decode()
DATA_URL = f"data:image/png;base64,{PNG}"


async def test_a_rejected_upload_never_reaches_storage(db_session, user, monkeypatch):
    stored: list[str] = []

    async def _reject(_raw, filename):
        raise UploadRejected(f"{filename}: infected", status_code=422)

    async def _store(*_args, **kwargs):
        stored.append(kwargs.get("kind", "?"))

    monkeypatch.setattr("app.services.upload_screening.screen_upload", _reject)
    monkeypatch.setattr(storage_service, "store_generated_blob", _store)

    with pytest.raises(UploadRejected):
        await storage_service.store_generated_media(
            db_session,
            user_id=user.id,
            username=user.username,
            kind="image",
            source_model=None,
            source_prompt=None,
            chat_session_id=None,
            data_url=DATA_URL,
        )
    assert stored == [], "the bytes were stored despite being rejected"


async def test_clean_bytes_are_screened_and_then_stored(db_session, user, monkeypatch):
    screened: list[str] = []
    stored: list[str] = []

    async def _screen(_raw, filename):
        screened.append(filename)

    async def _store(*_args, **kwargs):
        stored.append(kwargs.get("kind", "?"))

    monkeypatch.setattr("app.services.upload_screening.screen_upload", _screen)
    monkeypatch.setattr(storage_service, "store_generated_blob", _store)

    await storage_service.store_generated_media(
        db_session,
        user_id=user.id,
        username=user.username,
        kind="image",
        source_model=None,
        source_prompt=None,
        chat_session_id=None,
        data_url=DATA_URL,
        file_name_hint="picture.png",
    )

    assert screened == ["picture.png"], "the client-supplied bytes were not screened"
    assert stored == ["image"]


async def test_generated_media_is_not_screened(db_session, user, monkeypatch):
    """The provider paths must not gain a ClamAV round trip per generated image."""

    screened: list[str] = []

    async def _screen(_raw, filename):
        screened.append(filename)

    monkeypatch.setattr("app.services.upload_screening.screen_upload", _screen)

    import inspect

    source = inspect.getsource(storage_service.store_generated_blob)
    assert "screen_upload" not in source
    assert screened == []
