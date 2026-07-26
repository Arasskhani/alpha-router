"""Browser session and double-submit CSRF cookie helpers."""

from __future__ import annotations

import secrets
import ipaddress
from urllib.parse import urlsplit

from fastapi import Request, Response

from app.config import get_settings


_PRIVATE_HTTP_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def _private_ip(value: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(value or "")
    except ValueError:
        return False
    return any(ip in network for network in _PRIVATE_HTTP_NETWORKS)


def _private_http_request(request: Request | None) -> bool:
    """Allow insecure cookies only for same-origin HTTP on an RFC1918 IP."""
    if request is None:
        return False
    origin = urlsplit((request.headers.get("origin") or "").strip())
    request_host = request.url.hostname
    return bool(
        request.url.scheme == "http"
        and origin.scheme == "http"
        and origin.hostname == request_host
        and _private_ip(request_host)
        and origin.username is None
        and origin.password is None
    )


def _secure(request: Request | None = None) -> bool:
    production = get_settings().environment.lower() == "production"
    return production and not _private_http_request(request)


def session_cookie_name() -> str:
    return get_settings().session_cookie_name


def csrf_cookie_name() -> str:
    return get_settings().csrf_cookie_name


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_session_cookies(
    response: Response,
    *,
    access_token: str,
    csrf_token: str | None = None,
    request: Request | None = None,
) -> str:
    settings = get_settings()
    csrf = csrf_token or new_csrf_token()
    max_age = max(300, int(settings.jwt_expire_minutes) * 60)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=access_token,
        httponly=True,
        secure=_secure(request),
        samesite="lax",
        path="/api",
        max_age=max_age,
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf,
        httponly=False,
        secure=_secure(request),
        samesite="lax",
        path="/",
        max_age=max_age,
    )
    return csrf


def clear_session_cookies(response: Response, *, request: Request | None = None) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/api",
        secure=_secure(request),
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path="/",
        secure=_secure(request),
        httponly=False,
        samesite="lax",
    )
