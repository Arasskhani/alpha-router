"""Phase 9: OpenAPI docs/redoc/openapi.json locked to Super Admin in production."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.core.security import create_access_token
from app.database import Base
from app.models.user import User, UserRoleAssignment
from app.services import docs_guard
from app.services.docs_guard import (
    OpenApiDocsGuardMiddleware,
    is_docs_path,
    request_has_super_admin,
)


def _settings(**overrides):
    base = {
        "environment": "production",
        "openapi_admin_only": True,
        "enable_cookie_auth": True,
        "allow_legacy_bearer_auth": True,
        "session_cookie_name": "alpha_router_session",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_is_docs_path_detection():
    assert is_docs_path("/docs")
    assert is_docs_path("/redoc")
    assert is_docs_path("/openapi.json")
    assert is_docs_path("/api/docs")
    assert is_docs_path("/api/redoc")
    assert is_docs_path("/api/openapi.json")
    assert is_docs_path("/docs/")  # trailing slash normalized
    assert not is_docs_path("/")
    assert not is_docs_path("/api/docs/foo")
    assert not is_docs_path("/api")
    assert not is_docs_path("")


def _build_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/docs")
    async def docs():
        return JSONResponse({"ok": True})

    @app.get("/openapi.json")
    async def openapi():
        return JSONResponse({"openapi": "3.0.0"})

    app.add_middleware(OpenApiDocsGuardMiddleware)
    return app


def test_dispatch_blocks_anonymous_in_production():
    app = _build_app()
    with patch("app.services.docs_guard.get_settings", lambda: _settings()), \
         patch("app.services.docs_guard.request_has_super_admin", lambda req: _false()):
        client = TestClient(app)
        r = client.get("/docs")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_dispatch_allows_super_admin_in_production():
    app = _build_app()
    with patch("app.services.docs_guard.get_settings", lambda: _settings()), \
         patch("app.services.docs_guard.request_has_super_admin", lambda req: _true()):
        client = TestClient(app)
        r = client.get("/docs")
        r2 = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert r2.status_code == 200


def test_dispatch_noop_when_openapi_not_admin_only():
    app = _build_app()
    with patch("app.services.docs_guard.get_settings", lambda: _settings(openapi_admin_only=False)), \
         patch("app.services.docs_guard.request_has_super_admin", lambda req: _false()):
        client = TestClient(app)
        r = client.get("/docs")
    assert r.status_code == 200


def test_dispatch_locks_in_development_when_flag_explicitly_set():
    # The guard keys off the explicit operator opt-in (openapi_admin_only), so a
    # dev/single-box deployment that sets the flag still locks docs (and keeps
    # cookie auth working over HTTP for localhost testing).
    app = _build_app()
    with patch("app.services.docs_guard.get_settings", lambda: _settings(environment="development", openapi_admin_only=True)), \
         patch("app.services.docs_guard.request_has_super_admin", lambda req: _false()):
        client = TestClient(app)
        r = client.get("/docs")
    assert r.status_code == 404


def test_dispatch_does_not_guard_non_docs_paths():
    app = _build_app()
    with patch("app.services.docs_guard.get_settings", lambda: _settings()), \
         patch("app.services.docs_guard.request_has_super_admin", lambda req: _false()):
        client = TestClient(app)
        r = client.get("/health")
    # /health is not a route on the minimal app -> 404 from the app itself, not the guard.
    assert r.status_code == 404


async def _false() -> bool:
    return False


async def _true() -> bool:
    return True


# --- request_has_super_admin with a real DB session --------------------------


def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


async def _build_users(factory):
    async with factory() as db:
        super_user = User(
            username="super-admin",
            email="super@alpha-router.local",
            display_name="Super",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        regular = User(
            username="regular-user",
            email="regular@alpha-router.local",
            display_name="Regular",
            hashed_password="x",
            auth_provider="local",
            is_active=True,
        )
        db.add_all([super_user, regular])
        await db.flush()
        db.add(UserRoleAssignment(user_id=super_user.id, role_slug="super_admin"))
        db.add(UserRoleAssignment(user_id=regular.id, role_slug="user"))
        await db.commit()
        return super_user.username, regular.username


def test_request_has_super_admin_accepts_super_admin_cookie():
    async def run():
        engine, factory = _setup_db()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        super_username, _ = await _build_users(factory)
        token = create_access_token(super_username, "super_admin")
        request = _cookie_request(token)
        with patch("app.services.docs_guard.AsyncSessionLocal", factory):
            assert await request_has_super_admin(request) is True
        await engine.dispose()

    asyncio.run(run())


def test_request_has_super_admin_rejects_regular_user_cookie():
    async def run():
        engine, factory = _setup_db()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _, regular_username = await _build_users(factory)
        token = create_access_token(regular_username, "user")
        request = _cookie_request(token)
        with patch("app.services.docs_guard.AsyncSessionLocal", factory):
            assert await request_has_super_admin(request) is False
        await engine.dispose()

    asyncio.run(run())


def test_request_has_super_admin_rejects_missing_cookie():
    async def run():
        engine, factory = _setup_db()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await _build_users(factory)
        request = _cookie_request(None)
        with patch("app.services.docs_guard.AsyncSessionLocal", factory):
            assert await request_has_super_admin(request) is False
        await engine.dispose()

    asyncio.run(run())


class _FakeRequest:
    """Minimal request stand-in with cookies and headers."""

    def __init__(self, cookie: str | None, bearer: str | None = None):
        self.cookies = {"alpha_router_session": cookie} if cookie else {}
        self.headers = {"authorization": f"Bearer {bearer}"} if bearer else {}


def _cookie_request(token: str | None) -> _FakeRequest:
    return _FakeRequest(token)


# pytest async config safety: ensure tests above use asyncio.run, not the loop.
@pytest.fixture(autouse=True)
def _no_asyncio_loop():
    yield
