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
