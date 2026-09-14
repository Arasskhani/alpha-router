"""HTTP Range serving for video media assets."""

from app.services.attachment_policy import (
    is_inline_video_media,
    media_response_type_and_disposition,
)


def test_inline_video_mime_allowlist():
    assert is_inline_video_media(kind="video", mime="video/mp4")
    assert is_inline_video_media(kind="video", mime="video/webm")
    assert not is_inline_video_media(kind="document", mime="video/mp4")


def test_video_response_is_inline():
    media_type, disposition = media_response_type_and_disposition(
        file_name="clip.mp4",
        kind="video",
        stored_mime="video/mp4",
    )
    assert media_type == "video/mp4"
    assert disposition.startswith("inline")


async def test_range_request_fetches_only_the_window():
    """A seek must cost one partial GET, not a full download sliced in Python."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from app.api import chat
    from app.services.object_storage_service import InvalidRangeError

    row = SimpleNamespace(id=1, kind="video", mime_type="video/mp4", file_name="clip.mp4", size_bytes=1000)

    async def run(range_header, range_result=None, range_exc=None):
        full = AsyncMock(return_value=b"x" * 1000)
        partial = AsyncMock(return_value=range_result, side_effect=range_exc)
        with (
            patch.object(chat, "load_authorized_media_asset", AsyncMock(return_value=row)),
            patch.object(chat, "read_media_bytes", full),
            patch.object(chat, "read_media_range", partial),
        ):
            resp = await chat.media_file(
                1,
                request=SimpleNamespace(headers={"range": range_header} if range_header else {}),
                user=SimpleNamespace(id=1),
                db=object(),
            )
        return resp, full, partial

    resp, full, partial = await run("bytes=100-199", (b"y" * 100, 100, 199, 1000))
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 100-199/1000"
    assert resp.headers["Content-Length"] == "100"
    partial.assert_awaited_once_with(row, "100-199")
    full.assert_not_awaited()

    resp, full, partial = await run("bytes=5000-", None, InvalidRangeError("5000-"))
    assert resp.status_code == 416 and resp.headers["Content-Range"] == "bytes */1000"
    full.assert_not_awaited()

    resp, full, partial = await run(None)
    assert resp.status_code == 200 and resp.headers["Content-Length"] == "1000"
    partial.assert_not_awaited()

    # Multi-range and malformed specs fall back to the full body (as before).
    resp, full, partial = await run("bytes=0-1,5-9")
    assert resp.status_code == 200
    partial.assert_not_awaited()
