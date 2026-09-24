"""Cache headers on the built frontend (app/core/frontend_files.py).

index.html must be revalidated on every load, or a browser (or an installed
app) can start an old build after an upgrade whose hashed chunks are gone.
Hashed assets are cached for a year, on 200 and 304 only, never on a 404.

The routes are rebuilt on a small app with the real helpers, since the full
app mounts them only when a built dist/ exists.
"""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.core.frontend_files import IMMUTABLE, NO_CACHE, ImmutableStaticFiles, frontend_file

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


@pytest.fixture()
def client(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "icons").mkdir()
    (dist / "index.html").write_text("<!DOCTYPE html><title>SPA</title>", encoding="utf-8")
    (dist / "offline.html").write_text("<!DOCTYPE html><title>Offline</title>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1);", encoding="utf-8")
    (dist / "icons" / "icon-192.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (dist / "manifest.webmanifest").write_text('{"name": "Alpharouter"}', encoding="utf-8")

    app = FastAPI()

    @app.get("/")
    async def root():
        return frontend_file(dist / "index.html")

    app.mount("/assets", ImmutableStaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        candidate = dist / full_path
        return frontend_file(candidate if candidate.is_file() else dist / "index.html")

    return TestClient(app)


def test_index_is_revalidated_on_every_load(client):
    for path in ("/", "/app/chat", "/login"):
        r = client.get(path)
        assert r.status_code == 200
        assert "SPA" in r.text
        assert r.headers["cache-control"] == NO_CACHE


def test_other_html_in_dist_is_revalidated_too(client):
    r = client.get("/offline.html")
    assert r.status_code == 200
    assert r.headers["cache-control"] == NO_CACHE


def test_the_manifest_is_revalidated_and_typed(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["cache-control"] == NO_CACHE
    # X-Content-Type-Options: nosniff is set app-wide, so the type must be right.
    assert r.headers["content-type"].startswith("application/manifest+json")


def test_a_plain_file_from_dist_keeps_the_default(client):
    r = client.get("/icons/icon-192.png")
    assert r.status_code == 200
    assert "cache-control" not in r.headers


def test_hashed_assets_are_cached_for_a_year(client):
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == IMMUTABLE == "public, max-age=31536000, immutable"


def test_a_304_for_an_asset_keeps_the_year(client):
    first = client.get("/assets/index-abc123.js")
    r = client.get("/assets/index-abc123.js", headers={"If-None-Match": first.headers["etag"]})
    assert r.status_code == 304
    assert r.headers["cache-control"] == IMMUTABLE


def test_a_missing_asset_is_never_cached(client):
    r = client.get("/assets/index-gone.js")
    assert r.status_code == 404
    assert "immutable" not in r.headers.get("cache-control", "")


def test_main_serves_the_frontend_through_these_helpers():
    source = MAIN.read_text(encoding="utf-8")
    assert 'ImmutableStaticFiles(directory=_FRONTEND_DIST / "assets")' in source
    assert "FileResponse(" not in source, "serve dist/ files with frontend_file() so they get their Cache-Control"
    assert len(re.findall(r"return frontend_file\(", source)) >= 3
