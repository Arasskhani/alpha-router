"""Project media cannot serve a script on the application's own origin.

Upload stored the client's ``Content-Type`` verbatim and download replayed it,
marking anything ``image/*`` inline. Uploading an SVG containing ``<script>``
with ``Content-Type: image/svg+xml`` therefore executed it on the app's origin.
The session cookie is HttpOnly, but the CSRF cookie is readable by design
(double-submit), so the script could read the token and act as the victim - and
a project member can be added without their consent, so the whole chain starts
from an ordinary user account.

This was an omission, not a design choice: ``UNSAFE_MEDIA_MIMES`` already listed
``image/svg+xml``, ``text/html`` and ``application/xhtml+xml``, and the personal
media path has coerced them since it shipped. Project media never called it.
"""

from __future__ import annotations

import pytest

from app.services.attachment_policy import (
    UNSAFE_MEDIA_MIMES,
    coerce_safe_storage_mime,
    media_response_type_and_disposition,
)

SVG_WITH_SCRIPT = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.mark.parametrize("declared", sorted(UNSAFE_MEDIA_MIMES))
async def test_an_unsafe_type_is_never_stored(declared):
    stored = coerce_safe_storage_mime("image", declared)
    assert stored == "application/octet-stream", declared


@pytest.mark.parametrize("declared", sorted(UNSAFE_MEDIA_MIMES))
def test_an_unsafe_type_is_never_served_inline(declared):
    media_type, disposition = media_response_type_and_disposition(
        file_name="payload.svg",
        kind="image",
        stored_mime=declared,
    )
    assert media_type == "application/octet-stream", declared
    assert "attachment" in disposition, declared


async def test_uploading_an_svg_stores_an_inert_type(db_session, monkeypatch):
    from app.core.security import hash_password
    from app.models.user import User
    from app.services.project_media_service import upload_project_media
    from app.services.project_service import create_project

    owner = User(
        username="svg_uploader",
        hashed_password=hash_password("a-password"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(owner)
    await db_session.flush()
    project = await create_project(db_session, user=owner, name="Media")

    class _Store:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}

        async def put(self, key, body, mime):
            self.objects[key] = body

        async def get(self, key):
            return self.objects[key]

        async def delete(self, key):
            self.objects.pop(key, None)

        async def exists(self, key):
            return key in self.objects

    uploaded = await upload_project_media(
        db_session,
        project_id=project["id"],
        user=owner,
        file_name="payload.svg",
        mime_type="image/svg+xml",
        content_bytes=SVG_WITH_SCRIPT,
        object_store=_Store(),
    )

    assert uploaded["mimeType"] == "application/octet-stream", (
        "an SVG must not be stored under a type the browser will render"
    )
    media_type, disposition = media_response_type_and_disposition(
        file_name=uploaded["fileName"],
        kind=uploaded["kind"],
        stored_mime=uploaded["mimeType"],
    )
    assert media_type == "application/octet-stream"
    assert "attachment" in disposition


def test_the_download_handler_uses_the_safe_helper():
    """A regression here re-opens stored XSS, so assert the call site exists."""

    import inspect

    from app.api import projects

    source = inspect.getsource(projects.download_project_media_endpoint)
    assert "media_response_type_and_disposition" in source
    assert 'disposition = "inline"' not in source, "the hand-rolled inline rule is back"


async def test_an_ordinary_image_still_renders_inline():
    """The fix must not turn every project image into a download."""

    media_type, disposition = media_response_type_and_disposition(
        file_name="photo.png",
        kind="image",
        stored_mime="image/png",
    )
    assert media_type == "image/png"
    assert "inline" in disposition
