"""The shared fixtures in conftest.py work and isolate tests from each other."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.user import User
from app.services.rbac import user_has_super_admin_access
from app.services.user_role_service import get_user_role_slugs


def gateway_cookie_name() -> str:
    from app.config import get_settings

    return get_settings().session_cookie_name


async def test_user_and_admin_fixtures(db_session, user, admin) -> None:
    assert user.id != admin.id
    total = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    assert total == 2
    assert user_has_super_admin_access(await get_user_role_slugs(db_session, admin.id))
    assert not user_has_super_admin_access(await get_user_role_slugs(db_session, user.id))


async def test_each_test_gets_a_fresh_schema(db_session) -> None:
    total = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    assert total == 0


async def test_client_uses_the_test_database(client, user) -> None:
    # Unauthenticated -> refused (the real app and middleware chain, not a
    # stub). Then a session cookie for the fixture user is honoured, which
    # proves the dependency override points the app at the test database.
    resp = await client.get("/api/auth/session")
    assert resp.status_code == 401
    from app.core.security import create_access_token

    token = create_access_token(user.username, "user")
    client.cookies.set(gateway_cookie_name(), token)
    resp = await client.get("/api/auth/session")
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == user.username
    resp = await client.get("/health")
    assert resp.status_code == 200
