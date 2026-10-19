"""The chat's Web Fetch: the links a person typed, read as text a model can use.

What changed from reading a page as one undifferentiated string:

- Only the person's own words are looked in for links: not the text of a
  file they attached (a document's links are not a request to open them),
  and the latest message even when it carries an image.
- A link ends where a sentence does: the full stop, comma or Persian comma
  after it, or a closing bracket it does not open, is not part of it.
- A page's scripts, styles and other machinery are dropped; its main content
  (``<main>``, ``<article>``) is preferred when it has one, and headings and
  list items keep their shape.
- The page's own character set is read (the header, then ``<meta charset>``).
- A page larger than the limit is read up to it and cut, not refused.
- A PDF is read as a document; another binary file is said to be one.
- Up to three links are read at the same time, within one overall limit.
"""

from __future__ import annotations

import asyncio
import codecs
import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

URL_RE = re.compile(r"https?://[^\s<>\[\]\"'`]+", re.IGNORECASE)
#: Characters that end a sentence or a quotation rather than a link (Latin and Persian).
_TRAILING = ".,;:!?…»«،؛؟‌'\""
#: Brackets a link may legitimately contain when it opens them (Wikipedia's "Python_(language)").
_PAIRS = {")": "(", "]": "[", "}": "{"}

#: Links read per message, and how long reading them all may take.
MAX_LINKS = 3
FETCH_ALL_TIMEOUT_S = 30.0

#: How a chat attachment is set out in a message (frontend chatAttachments.ts): the person's words come first.
_ATTACHMENT_NOTE = re.compile(r"\n\n--- [^\n]{1,300} ---\n")
_ATTACHMENT_LINE = re.compile(r"^\[(Attached file|Attached image|Attached audio|Attached video)[^\n]*\]$", re.MULTILINE)


def trim_url(raw: str) -> str:
    """A link as found in running text, without the punctuation after it or a bracket it does not open."""
    url = raw
    while url:
        last = url[-1]
        if last in _TRAILING:
            url = url[:-1]
            continue
        if last in _PAIRS and url.count(_PAIRS[last]) < url.count(last):
            url = url[:-1]
            continue
        break
    return url


def extract_urls(text: str, limit: int = MAX_LINKS) -> list[str]:
    """The distinct http(s) links in ``text``, in order, at most ``limit``."""
    found: list[str] = []
    for match in URL_RE.finditer(text or ""):
        url = trim_url(match.group(0))
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc and url not in found:
            found.append(url)
        if len(found) >= limit:
            break
    return found


def typed_text(content: Any) -> str:
    """What the person typed in a message: its text parts, without the text of files attached to it."""
    if isinstance(content, list):
        text = "\n".join(
            str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    elif isinstance(content, str):
        text = content
    else:
        return ""
    note = _ATTACHMENT_NOTE.search(text)
    if note:
        text = text[: note.start()]
    return _ATTACHMENT_LINE.sub("", text).strip()


def latest_user_text(messages: list[dict]) -> str:
    """What the person typed in their latest message - that message, whatever it carries, never an older one."""
    for message in reversed(messages):
        if message.get("role") == "user":
            return typed_text(message.get("content"))
    return ""


# --- HTML to text ---------------------------------------------------------------------------------------------

#: Elements whose content is never page text.
_SKIP = frozenset(
    {"script", "style", "noscript", "svg", "template", "iframe", "canvas", "object", "head", "button", "select"}
)
#: Elements that start a new line of text.
_BLOCKS = frozenset(
    {"p", "div", "section", "article", "main", "header", "footer", "aside", "nav", "br", "tr", "table", "ul", "ol",
     "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "figcaption", "dd", "dt", "hr", "form"}
)  # fmt: skip
_VOID = frozenset(
    {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
)
#: The page's own chrome, kept out of the main content when it is marked as such.
_CHROME = frozenset({"nav", "footer", "aside"})
#: Elements nested deeper than this are read as text without being tracked: a page of
#: endless unclosed tags cannot make the reading of it slow.
_MAX_DEPTH = 512


class _PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._skip = 0
        self._chrome = 0
        self._main = 0
        self._stack: list[str] = []
        #: How many of each tag are open: whether an end tag closes anything, without searching the stack.
        self._open: Counter[str] = Counter()
        self.all: list[str] = []
        self.main: list[str] = []

    def _emit(self, text: str) -> None:
        self.all.append(text)
        if self._main and not self._chrome:
            self.main.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in _VOID:
            if tag in ("br", "hr"):
                self._emit("\n")
            return
        if len(self._stack) >= _MAX_DEPTH:
            return
        self._stack.append(tag)
        self._open[tag] += 1
        if tag in _SKIP:
            self._skip += 1
            return
        if tag in _CHROME:
            self._chrome += 1
        if tag in ("main", "article") or dict(attrs).get("role") == "main":
            self._main += 1
        if tag in _BLOCKS:
            self._emit("\n")
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._emit("#" * int(tag[1]) + " ")
        elif tag == "li":
            self._emit("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _VOID or not self._open[tag]:
            return
        # Close up to the matching tag: unclosed children of it (an unclosed <p>) end with it. Each tag is
        # pushed and popped once, so reading a page stays linear in its size.
        while self._stack:
            open_tag = self._stack.pop()
            self._open[open_tag] -= 1
            if open_tag in _SKIP:
                self._skip = max(0, self._skip - 1)
            if open_tag in _CHROME:
                self._chrome = max(0, self._chrome - 1)
            if open_tag in ("main", "article"):
                self._main = max(0, self._main - 1)
            # A list item's end needs no line of its own: the next item starts one.
            if open_tag in _BLOCKS and open_tag != "li":
                self._emit("\n")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        if data.strip():
            self._emit(" ".join(data.split()) + (" " if data[-1:].isspace() else ""))


def _tidy(chunks: list[str]) -> str:
    text = "".join(chunks)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


#: Below this many characters a page's main element is taken for a stub (a cookie notice), not its content.
_MAIN_MIN_CHARS = 200


def html_to_text(html: str) -> tuple[str, str]:
    """The page's title and its readable text: the main content when it is marked, else the whole body."""
    parser = _PageText()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 -- a page broken past repair still gives what was read of it
        pass
    main = _tidy(parser.main)
    body = main if len(main) >= _MAIN_MIN_CHARS else _tidy(parser.all)
    return " ".join(parser.title.split()), body


# --- Bytes to text --------------------------------------------------------------------------------------------

_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.IGNORECASE)


def _charset(content_type: str, raw: bytes) -> str:
    match = re.search(r"charset\s*=\s*\"?([A-Za-z0-9_.:-]+)", content_type or "", re.IGNORECASE)
    candidates = [match.group(1)] if match else []
    meta = _META_CHARSET.search(raw[:4096])
    if meta:
        candidates.append(meta.group(1).decode("ascii", "ignore"))
    for name in candidates:
        try:
            return codecs.lookup(name).name
        except LookupError:
            continue
    return "utf-8"


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str
    text: str
    #: The page was larger than the limit and was read only up to it.
    truncated: bool = False


async def page_from_bytes(url: str, raw: bytes, content_type: str, *, truncated: bool = False) -> FetchedPage:
    """What the model is given of a response: its text, read the way its type asks."""
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime == "application/pdf" or raw[:5] == b"%PDF-":
        from app.services.attachment_extract import extract_document_text_bounded

        if truncated:
            return FetchedPage(
                url=url, title="", text="(A PDF larger than this server reads from the web; it was not read.)"
            )
        name = urlparse(url).path.rsplit("/", 1)[-1] or "document.pdf"
        text = await extract_document_text_bounded(raw, name if name.lower().endswith(".pdf") else f"{name}.pdf")
        return FetchedPage(url=url, title=name, text=text or "(The PDF holds no text that could be read.)")
    is_text = mime.startswith("text/") or mime in ("", "application/xhtml+xml", "application/xml", "application/json")
    looks_html = b"<html" in raw[:2048].lower() or b"<!doctype html" in raw[:2048].lower()
    if not is_text and not looks_html:
        return FetchedPage(url=url, title="", text=f"(Not a text page: {mime or 'unknown type'}.)")
    text = raw.decode(_charset(content_type, raw), errors="replace")
    if "html" in mime or looks_html:
        # A large page takes a moment to read: off the event loop, so other turns go on meanwhile.
        title, body = await asyncio.to_thread(html_to_text, text)
        return FetchedPage(url=url, title=title, text=body, truncated=truncated)
    return FetchedPage(url=url, title="", text=text.strip(), truncated=truncated)


async def fetch_page(
    url: str, *, max_bytes: int, check_redirect: Callable[[str], Awaitable[None]] | None = None
) -> FetchedPage:
    """Read one link through the SSRF-guarded client; raises on a refused or failed fetch."""
    from app.branding import OUTBOUND_USER_AGENT
    from app.services.bounded_io import bounded_get_bytes_truncating
    from app.services.ssrf_guard import safe_client

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Invalid URL")
    async with safe_client(
        headers={
            "User-Agent": OUTBOUND_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        }
    ) as client:
        raw, content_type, truncated = await bounded_get_bytes_truncating(
            client, url, max_bytes=max_bytes, check_redirect=check_redirect
        )
    return await page_from_bytes(url, raw, content_type, truncated=truncated)


async def fetch_all(urls: list[str], fetch: Any, *, timeout: float = FETCH_ALL_TIMEOUT_S) -> list[Any]:
    """``fetch(url)`` for each link at the same time; a link not read in time gets a TimeoutError in its place."""
    tasks = [asyncio.ensure_future(fetch(url)) for url in urls]
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    results: list[Any] = []
    for task in tasks:
        if task in pending:
            results.append(TimeoutError(f"Not read within {timeout:g} s."))
        else:
            exc = task.exception()
            results.append(exc if exc is not None else task.result())
    return results
