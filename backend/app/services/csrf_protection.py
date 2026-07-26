"""Header-only CSRF protection for cookie-authenticated browser requests."""

from __future__ import annotations

import hmac
import ipaddress
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.observability import increment

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Origin still checked (same-site SPA posts).
EXEMPT_PATHS = frozenset(
    {
        "/api/auth/login",
        "/api/auth/login/2fa",
        "/api/auth/saml/exchange",
        "/api/auth/sso/exchange",
    }
)
# Cross-origin IdP form POST — skip Origin + CSRF header checks entirely.
FULL_EXEMPT_PATHS = frozenset(
    {
        "/api/auth/saml/acs",
    }
)

# RFC1918 private ranges — HTTP Origins from these hosts are allowed for LAN access.
_PRIVATE_HTTP_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def _normalized_origin(value: str) -> str:
    parsed = urlsplit((value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def allowed_origins() -> set[str]:
    settings = get_settings()
    configured = {
        _normalized_origin(settings.frontend_url),
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    }
    return {origin for origin in configured if origin}


def _is_private_http_origin(origin: str) -> bool:
    """True for http://<RFC1918-IP>[:port] (LAN lab / internal HTTP access)."""
    parsed = urlsplit((origin or "").strip())
    if (
        parsed.scheme.lower() != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return False
    return any(ip in network for network in _PRIVATE_HTTP_NETWORKS)


def origin_allowed(origin: str) -> bool:
    normalized = _normalized_origin(origin)
    if not normalized:
        return False
    if normalized in allowed_origins():
        return True
    return _is_private_http_origin(normalized)


class CsrfProtectionMiddleware:
    """Require cookie/header equality without reading request bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        method = str(scope.get("method") or "").upper()
        path = str(scope.get("path") or "")
        if (
            not settings.enable_csrf
            or method not in UNSAFE_METHODS
            or not path.startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if path in FULL_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        if path in EXEMPT_PATHS:
            origin = request.headers.get("origin")
            if origin and not origin_allowed(origin):
                increment("csrf_failure")
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed"},
                )
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        session_token = request.cookies.get(settings.session_cookie_name)
        if not session_token:
            # Legacy Bearer and unauthenticated requests remain compatible.
            # Route authentication still decides whether they are allowed.
            await self.app(scope, receive, send)
            return

        origin = request.headers.get("origin")
        if origin and not origin_allowed(origin):
            increment("csrf_failure")
            response = JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
            await response(scope, receive, send)
            return

        cookie_token = request.cookies.get(settings.csrf_cookie_name) or ""
        header_token = request.headers.get(settings.csrf_header_name) or ""
        if (
            not cookie_token
            or not header_token
            or not hmac.compare_digest(cookie_token, header_token)
        ):
            increment("csrf_failure")
            response = JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
