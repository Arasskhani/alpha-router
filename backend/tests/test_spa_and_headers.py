"""Phase 5: SPA fallback path-traversal containment + API 404 masking guard.

Rather than booting the full Alpha Router app (which requires DB / S3 / scheduler),
these tests build a minimal FastAPI app that mirrors the spa_fallback route and
the SecurityHeadersMiddleware logic, and assert the security properties
directly. This keeps the test hermetic and fast while validating the exact
patterns used in app/main.py.
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient


def _build_spa_app(dist_dir: Path) -> FastAPI:
    app = FastAPI()

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        _BASE_HEADERS = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
            "Cross-Origin-Opener-Policy": "same-origin",
        }

        async def dispatch(self, request, call_next):
            response = await call_next(request)
            for k, v in self._BASE_HEADERS.items():
                response.headers.setdefault(k, v)
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    if dist_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith(("api/", "v1/", "health", "docs", "openapi.json", "redoc")):
                return JSONResponse(status_code=404, content={"detail": "Not Found", "path": f"/{full_path}"})
            dist_root = dist_dir.resolve()
            candidate = (dist_dir / full_path).resolve()
            try:
                candidate.relative_to(dist_root)
            except ValueError:
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            if candidate.is_file():
                return FileResponse(candidate)
            index = dist_dir / "index.html"
            if index.is_file():
                return FileResponse(index)
            return HTMLResponse("not found", status_code=404)

    return app


@pytest.fixture()
def spa_app(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!DOCTYPE html><html><body>SPA</body></html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1);", encoding="utf-8")
    # a real file outside dist to attempt traversal toward
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    return _build_spa_app(dist), dist, secret


def test_spa_serves_index_for_client_route(spa_app):
    app, dist, _ = spa_app
    client = TestClient(app)
    r = client.get("/some/client/route")
    assert r.status_code == 200
    assert "SPA" in r.text


def test_spa_serves_real_asset(spa_app):
    app, dist, _ = spa_app
    client = TestClient(app)
    r = client.get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


def test_spa_path_traversal_blocked(spa_app):
    app, dist, secret = spa_app
    client = TestClient(app)
    # Attempt to escape dist via ../ to reach the secret file.
    r = client.get("../../secret.txt")
    # Depending on client normalization, the URL may be sent as-is or cleaned.
    # Either way, it must never return the secret content.
    assert b"TOPSECRET" not in r.content
    # Also try an absolute-ish traversal that survives path normalization.
    r2 = client.get("/assets/../../../secret.txt")
    assert b"TOPSECRET" not in r2.content


def test_api_unmatched_returns_json_not_spa(spa_app):
    app, dist, _ = spa_app
    client = TestClient(app)
    r = client.get("/api/nonexistent/endpoint")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert "Not Found" in r.text
    # Must NOT return the HTML SPA shell.
    assert "<html" not in r.text.lower()


def test_v1_unmatched_returns_json(spa_app):
    app, dist, _ = spa_app
    client = TestClient(app)
    r = client.get("/v1/typo")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_security_headers_present_on_all_responses(spa_app):
    app, dist, _ = spa_app
    client = TestClient(app)
    for path in ("/health", "/", "/assets/app.js"):
        r = client.get(path)
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "camera=()" in r.headers.get("Permissions-Policy", "")
