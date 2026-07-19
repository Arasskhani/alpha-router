"""Lock OpenAPI docs/redoc/openapi.json to Super Admin when opted in.

Phase 9. The guard activates when ``openapi_admin_only`` is true. In development
the flag defaults to false so docs stay open; in production the startup guard
flags a false value, so operators must set ``OPENAPI_ADMIN_ONLY=true`` and the
docs paths then require an authenticated Super Admin session. Everyone else
gets a 404 so the endpoint's existence is not leaked. Cookie and legacy Bearer
auth are both accepted to match ``get_current_user``.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.core.security import decode_access_token
from app.database import AsyncSessionLocal
from app.models.user import User
from app.services.rbac import user_has_super_admin_access
from app.services.user_role_service import get_user_role_slugs
from app.services.observability import increment

_DOCS_PATHS = frozenset(
    {
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
    }
)


def is_docs_path(path: str) -> bool:
    if not path or path == "/":
        return False
    return path.rstrip("/") in _DOCS_PATHS


def _extract_token(request: Request) -> str | None:
    settings = get_settings()
    if settings.enable_cookie_auth:
        cookie = request.cookies.get(settings.session_cookie_name)
        if cookie:
            return cookie
    if settings.allow_legacy_bearer_auth:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            return header.split(" ", 1)[1].strip() or None
    return None


async def request_has_super_admin(request: Request) -> bool:
    """Resolve the request's user and return True only for an active Super Admin."""
    token = _extract_token(request)
    if not token:
        return False
    payload = decode_access_token(token)
    if not payload:
        return False
    username = payload.get("sub")
    if not username:
        return False
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalars().first()
        if user is None or user.deleted_at is not None:
            return False
        jwt_ver = int(payload.get("ver", 0) or 0)
        if jwt_ver < int(user.token_version or 0):
            return False
        slugs = await get_user_role_slugs(db, user.id)
        return user_has_super_admin_access(slugs)


class OpenApiDocsGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if settings.openapi_admin_only and is_docs_path(request.url.path):
            if not await request_has_super_admin(request):
                increment("docs_denied")
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return await call_next(request)
