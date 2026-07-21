"""Shared validation for auth redirect / public URLs."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.config import get_settings


def _validate_web_origin_url(value: str, *, label: str) -> str:
    env = getattr(get_settings(), "environment", "development")
    url = (value or "").strip()
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError(f"Invalid {label}") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Invalid {label}")
    if env == "production" and parsed.scheme != "https":
        raise ValueError(f"{label} must be HTTPS in production")
    return url.rstrip("/")


def validate_frontend_url(frontend_url: str) -> str:
    """Validate the fixed post-auth destination used by backend redirects."""
    return _validate_web_origin_url(frontend_url, label="Frontend URL")


def public_api_base() -> str:
    """Base URL used for ACS / SP metadata absolute URLs."""
    settings = get_settings()
    base = (settings.api_public_url or settings.frontend_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("API_PUBLIC_URL (or FRONTEND_URL) must be configured for SAML")
    return base
