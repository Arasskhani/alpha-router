"""ASGI middleware that optionally restricts /admin and /api/admin by client IP."""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.services.admin_ip_allowlist_service import (
    get_restriction_state,
    ip_matches_allowlist,
    peek_restriction_state,
)
from app.services.client_ip import resolve_client_ip
from app.services.observability import increment

logger = logging.getLogger(__name__)

ADMIN_FORBIDDEN_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Access denied</title></head>
<body style="font-family:sans-serif;padding:2rem;max-width:40rem">
<h1>Access denied</h1>
<p>Access from your network is not permitted.</p>
</body>
</html>
"""


def path_is_admin_surface(path: str) -> bool:
    return path == "/admin" or path.startswith("/admin/") or path == "/api/admin" or path.startswith("/api/admin/")


class AdminIpGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if getattr(settings, "admin_ip_restriction_disabled", False):
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if not path_is_admin_surface(path):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        client_ip = resolve_client_ip(request)
        state = peek_restriction_state()
        if state is None:
            try:
                async with AsyncSessionLocal() as db:
                    state = await get_restriction_state(db)
            except Exception:
                logger.exception("admin IP allowlist cache refresh failed")
                state = peek_restriction_state(allow_stale=True)
                if state is None:
                    await self.app(scope, receive, send)
                    return

        if state.mode == "off":
            await self.app(scope, receive, send)
            return

        allowed = ip_matches_allowlist(
            client_ip,
            state.entries,
            allow_loopback=state.allow_loopback,
        )
        if allowed:
            await self.app(scope, receive, send)
            return

        increment("admin_ip_denied")
        logger.warning(
            "admin_ip_denied mode=%s ip=%s path=%s",
            state.mode,
            client_ip or "unknown",
            path,
        )
        if state.mode == "monitor":
            await self.app(scope, receive, send)
            return

        if path.startswith("/api/"):
            response = JSONResponse(
                status_code=403,
                content={"detail": "Admin access is restricted to allowed IP addresses"},
            )
        else:
            response = HTMLResponse(ADMIN_FORBIDDEN_HTML, status_code=403)
        await response(scope, receive, send)
