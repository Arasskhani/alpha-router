"""Render chat assistant content to PDF via headless Chromium (Playwright).

Security model:
- The caller is an authenticated user exporting their own chat content.
- Raw markdown is HTML-escaped (``<`` and ``&``) before parsing, so no
  user/model-supplied HTML tags can ever form elements in the browser
  context (no XSS via markdown).
- JavaScript is disabled in the Playwright context.
- All sub-resource requests are aborted to prevent SSRF (e.g. an
  ``<img src="http://internal">`` injected via model output cannot be
  fetched).
- No content length cap is enforced (per product decision); the content
  is the user's own and the render runs in a one-shot headless context.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Cap concurrent headless Chromium renders so a burst of export requests cannot
# exhaust host CPU/RAM. This limits concurrency (resource protection), NOT
# content length — there is deliberately no size cap on the exported content.
_RENDER_SEMAPHORE = asyncio.Semaphore(2)


class ChatExportError(Exception):
    """Chat PDF render failed."""


def build_pdf_content_disposition(title: str | None) -> str:
    """Build a Content-Disposition header for a PDF download.

    HTTP headers are latin-1, so an ASCII fallback ``filename`` is provided
    alongside a RFC 5987 ``filename*`` UTF-8 value so browsers can display the
    original (e.g. Persian) title.
    """
    return build_download_content_disposition(title, "pdf")


def build_download_content_disposition(title: str | None, ext: str) -> str:
    """Build a Content-Disposition header for a download with the given extension."""
    from urllib.parse import quote

    ext = (ext or "").lstrip(".").lower() or "bin"
    raw_title = (title or "chat-export").strip() or "chat-export"
    ascii_name = "".join(c for c in raw_title if (c.isascii() and c.isalnum()) or c in "-_") or "chat-export"
    ascii_name = ascii_name[:60]
    utf8_name = quote(raw_title[:120], safe="")
    return f"attachment; filename=\"{ascii_name}.{ext}\"; filename*=UTF-8''{utf8_name}.{ext}"


def _markdown_to_html(markdown_text: str) -> str:
    try:
        import markdown as md  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise ChatExportError("markdown library not installed. Run: pip install markdown") from exc
    # Escape angle brackets and ampersands so no raw HTML from the user/model
    # can form tags. Markdown syntax (#, *, |, `, >, -) is unaffected.
    escaped = markdown_text.replace("&", "&amp;").replace("<", "&lt;")
    return md.markdown(
        escaped,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
        output_format="html5",
    )


def _build_html_document(*, title: str, body_html: str) -> str:
    safe_title = html.escape(title or "Chat export")
    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8" />
<title>{safe_title}</title>
<style>
  @page {{ margin: 14mm 12mm; }}
  html, body {{
    margin: 0; padding: 0;
    font-family: "Vazirmatn", "Segoe UI", Tahoma, "Iran Sans", Arial, sans-serif;
    font-size: 12pt; line-height: 1.7; color: #1f2328; background: #fff;
  }}
  h1, h2, h3, h4 {{ line-height: 1.3; margin: 1em 0 0.5em; color: #0d1117; }}
  h1 {{ font-size: 1.6em; border-bottom: 1px solid #d0d7de; padding-bottom: 0.3em; }}
  h2 {{ font-size: 1.35em; }}
  h3 {{ font-size: 1.15em; }}
  p {{ margin: 0.6em 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 10.5pt; }}
  th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; text-align: right; }}
  th {{ background: #f6f8fa; font-weight: 700; }}
  tr:nth-child(even) td {{ background: #fbfcfd; }}
  pre {{
    background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
    padding: 10px 12px; overflow: auto; direction: ltr; text-align: left;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 10pt; line-height: 1.5; white-space: pre-wrap; word-break: break-word;
  }}
  code {{ font-family: "Cascadia Code", "Consolas", "Courier New", monospace; }}
  pre code {{ background: none; padding: 0; }}
  :not(pre) > code {{
    background: #eff1f3; padding: 2px 5px; border-radius: 4px; font-size: 0.92em;
  }}
  blockquote {{
    border-right: 3px solid #d0d7de; margin: 0.8em 0; padding: 0.2em 1em;
    color: #57606a; background: #f6f8fa;
  }}
  ul, ol {{ padding-right: 1.6em; margin: 0.6em 0; }}
  li {{ margin: 0.25em 0; }}
  a {{ color: #0969da; text-decoration: none; }}
  hr {{ border: none; border-top: 1px solid #d0d7de; margin: 1.4em 0; }}
  .chat-export-title {{
    font-size: 0.85em; color: #57606a; margin-bottom: 1.2em;
    border-bottom: 1px solid #d0d7de; padding-bottom: 0.5em;
  }}
</style>
</head>
<body>
  <div class="chat-export-title">{safe_title}</div>
{body_html}
</body>
</html>"""


def _launch_browser(playwright):
    channel = (os.environ.get("PLAYWRIGHT_BROWSER_CHANNEL") or "").strip()
    exe = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH", "").strip()
    # --no-sandbox is required because the runtime container drops all
    # capabilities and sets no-new-privileges (the Chromium setuid sandbox cannot
    # initialize). --disable-gpu avoids GPU init issues in headless containers.
    launch_kwargs: dict[str, Any] = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-gpu"],
    }
    if exe:
        launch_kwargs["executable_path"] = exe
        return playwright.chromium.launch(**launch_kwargs)
    if channel and channel != "chromium":
        try:
            return playwright.chromium.launch(channel=channel, **launch_kwargs)
        except Exception as channel_exc:
            logger.warning("Playwright channel %s unavailable: %s", channel, channel_exc)
    try:
        return playwright.chromium.launch(**launch_kwargs)
    except Exception as bundled_exc:
        raise ChatExportError(
            "No Chromium browser available for PDF export. Install Chrome or run: playwright install chromium"
        ) from bundled_exc


def _render_chat_pdf_sync(*, title: str, body_html: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise ChatExportError("Playwright is not installed.") from exc

    document_html = _build_html_document(title=title, body_html=body_html)

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            # JavaScript disabled: inline scripts cannot execute.
            context = browser.new_context(
                viewport={"width": 1200, "height": 1600},
                java_script_enabled=False,
            )
            page = context.new_page()

            # Abort every sub-resource request so nothing is fetched over the
            # network (anti-SSRF: <img>/<link>/fetch pointing anywhere are blocked).
            def _abort_all(route):
                return route.abort()

            page.route("**/*", _abort_all)

            page.set_content(document_html, wait_until="load", timeout=120_000)
            page.emulate_media(media="print")
            return page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "14mm", "right": "12mm", "bottom": "14mm", "left": "12mm"},
            )
        finally:
            browser.close()


async def render_chat_pdf(*, content: str, title: str | None = None) -> bytes:
    """Render markdown ``content`` to a PDF byte string."""
    if content is None or not content.strip():
        raise ChatExportError("content must not be empty")
    body_html = _markdown_to_html(content)
    async with _RENDER_SEMAPHORE:
        return await asyncio.to_thread(
            _render_chat_pdf_sync,
            title=title or "Chat export",
            body_html=body_html,
        )
