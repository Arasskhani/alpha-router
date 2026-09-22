"""The administrative surface of the upload file-type policy.

The policy decides what may enter the platform, so this module is about who
may change it, that what is saved is what is read back (by the page, by the
composer, by the next upload), and that every change leaves a record that
says exactly which extensions came and went.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.api.admin import (
    FileTypePolicyIn,
    get_storage_overview,
    put_file_type_policy,
    reset_file_type_policy,
)
from app.core.security import create_access_token
from app.models.security import SecurityAuditEvent
from app.models.system import SystemSetting
from app.models.user import User
from app.services import upload_file_policy as policy
from app.services.upload_file_policy import DEFAULT_ALLOWED, DEFAULT_BLOCKED, KEY_BLOCKED, KEY_MODE, load_policy
from app.services.user_role_service import set_user_roles

PUT_URL = "/api/admin/storage/file-type-policy"
RESET_URL = "/api/admin/storage/file-type-policy/reset"
OVERVIEW_URL = "/api/admin/storage"
PUBLIC_URL = "/api/chat/attachment-policy"


@pytest.fixture(autouse=True)
def _fresh_policy_cache():
    """The policy is cached per process; a test must start from the database."""

    policy.invalidate_policy_cache()
    yield
    policy.invalidate_policy_cache()


@pytest.fixture(autouse=True)
def _guard_on_the_test_engine(session_factory, monkeypatch):
    from app.services import admin_ip_allowlist_service

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    admin_ip_allowlist_service.invalidate_restriction_cache()
    yield
    admin_ip_allowlist_service.invalidate_restriction_cache()


class _Request:
    client = type("C", (), {"host": "203.0.113.9"})()
    headers: dict[str, str] = {}


async def _user(db, username: str, *, roles: list[str] | None = None) -> User:
    row = User(username=username, email=f"{username}@test", hashed_password="x", auth_provider="local", is_active=True)
    db.add(row)
    await db.flush()
    if roles:
        await set_user_roles(db, row, roles)
    await db.commit()
    return row


def _sign_in(client, user: User) -> dict[str, str]:
    """Cookie session plus the CSRF pair a browser would send with a PUT/POST."""

    from app.config import get_settings

    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, "csrf-token")
    return {settings.csrf_header_name: "csrf-token"}


async def _audit_rows(db, action: str) -> list[SecurityAuditEvent]:
    return list(
        (await db.execute(select(SecurityAuditEvent).where(SecurityAuditEvent.action == action))).scalars().all()
    )


def _body(
    mode: str = "blocklist", blocked: list[str] | None = None, allowed: list[str] | None = None
) -> FileTypePolicyIn:
    return FileTypePolicyIn(
        mode=mode,
        blocked=sorted(DEFAULT_BLOCKED) if blocked is None else blocked,
        allowed=sorted(DEFAULT_ALLOWED) if allowed is None else allowed,
    )


class TestOverview:
    async def test_the_retention_page_receives_the_policy_block(self, db_session):
        admin = await _user(db_session, "viewer")
        stats = await get_storage_overview(db=db_session, _=admin)
        block = stats["file_types"]
        assert block["mode"] == "blocklist"
        assert block["blocked"] == sorted(DEFAULT_BLOCKED)
        assert block["allowed"] == sorted(DEFAULT_ALLOWED)
        assert block["default_blocked"] == sorted(DEFAULT_BLOCKED)
        assert block["default_allowed"] == sorted(DEFAULT_ALLOWED)
        assert "exe" in block["blocked"]

    async def test_the_page_reads_past_the_cache(self, db_session):
        """Warm the cache with the defaults, then change the row underneath it:
        the page must show the row, because that is what the next save
        will be diffed against."""
        admin = await _user(db_session, "viewer")
        await load_policy(db_session)  # cached defaults
        db_session.add(SystemSetting(key=KEY_MODE, value="allowlist"))
        await db_session.commit()

        stats = await get_storage_overview(db=db_session, _=admin)
        assert stats["file_types"]["mode"] == "allowlist"


class TestPut:
    async def test_saves_mode_and_normalised_lists(self, db_session):
        admin = await _user(db_session, "policy_admin")
        response = await put_file_type_policy(
            _body("allowlist", blocked=[".EXE", "Bat ", "exe"], allowed=["PDF", " .png"]), _Request(), db_session, admin
        )
        assert response["ok"] is True
        assert response["file_types"]["mode"] == "allowlist"
        assert response["file_types"]["blocked"] == ["bat", "exe"]
        assert response["file_types"]["allowed"] == ["pdf", "png"]
        assert response["file_types"]["default_blocked"] == sorted(DEFAULT_BLOCKED)

        stored = await load_policy(db_session, use_cache=False)
        assert stored.mode == "allowlist"
        assert stored.blocked == frozenset({"bat", "exe"})
        assert stored.allowed == frozenset({"pdf", "png"})

    async def test_saving_invalidates_the_process_cache(self, db_session):
        """An upload arriving right after Save must see the new policy, not
        the one cached a moment earlier."""
        admin = await _user(db_session, "policy_admin")
        cached = await load_policy(db_session)
        assert "exe" in cached.blocked

        await put_file_type_policy(_body(blocked=["zip"]), _Request(), db_session, admin)
        fresh = await load_policy(db_session)  # cache allowed
        assert fresh.blocked == frozenset({"zip"})

    async def test_a_bad_entry_is_a_400_that_names_it_and_changes_nothing(self, db_session):
        from fastapi import HTTPException

        admin = await _user(db_session, "policy_admin")
        with pytest.raises(HTTPException) as exc_info:
            await put_file_type_policy(_body(blocked=["exe", "tar.gz"]), _Request(), db_session, admin)
        assert exc_info.value.status_code == 400
        assert "tar.gz" in exc_info.value.detail

        assert await db_session.get(SystemSetting, KEY_BLOCKED) is None
        assert (await load_policy(db_session, use_cache=False)).blocked == DEFAULT_BLOCKED
        assert await _audit_rows(db_session, "upload_file_type_policy_changed") == []

    async def test_an_unknown_mode_is_a_400(self, db_session):
        from fastapi import HTTPException

        admin = await _user(db_session, "policy_admin")
        with pytest.raises(HTTPException) as exc_info:
            await put_file_type_policy(_body("denylist"), _Request(), db_session, admin)
        assert exc_info.value.status_code == 400
        assert "denylist" in exc_info.value.detail
        assert (await load_policy(db_session, use_cache=False)).mode == "blocklist"

    def test_the_schema_caps_each_list(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FileTypePolicyIn(mode="blocklist", blocked=[f"a{i}" for i in range(501)], allowed=[])
        assert len(FileTypePolicyIn(mode="blocklist", blocked=[f"a{i}" for i in range(500)]).blocked) == 500

    async def test_the_change_is_audited_as_a_diff(self, db_session):
        admin = await _user(db_session, "policy_admin")
        new_blocked = sorted((DEFAULT_BLOCKED - {"exe"}) | {"pdf"})
        await put_file_type_policy(_body("allowlist", blocked=new_blocked), _Request(), db_session, admin)

        rows = await _audit_rows(db_session, "upload_file_type_policy_changed")
        assert len(rows) == 1
        assert rows[0].actor_username == "policy_admin"
        assert rows[0].actor_ip == "203.0.113.9"
        assert rows[0].resource_type == "upload_policy"
        assert json.loads(rows[0].detail_json) == {
            "mode_before": "blocklist",
            "mode_after": "allowlist",
            "blocked_added": ["pdf"],
            "blocked_removed": ["exe"],
            "allowed_added": [],
            "allowed_removed": [],
        }

    async def test_the_operator_may_empty_the_blocklist(self, db_session):
        """There is no locked core: the two protections that do not move live
        outside the lists (content sniffing, download-only serving). An empty
        blocklist is a legitimate, if bold, operator decision."""
        admin = await _user(db_session, "policy_admin")
        response = await put_file_type_policy(_body(blocked=[]), _Request(), db_session, admin)
        assert response["file_types"]["blocked"] == []

        stored = await load_policy(db_session, use_cache=False)
        assert stored.blocked == frozenset()
        row = await db_session.get(SystemSetting, KEY_BLOCKED)
        assert row is not None and json.loads(row.value) == []

        [event] = await _audit_rows(db_session, "upload_file_type_policy_changed")
        assert json.loads(event.detail_json)["blocked_removed"] == sorted(DEFAULT_BLOCKED)


class TestReset:
    async def test_reset_restores_defaults_and_is_audited(self, db_session):
        admin = await _user(db_session, "policy_admin")
        await put_file_type_policy(
            _body("allowlist", blocked=sorted(DEFAULT_BLOCKED - {"exe"}), allowed=["pdf"]),
            _Request(),
            db_session,
            admin,
        )

        response = await reset_file_type_policy(_Request(), db_session, admin)
        assert response["ok"] is True
        assert response["file_types"]["mode"] == "blocklist"
        assert response["file_types"]["blocked"] == sorted(DEFAULT_BLOCKED)
        assert response["file_types"]["allowed"] == sorted(DEFAULT_ALLOWED)

        stored = await load_policy(db_session, use_cache=False)
        assert stored.mode == "blocklist"
        assert stored.blocked == DEFAULT_BLOCKED
        assert stored.allowed == DEFAULT_ALLOWED

        [event] = await _audit_rows(db_session, "upload_file_type_policy_reset")
        assert event.actor_username == "policy_admin"
        assert event.actor_ip == "203.0.113.9"
        assert event.resource_type == "upload_policy"
        assert json.loads(event.detail_json) == {
            "mode_before": "allowlist",
            "mode_after": "blocklist",
            "blocked_added": ["exe"],
            "blocked_removed": [],
            "allowed_added": sorted(DEFAULT_ALLOWED - {"pdf"}),
            "allowed_removed": [],
        }


class TestAccessOverHttp:
    async def test_anonymous_is_refused(self, client):
        assert (await client.get(OVERVIEW_URL)).status_code == 401
        assert (await client.put(PUT_URL, json=_body().model_dump())).status_code == 401
        assert (await client.post(RESET_URL)).status_code == 401

    async def test_a_plain_user_is_refused(self, client, user):
        headers = _sign_in(client, user)
        assert (await client.get(OVERVIEW_URL)).status_code == 403
        assert (await client.put(PUT_URL, json=_body().model_dump(), headers=headers)).status_code == 403
        assert (await client.post(RESET_URL, headers=headers)).status_code == 403

    async def test_read_only_super_admin_sees_but_cannot_change(self, client, db_session):
        auditor = await _user(db_session, "auditor", roles=["read_only_super_admin"])
        headers = _sign_in(client, auditor)

        resp = await client.get(OVERVIEW_URL)
        assert resp.status_code == 200, resp.text
        assert resp.json()["file_types"]["blocked"] == sorted(DEFAULT_BLOCKED)

        put = await client.put(PUT_URL, json=_body(blocked=[]).model_dump(), headers=headers)
        assert put.status_code == 403, put.text
        reset = await client.post(RESET_URL, headers=headers)
        assert reset.status_code == 403, reset.text
        assert (await load_policy(db_session, use_cache=False)).blocked == DEFAULT_BLOCKED

    async def test_super_admin_saves_and_the_page_shows_it(self, client, db_session):
        root = await _user(db_session, "root", roles=["super_admin"])
        headers = _sign_in(client, root)

        put = await client.put(
            PUT_URL, json={"mode": "allowlist", "blocked": ["EXE"], "allowed": ["pdf", "PNG"]}, headers=headers
        )
        assert put.status_code == 200, put.text
        assert put.json()["file_types"]["mode"] == "allowlist"
        assert put.json()["file_types"]["blocked"] == ["exe"]
        assert put.json()["file_types"]["allowed"] == ["pdf", "png"]

        overview = await client.get(OVERVIEW_URL)
        assert overview.status_code == 200, overview.text
        assert overview.json()["file_types"]["allowed"] == ["pdf", "png"]

        reset = await client.post(RESET_URL, headers=headers)
        assert reset.status_code == 200, reset.text
        assert reset.json()["file_types"]["mode"] == "blocklist"

    async def test_a_bad_entry_over_http_is_a_400(self, client, db_session):
        root = await _user(db_session, "root", roles=["super_admin"])
        headers = _sign_in(client, root)
        resp = await client.put(
            PUT_URL, json={"mode": "blocklist", "blocked": ["tar.gz"], "allowed": []}, headers=headers
        )
        assert resp.status_code == 400, resp.text
        assert "tar.gz" in resp.json()["detail"]


class TestPublicPolicy:
    async def test_the_composer_reads_the_saved_policy(self, client, db_session, user):
        root = await _user(db_session, "root", roles=["super_admin"])
        headers = _sign_in(client, root)
        put = await client.put(
            PUT_URL, json={"mode": "allowlist", "blocked": ["exe"], "allowed": ["pdf"]}, headers=headers
        )
        assert put.status_code == 200, put.text

        client.cookies.clear()
        assert (await client.get(PUBLIC_URL)).status_code == 401

        _sign_in(client, user)
        resp = await client.get(PUBLIC_URL)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "allowlist"
        assert body["blocked"] == ["exe"]
        assert body["allowed"] == ["pdf"]
        assert isinstance(body["max_attachments"], int) and body["max_attachments"] >= 1
        assert isinstance(body["max_upload_mb"], int) and body["max_upload_mb"] >= 1
        assert "default_blocked" not in body, "the composer gets the policy, not the admin page's defaults"
