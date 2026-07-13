"""Browser session and double-submit CSRF cookie helpers."""

from __future__ import annotations

import secrets

from fastapi import Response

from app.config import get_settings


def _secure() -> bool:
    return get_settings().environment.lower() == "production"


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
) -> str:
    settings = get_settings()
    csrf = csrf_token or new_csrf_token()
    max_age = max(300, int(settings.jwt_expire_minutes) * 60)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=access_token,
        httponly=True,
        secure=_secure(),
        samesite="lax",
        path="/api",
        max_age=max_age,
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf,
        httponly=False,
        secure=_secure(),
        samesite="lax",
        path="/",
        max_age=max_age,
    )
    return csrf


def clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/api",
        secure=_secure(),
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path="/",
        secure=_secure(),
        httponly=False,
        samesite="lax",
    )
