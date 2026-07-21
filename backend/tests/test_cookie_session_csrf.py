"""HttpOnly session cookie and double-submit CSRF regression tests."""

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.csrf_protection import CsrfProtectionMiddleware
from app.services.session_cookie import clear_session_cookies, set_session_cookies


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CsrfProtectionMiddleware)

    @app.post("/api/mutate")
    async def mutate():
        return {"ok": True}

    @app.post("/v1/chat/completions")
    async def gateway():
        return {"ok": True}

    @app.post("/api/auth/login")
    async def login():
        return {"ok": True}

    return app


def test_cookie_authenticated_mutations_require_matching_csrf(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_CSRF", "true")
    get_settings.cache_clear()
    client = TestClient(_app())
    client.cookies.set("alpha_router_session", "jwt")
    client.cookies.set("alpha_router_csrf", "csrf-token")

    assert client.post("/api/mutate").status_code == 403
    assert (
        client.post(
            "/api/mutate",
            headers={"X-CSRF-Token": "wrong"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/mutate",
            headers={
                "X-CSRF-Token": "csrf-token",
                "Origin": "http://127.0.0.1:8080",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/mutate",
            headers={
                "X-CSRF-Token": "csrf-token",
                "Origin": "https://evil.example",
            },
        ).status_code
        == 403
    )
    get_settings.cache_clear()


def test_v1_requests_are_csrf_exempt(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_CSRF", "true")
    monkeypatch.setenv("ALLOW_LEGACY_BEARER_AUTH", "false")
    get_settings.cache_clear()
    client = TestClient(_app())
    assert client.post("/v1/chat/completions").status_code == 200
    assert (
        client.post(
            "/api/auth/login",
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    get_settings.cache_clear()


def test_legacy_bearer_csrf_bypass_requires_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_CSRF", "true")
    monkeypatch.setenv("ALLOW_LEGACY_BEARER_AUTH", "true")
    get_settings.cache_clear()
    client = TestClient(_app())
    assert (
        client.post(
            "/api/mutate",
            headers={"Authorization": "Bearer legacy-jwt"},
        ).status_code
        == 200
    )
    get_settings.cache_clear()


def test_session_cookie_attributes_and_clear(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    response = Response()
    csrf = set_session_cookies(response, access_token="jwt")
    headers = response.headers.getlist("set-cookie")
    session = next(value for value in headers if value.startswith("alpha_router_session="))
    csrf_header = next(value for value in headers if value.startswith("alpha_router_csrf="))
    assert csrf
    assert "HttpOnly" in session
    assert "Secure" in session
    assert "SameSite=lax" in session
    assert "Path=/api" in session
    assert "HttpOnly" not in csrf_header
    assert "Secure" in csrf_header

    cleared = Response()
    clear_session_cookies(cleared)
    delete_headers = cleared.headers.getlist("set-cookie")
    assert len(delete_headers) == 2
    assert all("Max-Age=0" in value for value in delete_headers)
    get_settings.cache_clear()
