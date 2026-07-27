"""Unit tests for chat export (markdown -> PDF) service.

These tests cover the pure, fast parts: markdown escaping/sanitization and
HTML document assembly. The Playwright-driven PDF render is exercised by an
integration test that is skipped when Chromium is unavailable.
"""

from app.services.chat_export_service import (
    ChatExportError,
    _build_html_document,
    _markdown_to_html,
    build_pdf_content_disposition,
)


def test_markdown_table_converted_to_html_table():
    md = "| نام | سن |\n| --- | --- |\n| علی | ۳۰ |\n| سارا | ۲۵ |"
    out = _markdown_to_html(md)
    assert "<table>" in out
    assert "<th" in out
    assert "علی" in out
    assert "سارا" in out


def test_markdown_fenced_code_block_preserved():
    md = "```python\nprint('hi')\n```"
    out = _markdown_to_html(md)
    assert "<pre" in out
    assert "<code" in out
    assert "print('hi')" in out


def test_raw_html_is_escaped_not_rendered():
    # A script tag in user/model content must NOT survive as a live element.
    md = "<script>alert(1)</script>"
    out = _markdown_to_html(md)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_inline_html_img_is_escaped():
    md = '<img src="http://internal/resource" onerror="steal()">'
    out = _markdown_to_html(md)
    # No live <img tag can form (the < is escaped), so onerror is inert text.
    assert "<img" not in out
    assert "&lt;img" in out


def test_ampersand_escaped_before_parsing():
    md = "Tom & Jerry <b>"
    out = _markdown_to_html(md)
    assert "&amp;" in out
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_markdown_headings_and_lists():
    md = "# Title\n\n- one\n- two\n"
    out = _markdown_to_html(md)
    assert "<h1>" in out
    assert "<ul>" in out
    assert "<li>one</li>" in out


def test_build_html_document_is_rtl_and_escapes_title():
    body = "<p>hello</p>"
    doc = _build_html_document(title="<b>bad</b>", body_html=body)
    assert 'dir="rtl"' in doc
    assert "<b>bad</b>" not in doc
    assert "&lt;b&gt;bad&lt;/b&gt;" in doc
    assert "<p>hello</p>" in doc


def test_render_chat_pdf_rejects_none():
    import asyncio

    from app.services.chat_export_service import render_chat_pdf

    try:
        asyncio.run(render_chat_pdf(content=None))  # type: ignore[arg-type]
        raise AssertionError("expected ChatExportError")
    except ChatExportError:
        pass


def test_render_chat_pdf_empty_string_rejected():
    import asyncio

    from app.services.chat_export_service import render_chat_pdf

    try:
        asyncio.run(render_chat_pdf(content="   "))
        raise AssertionError("expected ChatExportError")
    except ChatExportError:
        pass


def test_content_disposition_ascii_only_title():
    cd = build_pdf_content_disposition("My Report")
    assert 'filename="MyReport.pdf"' in cd
    assert "filename*=UTF-8''" in cd


def test_content_disposition_persian_title_is_latin1_safe():
    # Regression: a Persian title must not raise UnicodeEncodeError when the
    # header is encoded. The ASCII fallback is used for `filename=` and the
    # UTF-8 percent-encoded value is used for `filename*`.
    cd = build_pdf_content_disposition("تحلیل فروش ماهانه")
    # The whole header must be latin-1 encodable (this is what starlette does).
    cd.encode("latin-1")
    assert 'filename="chat-export.pdf"' in cd
    assert "filename*=UTF-8''" in cd
    # Persian chars must NOT appear literally in the latin-1 part.
    assert "تحلیل" not in cd


def test_content_disposition_empty_title_fallback():
    cd = build_pdf_content_disposition("")
    assert 'filename="chat-export.pdf"' in cd


def test_content_disposition_strips_path_separators():
    cd = build_pdf_content_disposition("a/b\\c:d")
    assert 'filename="abcd.pdf"' in cd
