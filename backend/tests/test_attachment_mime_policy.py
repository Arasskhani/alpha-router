"""MIME allowlist and Content-Disposition policy for chat attachments (H1)."""

from app.services.attachment_policy import (
    coerce_safe_storage_mime,
    is_inline_image_media,
    media_response_type_and_disposition,
    resolve_attachment_mime,
)
from app.services.storage_service import media_content_hash


def test_document_upload_ignores_client_html_mime():
    mime = resolve_attachment_mime(
        filename="notes.txt",
        kind="document",
        client_mime="text/html",
    )
    assert mime == "text/plain"


def test_document_md_never_stores_html():
    mime = resolve_attachment_mime(
        filename="readme.md",
        kind="document",
        client_mime="text/html; charset=utf-8",
    )
    assert mime == "text/plain"


def test_unknown_document_extension_maps_to_octet_stream_via_allowed_path():
    # pdf is mapped; unknown allowed types fall through to octet-stream only if unmapped
    mime = resolve_attachment_mime(
        filename="report.pdf",
        kind="document",
        client_mime="application/x-msdownload",
    )
    assert mime == "application/pdf"


def test_coerce_strips_unsafe_mime_for_documents():
    assert coerce_safe_storage_mime("document", "text/html") == "application/octet-stream"
    assert coerce_safe_storage_mime("document", "image/svg+xml") == "application/octet-stream"
    assert coerce_safe_storage_mime("document", "text/plain") == "text/plain"


def test_media_content_hash_strips_html_for_documents():
    blob = b"<script>alert(1)</script>"
    out_blob, mime, digest = media_content_hash(blob, "text/html", "document")
    assert out_blob == blob
    assert mime == "application/octet-stream"
    assert len(digest) == 64


def test_document_served_as_attachment_with_safe_mime():
    media_type, disposition = media_response_type_and_disposition(
        file_name="notes.txt",
        kind="document",
        stored_mime="text/html",
    )
    assert media_type == "text/plain"
    assert disposition.startswith("attachment;")
    assert "notes.txt" in disposition or "filename*=UTF-8''notes.txt" in disposition


def test_legacy_html_mime_on_md_forced_to_attachment():
    media_type, disposition = media_response_type_and_disposition(
        file_name="x.md",
        kind="document",
        stored_mime="text/html",
    )
    assert media_type == "text/plain"
    assert disposition.startswith("attachment;")


def test_image_still_inline():
    assert is_inline_image_media(kind="image", mime="image/png") is True
    media_type, disposition = media_response_type_and_disposition(
        file_name="photo.png",
        kind="image",
        stored_mime="image/png",
    )
    assert media_type == "image/png"
    assert disposition.startswith("inline;")


def test_svg_mime_never_inline():
    assert is_inline_image_media(kind="image", mime="image/svg+xml") is False
    media_type, disposition = media_response_type_and_disposition(
        file_name="icon.png",
        kind="image",
        stored_mime="image/svg+xml",
    )
    assert disposition.startswith("attachment;")
    assert media_type == "application/octet-stream"
