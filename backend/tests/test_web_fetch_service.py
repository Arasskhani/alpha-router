"""Web Fetch: which links are read, and how a page becomes text a model can use."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services import chat_tools_service
from app.services.web_fetch_service import (
    extract_urls,
    fetch_all,
    html_to_text,
    latest_user_text,
    page_from_bytes,
    trim_url,
    typed_text,
)


class TestTheLinks:
    @pytest.mark.parametrize(
        ("text", "urls"),
        [
            ("See https://example.com/page.", ["https://example.com/page"]),
            ("این را بخوان https://example.com/a، و خلاصه کن", ["https://example.com/a"]),
            ("آیا https://example.com/b؟", ["https://example.com/b"]),
            (
                "(https://en.wikipedia.org/wiki/Python_(programming_language))",
                ["https://en.wikipedia.org/wiki/Python_(programming_language)"],
            ),
            ("link: https://x.com/a, https://y.com/b!", ["https://x.com/a", "https://y.com/b"]),
            ("«https://x.com/q?a=1&b=2»", ["https://x.com/q?a=1&b=2"]),
            ("twice https://x.com and https://x.com.", ["https://x.com"]),
            ("ftp://x.com and javascript:alert(1)", []),
        ],
    )
    def test_a_link_ends_where_the_sentence_does(self, text, urls):
        assert extract_urls(text) == urls

    def test_at_most_three(self):
        text = " ".join(f"https://s{i}.example" for i in range(6))
        assert extract_urls(text) == ["https://s0.example", "https://s1.example", "https://s2.example"]

    def test_trim_keeps_brackets_it_opens(self):
        assert trim_url("https://a.example/x_(y))") == "https://a.example/x_(y)"
        assert trim_url("https://a.example/x].") == "https://a.example/x"


class TestWhatThePersonTyped:
    def test_the_text_of_an_attached_file_is_not_theirs(self):
        content = "Summarise this please\n\n--- report.pdf ---\nSee https://inside-the-file.example for more"
        assert typed_text(content) == "Summarise this please"
        assert extract_urls(typed_text(content)) == []

    def test_notes_about_attachments_are_dropped(self):
        content = 'what is this?\n\n[Attached file "x.bin" (2 KB, binary): no text was extracted.]'
        assert typed_text(content) == "what is this?"

    def test_the_latest_message_counts_even_with_an_image(self):
        messages = [
            {"role": "user", "content": "what is the weather in Paris?"},
            {"role": "assistant", "content": "..."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "search for this building https://img.example/a"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
                ],
            },
        ]
        assert latest_user_text(messages) == "search for this building https://img.example/a"

    def test_no_user_message_is_no_text(self):
        assert latest_user_text([{"role": "system", "content": "rules"}]) == ""


class TestHtmlToText:
    def test_scripts_styles_and_chrome_are_not_page_text(self):
        html = (
            "<html><head><title>My page</title><style>body{color:red}</style><script>var a=1;track()</script></head>"
            "<body><nav>Home Menu</nav><p>Real article text</p><noscript>enable js</noscript>"
            "<svg><text>icon</text></svg></body></html>"
        )
        title, text = html_to_text(html)
        assert title == "My page"
        assert "Real article text" in text
        for noise in ("color:red", "track()", "enable js", "icon"):
            assert noise not in text

    def test_the_main_content_is_preferred_when_marked(self):
        article = "Paragraph of the story. " * 20
        html = f"<body><nav>Menu</nav><main><h1>Headline</h1><p>{article}</p><ul><li>one</li><li>two</li></ul></main><footer>Copyright</footer></body>"
        _, text = html_to_text(html)
        assert text.startswith("# Headline")
        assert "- one\n- two" in text
        assert "Menu" not in text and "Copyright" not in text

    def test_a_stub_main_falls_back_to_the_whole_body(self):
        _, text = html_to_text("<body><main>Accept cookies</main><div>The real content is here.</div></body>")
        assert "The real content is here." in text

    def test_broken_html_still_gives_its_text(self):
        _, text = html_to_text("<div><p>one<p>two</div><b>three")
        assert "one" in text and "two" in text and "three" in text


class TestBytesToText:
    async def test_the_page_s_charset_is_read_from_the_header_then_the_meta_tag(self):
        arabic = "مرحبا بالعالم"
        raw = f"<html><body><p>{arabic}</p></body></html>".encode("cp1256")
        page = await page_from_bytes("https://a.example", raw, "text/html; charset=windows-1256")
        assert arabic in page.text
        meta = f'<html><head><meta charset="windows-1256"></head><body><p>{arabic}</p></body></html>'.encode("cp1256")
        assert arabic in (await page_from_bytes("https://a.example", meta, "text/html")).text

    async def test_an_image_is_said_to_be_one(self):
        page = await page_from_bytes("https://a.example/x.png", b"\x89PNG\r\n", "image/png")
        assert page.text == "(Not a text page: image/png.)"

    async def test_a_pdf_is_read_as_a_document(self, monkeypatch):
        async def extract(raw, name):
            return f"text of {name}"

        monkeypatch.setattr("app.services.attachment_extract.extract_document_text_bounded", extract)
        page = await page_from_bytes("https://a.example/files/report", b"%PDF-1.7 ...", "application/octet-stream")
        assert page.text == "text of report.pdf"

    async def test_plain_text_passes_through(self):
        page = await page_from_bytes("https://a.example/r.txt", b"  hello  ", "text/plain")
        assert page.text == "hello"


class TestFetching:
    async def test_a_large_page_is_cut_not_refused(self, monkeypatch):
        from app.services.bounded_io import bounded_get_bytes_truncating

        monkeypatch.setattr("app.services.ssrf_guard.assert_url_safe", lambda url: None)
        monkeypatch.setattr("app.services.ssrf_guard.assert_response_target_safe", lambda response: None)
        body = b"<html><body>" + b"<p>word</p>" * 50_000 + b"</body></html>"
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, content=body, headers={"content-type": "text/html; charset=utf-8"})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            raw, ctype, truncated = await bounded_get_bytes_truncating(client, "https://big.example", max_bytes=100_000)
        assert truncated is True and len(raw) == 100_000
        assert ctype == "text/html; charset=utf-8"

    async def test_links_are_read_at_the_same_time_within_one_limit(self):
        started: list[str] = []

        async def fetch(url):
            started.append(url)
            await asyncio.sleep(0.2 if "slow" in url else 0.01)
            if "bad" in url:
                raise RuntimeError("refused")
            return url.upper()

        results = await fetch_all(
            ["https://a.example", "https://bad.example", "https://slow.example"], fetch, timeout=0.1
        )
        assert len(started) == 3
        assert results[0] == "HTTPS://A.EXAMPLE"
        assert isinstance(results[1], RuntimeError)
        assert isinstance(results[2], TimeoutError)

    async def test_the_model_is_told_which_page_could_not_be_read(self, monkeypatch):
        async def fake(url, **kwargs):
            if "down" in url:
                raise RuntimeError("Connection refused")
            return f"Title: Up\n\ncontent of {url}"

        monkeypatch.setattr(chat_tools_service, "fetch_url_text", fake)
        messages = [{"role": "user", "content": "compare https://up.example and https://down.example."}]
        context = await chat_tools_service.web_fetch_context(messages)
        assert 'source="https://up.example"' in context and "content of https://up.example" in context
        assert 'source="https://down.example"' in context
        assert "could not be read: Connection refused" in context


class TestAHostilePage:
    def test_endless_unclosed_tags_are_read_in_linear_time(self):
        import time

        html = "<div>" * 100_000 + "deep text" + "</a>" * 100_000
        started = time.perf_counter()
        _, text = html_to_text(html)
        assert time.perf_counter() - started < 5
        assert "deep text" in text

    async def test_a_page_is_read_off_the_event_loop(self, monkeypatch):
        import threading

        seen: list[bool] = []
        real = html_to_text

        def spy(html):
            seen.append(threading.current_thread() is threading.main_thread())
            return real(html)

        monkeypatch.setattr("app.services.web_fetch_service.html_to_text", spy)
        page = await page_from_bytes("https://a.example", b"<html><body><p>hi</p></body></html>", "text/html")
        assert page.text == "hi"
        assert seen == [False]
