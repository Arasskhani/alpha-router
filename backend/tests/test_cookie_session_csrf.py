"""HttpOnly session cookie and double-submit CSRF regression tests."""

from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.csrf_protection import CsrfProtectionMiddleware, origin_allowed
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


def test_private_http_origins_allowed_for_login(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_CSRF", "true")
    get_settings.cache_clear()
    client = TestClient(_app())

    for origin in (
        "http://10.1.2.3:8080",
        "http://172.16.5.10",
        "http://192.168.1.50:8080",
    ):
        assert client.post("/api/auth/login", headers={"Origin": origin}).status_code == 200, origin

    # Public / non-RFC1918 HTTP Origins remain rejected.
    assert (
        client.post(
            "/api/auth/login",
            headers={"Origin": "http://8.8.8.8:8080"},
        ).status_code
        == 403
    )
    # HTTPS from private IP is not covered by the LAN-HTTP exception.
    assert (
        client.post(
            "/api/auth/login",
            headers={"Origin": "https://192.168.1.50:8080"},
        ).status_code
        == 403
    )
    get_settings.cache_clear()


def test_origin_allowed_helper_private_ranges() -> None:
    assert origin_allowed("http://10.0.0.1:8080")
    assert origin_allowed("http://172.31.255.255")
    assert origin_allowed("http://192.168.0.1")
    assert not origin_allowed("http://172.15.0.1")  # outside 172.16/12
    assert not origin_allowed("http://11.0.0.1")
    assert not origin_allowed("https://10.0.0.1")
    assert not origin_allowed("http://evil.example")


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


def _request(url: str, origin: str) -> Request:
    parsed = urlsplit(url)
    host = parsed.netloc.encode("ascii")
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": parsed.scheme,
            "path": parsed.path or "/",
            "raw_path": (parsed.path or "/").encode(),
            "query_string": b"",
            "headers": [(b"host", host), (b"origin", origin.encode("ascii"))],
            "server": (parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)),
            "client": ("192.168.1.20", 50000),
        }
    )


def test_production_private_http_session_cookie_is_not_secure(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    request = _request("http://192.168.1.50:8080/api/auth/login", "http://192.168.1.50:8080")

    response = Response()
    set_session_cookies(response, access_token="jwt", request=request)
    headers = response.headers.getlist("set-cookie")
    assert all("Secure" not in value for value in headers)

    cleared = Response()
    clear_session_cookies(cleared, request=request)
    assert all("Secure" not in value for value in cleared.headers.getlist("set-cookie"))
    get_settings.cache_clear()


def test_production_cookie_remains_secure_outside_exact_private_http_origin(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    get_settings.cache_clear()
    requests = (
        _request("http://8.8.8.8:8080/api/auth/login", "http://8.8.8.8:8080"),
        _request("https://192.168.1.50:8080/api/auth/login", "https://192.168.1.50:8080"),
        _request("http://192.168.1.50:8080/api/auth/login", "http://192.168.1.51:8080"),
    )
    for request in requests:
        response = Response()
        set_session_cookies(response, access_token="jwt", request=request)
        assert all("Secure" in value for value in response.headers.getlist("set-cookie"))
    get_settings.cache_clear()
