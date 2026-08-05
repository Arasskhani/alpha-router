"""Detect client application name from OpenRouter-style attribution headers."""

from urllib.parse import urlparse

from starlette.requests import Request

from app.branding import CHAT_CLIENT_APP

_REFERRER_HOST_APPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("kilocode.ai", "kilo.ai"), "Kilo Code"),
    (("openwebui.com", "open-webui", "openwebui"), "Open WebUI"),
    (("cursor.com", "cursor.sh"), "Cursor"),
    (("continue.dev",), "Continue"),
    (("cline.bot", "cline.dev"), "Cline"),
    (("roo.ai", "roocode.com"), "Roo Code"),
)


def _app_from_referer(referer: str) -> str | None:
    lower = referer.lower()
    for hosts, label in _REFERRER_HOST_APPS:
        if any(h in lower for h in hosts):
            return label
    return None


def detect_client_app(request: Request) -> str | None:
    """
    Resolve display name for the App column (OpenRouter-compatible).
    Priority: X-OpenRouter-Title / X-Title, then Referer mapping, then User-Agent heuristics.
    """
    headers = request.headers
    for key in ("x-openrouter-title", "x-title"):
        title = (headers.get(key) or "").strip()
        if title:
            return title[:128]

    referer = (headers.get("http-referer") or headers.get("referer") or "").strip()
    if referer:
        mapped = _app_from_referer(referer)
        if mapped:
            return mapped
        lower = referer.lower()
        if "/admin/chat" in lower or (lower.rstrip("/").endswith("/chat") and "localhost" in lower):
            return CHAT_CLIENT_APP
        if "localhost" in lower or "127.0.0.1" in lower:
            return referer[:128]
        try:
            parsed = urlparse(referer if "://" in referer else f"https://{referer}")
            if parsed.netloc:
                return parsed.netloc[:128]
        except Exception:
            pass
        return referer[:128]

    ua = (headers.get("user-agent") or "").lower()
    if "kilocode" in ua or "kilo code" in ua or ("kilo" in ua and "code" in ua):
        return "Kilo Code"
    if "open-webui" in ua or "openwebui" in ua:
        return "Open WebUI"
    if "litellm" in ua:
        return "liteLLM"
    if "cursor" in ua:
        return "Cursor"
    return None
