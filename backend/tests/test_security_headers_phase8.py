"""Phase 8 CSP Report-Only and staged HSTS regression tests."""

from types import SimpleNamespace

from app.services.security_headers import build_security_headers


def _settings(**overrides):
    values = {
        "content_security_policy_report_only": "default-src 'self'; object-src 'none'",
        "content_security_policy": "",
        "enable_hsts": False,
        "environment": "development",
        "hsts_max_age_seconds": 300,
        "hsts_include_subdomains": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_report_only_csp_is_emitted_without_enforcement() -> None:
    headers = build_security_headers(_settings(), request_is_https=False)
    assert headers["Content-Security-Policy-Report-Only"] == ("default-src 'self'; object-src 'none'")
    assert "Content-Security-Policy" not in headers
    assert "Strict-Transport-Security" not in headers
    assert headers["X-Frame-Options"] == "DENY"
    assert "microphone=(self)" in headers["Permissions-Policy"]


def test_enforced_and_report_only_csp_are_independent() -> None:
    headers = build_security_headers(
        _settings(content_security_policy="default-src 'self'"),
        request_is_https=True,
    )
    assert "Content-Security-Policy-Report-Only" in headers
    assert headers["Content-Security-Policy"] == "default-src 'self'"


def test_hsts_requires_production_https_and_starts_conservatively() -> None:
    enabled = _settings(enable_hsts=True, environment="production")
    assert "Strict-Transport-Security" not in build_security_headers(enabled, request_is_https=False)
    headers = build_security_headers(enabled, request_is_https=True)
    assert headers["Strict-Transport-Security"] == "max-age=300"


def test_hsts_subdomains_must_be_explicitly_enabled() -> None:
    headers = build_security_headers(
        _settings(
            enable_hsts=True,
            environment="production",
            hsts_max_age_seconds=86400,
            hsts_include_subdomains=True,
        ),
        request_is_https=True,
    )
    assert headers["Strict-Transport-Security"] == "max-age=86400; includeSubDomains"
