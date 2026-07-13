"""Browser security headers with staged CSP and HSTS rollout controls."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def _is_https_request(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",", 1)[0].strip().lower() == "https"


def build_security_headers(
    settings: Any,
    *,
    request_is_https: bool,
) -> dict[str, str]:
    headers = dict(BASE_SECURITY_HEADERS)
    report_only = (getattr(settings, "content_security_policy_report_only", "") or "").strip()
    if report_only:
        headers["Content-Security-Policy-Report-Only"] = report_only
    enforced = (getattr(settings, "content_security_policy", "") or "").strip()
    if enforced:
        headers["Content-Security-Policy"] = enforced

    if (
        getattr(settings, "enable_hsts", False)
        and getattr(settings, "environment", "development") == "production"
        and request_is_https
    ):
        max_age = max(0, int(getattr(settings, "hsts_max_age_seconds", 300)))
        value = f"max-age={max_age}"
        if getattr(settings, "hsts_include_subdomains", False):
            value += "; includeSubDomains"
        headers["Strict-Transport-Security"] = value
    return headers


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = build_security_headers(
            get_settings(),
            request_is_https=_is_https_request(request),
        )
        for key, value in headers.items():
            response.headers.setdefault(key, value)
        return response
