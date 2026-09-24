"""Handing out the browser extension: Settings → Extension, the download, and Group Policy updates.

The backend CI jobs do not build the frontend, so these tests build a small
extension folder of their own from the real manifest template.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core.security import create_access_token
from app.models.security import SecurityAuditEvent
from app.models.user import User
from app.services import extension_distribution, extension_keys
from app.services.chat_tool_access_service import set_chat_tool_access
from app.services.extension_distribution import resolve_extension_dist
from app.services.extension_keys import load_or_create_signing_key
from app.services.extension_settings import ExtensionSettings, load_extension_settings, save_extension_settings
from app.services.resource_access_service import AccessGrant
from app.services.user_role_service import set_user_roles

TEMPLATE = Path(__file__).resolve().parents[2] / "frontend" / "extension" / "manifest.template.json"
SERVER = "https://ai.example.com"
CSRF = "csrf-token"


@pytest.fixture
def built_extension(tmp_path, monkeypatch) -> Path:
    dist = tmp_path / "dist-extension"
    (dist / "icons").mkdir(parents=True)
    (dist / "manifest.json").write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    (dist / "config.json").write_text('{"serverUrl": ""}\n', encoding="utf-8")
    (dist / "background.js").write_text("// sw\n", encoding="utf-8")
    (dist / "icons" / "icon-16.png").write_bytes(b"\x89PNG")
    monkeypatch.setattr(extension_distribution, "resolve_extension_dist", lambda: dist)
    return dist


@pytest.fixture(autouse=True)
def _server(monkeypatch, session_factory):
    monkeypatch.setattr(extension_keys, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(extension_distribution, "AsyncSessionLocal", session_factory)
    # The admin IP guard reads its allowlist in a session of its own.
    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr(get_settings(), "frontend_url", f"{SERVER}/")
    monkeypatch.setattr(get_settings(), "app_version", "v1.4.0")


def _sign_in(client, user) -> dict[str, str]:
    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, CSRF)
    return {settings.csrf_header_name: CSRF}


async def _user(db, username: str, *, roles: list[str] | None = None, active: bool = True) -> User:
    row = User(
        username=username, email=f"{username}@test", hashed_password="x", auth_provider="local", is_active=active
    )
    db.add(row)
    await db.flush()
    if roles:
        await set_user_roles(db, row, roles)
    await db.commit()
    return row


class TestTheSettingsTab:
    async def test_a_user_sees_what_this_server_hands_out(self, client, db_session, user, built_extension):
        _sign_in(client, user)
        resp = await client.get("/api/extension/info")
        assert resp.status_code == 200, resp.text
        info = resp.json()
        key = await load_or_create_signing_key(db_session)
        assert info["available"] is True and info["permitted"] is True
        assert info["version"] == "1.0.0.1"
        assert info["extension_id"] == key.extension_id
        assert info["update_url"] == f"{SERVER}/extension/update.xml"
        assert info["gpo_value"] == f"{key.extension_id};{SERVER}/extension/update.xml"
        assert info["server_url"] == SERVER
        assert info["site_access"] == "per_site"

    async def test_without_a_build_it_says_so(self, client, user, monkeypatch, tmp_path):
        monkeypatch.setattr(extension_distribution, "resolve_extension_dist", lambda: tmp_path / "missing")
        _sign_in(client, user)
        info = (await client.get("/api/extension/info")).json()
        assert info["available"] is False
        assert info["reason_code"] == "not_built"
        assert "npm run build" in info["reason"]

    async def test_a_loopback_frontend_url_reached_by_another_name_is_refused(
        self, client, user, built_extension, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "frontend_url", "http://127.0.0.1:8080")
        _sign_in(client, user)
        info = (await client.get("/api/extension/info")).json()
        assert info["available"] is False
        assert info["reason_code"] == "frontend_url"
        assert "FRONTEND_URL" in info["reason"]

    async def _info_as(self, session_factory, user, *, base_url: str, client: tuple[str, int]) -> dict:
        import httpx

        from app.database import get_db
        from app.main import app as fastapi_app

        async def _get_db():
            async with session_factory() as session:
                yield session
                await session.commit()

        fastapi_app.dependency_overrides[get_db] = _get_db
        try:
            transport = httpx.ASGITransport(app=fastapi_app, client=client)
            async with httpx.AsyncClient(transport=transport, base_url=base_url) as local:
                _sign_in(local, user)
                return (await local.get("/api/extension/info")).json()
        finally:
            fastapi_app.dependency_overrides.pop(get_db, None)

    async def test_a_proxy_on_this_host_cannot_make_a_visitor_look_local(
        self, session_factory, user, built_extension, monkeypatch
    ):
        """Host: 127.0.0.1 from a proxy on the same machine, but the visitor is elsewhere."""
        monkeypatch.setattr(get_settings(), "frontend_url", "http://127.0.0.1:8080")
        info = await self._info_as(
            session_factory, user, base_url="http://127.0.0.1:8080", client=("203.0.113.9", 51000)
        )
        assert info["available"] is False
        assert info["reason_code"] == "frontend_url"

    @pytest.mark.parametrize("url", ["http://0.0.0.0:8080", "http://[::]:8080"])
    async def test_a_listening_address_is_never_a_server_address(
        self, session_factory, user, built_extension, monkeypatch, url
    ):
        monkeypatch.setattr(get_settings(), "frontend_url", url)
        info = await self._info_as(session_factory, user, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 51000))
        assert info["available"] is False
        assert "listen on" in info["reason"]

    async def test_a_loopback_frontend_url_reached_on_loopback_works(
        self, session_factory, user, built_extension, monkeypatch
    ):
        """Local development: the server and the browser on one machine."""
        import httpx

        from app.database import get_db
        from app.main import app as fastapi_app

        async def _get_db():
            async with session_factory() as session:
                yield session
                await session.commit()

        monkeypatch.setattr(get_settings(), "frontend_url", "http://127.0.0.1:8080")
        fastapi_app.dependency_overrides[get_db] = _get_db
        try:
            transport = httpx.ASGITransport(app=fastapi_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as local:
                _sign_in(local, user)
                info = (await local.get("/api/extension/info")).json()
        finally:
            fastapi_app.dependency_overrides.pop(get_db, None)
        assert info["available"] is True
        assert info["server_url"] == "http://127.0.0.1:8080"

    async def test_a_user_the_admin_left_out_is_told_so(self, client, db_session, user, built_extension):
        await set_chat_tool_access(db_session, "browser_extension", access_type="private", grants=[])
        await db_session.commit()
        _sign_in(client, user)
        info = (await client.get("/api/extension/info")).json()
        assert info["permitted"] is False
        assert info["available"] is True

    async def test_signing_in_is_required(self, client, built_extension):
        assert (await client.get("/api/extension/info")).status_code == 401


class TestTheDownload:
    async def test_it_is_this_servers_extension(self, client, db_session, user, built_extension):
        _sign_in(client, user)
        resp = await client.get("/api/extension/download")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/zip"
        assert resp.headers["content-disposition"] == 'attachment; filename="alpharouter-extension-1.0.0.1.zip"'
        assert resp.headers["cache-control"] == "no-store"
        archive = zipfile.ZipFile(io.BytesIO(resp.content))
        assert sorted(archive.namelist()) == ["background.js", "config.json", "icons/icon-16.png", "manifest.json"]
        manifest = json.loads(archive.read("manifest.json"))
        key = await load_or_create_signing_key(db_session)
        assert manifest["key"] == key.public_key_b64
        assert manifest["version"] == "1.0.0.1"
        assert "version_name" not in manifest
        assert manifest["host_permissions"] == [f"{SERVER}/*"]
        assert manifest["optional_host_permissions"] == ["<all_urls>"]
        assert manifest["web_accessible_resources"] == [{"resources": ["connected.html"], "matches": [f"{SERVER}/*"]}]
        assert manifest["permissions"] == json.loads(TEMPLATE.read_text())["permissions"]
        assert json.loads(archive.read("config.json")) == {
            "serverUrl": SERVER,
            "serverName": "Alpharouter",
            "extensionVersion": "1.0.0.1",
        }

    async def test_all_sites_access_is_in_the_manifest_with_a_new_version(
        self, client, db_session, user, built_extension
    ):
        _sign_in(client, user)
        first = zipfile.ZipFile(io.BytesIO((await client.get("/api/extension/download")).content))
        before = json.loads(first.read("manifest.json"))
        await save_extension_settings(db_session, ExtensionSettings(site_access="all_sites"))
        await db_session.commit()
        archive = zipfile.ZipFile(io.BytesIO((await client.get("/api/extension/download")).content))
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["host_permissions"] == [f"{SERVER}/*", "<all_urls>"]
        assert "optional_host_permissions" not in manifest
        assert (before["version"], manifest["version"]) == ("1.0.0.1", "1.0.0.2")

    async def test_the_key_and_id_stay_the_same_across_downloads(self, client, user, built_extension):
        _sign_in(client, user)
        first = zipfile.ZipFile(io.BytesIO((await client.get("/api/extension/download")).content))
        second = zipfile.ZipFile(io.BytesIO((await client.get("/api/extension/download")).content))
        assert json.loads(first.read("manifest.json"))["key"] == json.loads(second.read("manifest.json"))["key"]

    async def test_not_for_a_user_the_admin_left_out(self, client, db_session, user, built_extension):
        await set_chat_tool_access(db_session, "browser_extension", access_type="private", grants=[])
        await db_session.commit()
        _sign_in(client, user)
        assert (await client.get("/api/extension/download")).status_code == 403

    async def test_a_grant_lets_that_user_through(self, client, db_session, user, built_extension):
        await set_chat_tool_access(
            db_session,
            "browser_extension",
            access_type="private",
            grants=[AccessGrant(target_type="user", target=user.id)],
        )
        await db_session.commit()
        _sign_in(client, user)
        assert (await client.get("/api/extension/download")).status_code == 200

    async def test_not_for_a_disabled_account(self, client, db_session, built_extension):
        disabled = await _user(db_session, "disabled", active=False)
        _sign_in(client, disabled)
        assert (await client.get("/api/extension/download")).status_code == 403

    async def test_unavailable_is_503_with_the_reason(self, client, user, monkeypatch, tmp_path):
        monkeypatch.setattr(extension_distribution, "resolve_extension_dist", lambda: tmp_path / "missing")
        _sign_in(client, user)
        resp = await client.get("/api/extension/download")
        assert resp.status_code == 503
        assert "not built" in resp.json()["detail"]


class TestTheVersionFollowsThePackage:
    async def _version(self, client) -> str:
        return (await client.get("/api/extension/info")).json()["version"]

    async def test_the_same_package_keeps_its_version(self, client, user, built_extension):
        _sign_in(client, user)
        assert await self._version(client) == "1.0.0.1"
        assert await self._version(client) == "1.0.0.1"

    async def test_new_code_is_a_new_version_even_without_a_new_tag(self, client, user, built_extension):
        """git describe gives v1.1.0-256-g... for every build after v1.1.0: the tag alone would never move."""
        _sign_in(client, user)
        assert await self._version(client) == "1.0.0.1"
        (built_extension / "background.js").write_text("// sw, changed\n", encoding="utf-8")
        assert await self._version(client) == "1.0.0.2"

    async def test_a_new_origin_is_a_new_version(self, client, user, built_extension, monkeypatch):
        _sign_in(client, user)
        assert await self._version(client) == "1.0.0.1"
        monkeypatch.setattr(get_settings(), "frontend_url", "https://ai2.example.com")
        assert await self._version(client) == "1.0.0.2"

    async def test_the_app_version_alone_does_not_change_it(self, client, user, built_extension, monkeypatch):
        _sign_in(client, user)
        assert await self._version(client) == "1.0.0.1"
        monkeypatch.setattr(get_settings(), "app_version", "v1.5.0")
        assert await self._version(client) == "1.0.0.1"

    async def test_two_builds_answering_at_once_keep_their_numbers(self, client, user, built_extension):
        """Old and new workers during an upgrade: the counter must not climb on every request."""
        _sign_in(client, user)
        background = built_extension / "background.js"
        old = background.read_text(encoding="utf-8")
        assert await self._version(client) == "1.0.0.1"
        background.write_text("// new build\n", encoding="utf-8")
        assert await self._version(client) == "1.0.0.2"
        background.write_text(old, encoding="utf-8")
        assert await self._version(client) == "1.0.0.1"
        background.write_text("// new build\n", encoding="utf-8")
        assert await self._version(client) == "1.0.0.2"

    async def test_an_old_build_seen_long_ago_gets_a_new_number(self, client, user, built_extension):
        _sign_in(client, user)
        background = built_extension / "background.js"
        first = background.read_text(encoding="utf-8")
        assert await self._version(client) == "1.0.0.1"
        for i in range(3):
            background.write_text(f"// build {i}\n", encoding="utf-8")
            await self._version(client)
        background.write_text(first, encoding="utf-8")
        assert await self._version(client) == "1.0.0.5"

    async def test_the_counter_by_fingerprint(self):
        from app.services.extension_distribution import package_revision

        assert await package_revision("fp-a") == 1
        assert await package_revision("fp-b") == 2
        assert await package_revision("fp-b") == 2
        assert await package_revision("fp-a") == 1


class TestTwoWorkersSeeANewBuildAtOnce:
    async def test_the_one_whose_update_loses_takes_the_next_number(self, session_factory, monkeypatch):
        from sqlalchemy.sql.dml import Update

        from app.models.system import SystemSetting
        from app.services.extension_distribution import PACKAGE_KEY, package_revision

        assert await package_revision("fp-a") == 1

        class _Racing:
            """A session whose first UPDATE finds another worker already moved the counter on."""

            def __init__(self, inner):
                self._inner = inner
                self.raced = False

            async def __aenter__(self):
                await self._inner.__aenter__()
                return self

            async def __aexit__(self, *exc):
                return await self._inner.__aexit__(*exc)

            def __getattr__(self, name):
                return getattr(self._inner, name)

            async def execute(self, statement, *args, **kwargs):
                if isinstance(statement, Update) and not self.raced:
                    self.raced = True
                    async with session_factory() as other:
                        row = await other.get(SystemSetting, PACKAGE_KEY)
                        row.value = json.dumps({"latest": 2, "recent": {"fp-a": 1, "fp-b": 2}}, sort_keys=True)
                        await other.commit()
                return await self._inner.execute(statement, *args, **kwargs)

        monkeypatch.setattr(extension_distribution, "AsyncSessionLocal", lambda: _Racing(session_factory()))
        assert await package_revision("fp-c") == 3
        async with session_factory() as session:
            stored = json.loads((await session.get(SystemSetting, PACKAGE_KEY)).value)
        assert stored == {"latest": 3, "recent": {"fp-a": 1, "fp-b": 2, "fp-c": 3}}


class TestBuildingOnce:
    async def test_the_crx_is_signed_once_per_package(self, client, built_extension, monkeypatch):
        signed = []
        real = extension_distribution.build_crx3

        def counting(archive, key):
            signed.append(1)
            return real(archive, key)

        monkeypatch.setattr(extension_distribution, "build_crx3", counting)
        first = await client.get("/extension/alpharouter.crx")
        second = await client.get("/extension/alpharouter.crx")
        assert first.status_code == second.status_code == 200
        assert first.content == second.content
        assert len(signed) == 1
        (built_extension / "background.js").write_text("// changed\n", encoding="utf-8")
        third = await client.get("/extension/alpharouter.crx")
        assert third.content != first.content
        assert len(signed) == 2

    async def test_the_built_files_are_read_again_only_when_they_change(
        self, client, user, built_extension, monkeypatch
    ):
        reads = []
        real = extension_distribution.read_dist

        def counting(dist):
            reads.append(1)
            return real(dist)

        monkeypatch.setattr(extension_distribution, "read_dist", counting)
        _sign_in(client, user)
        await client.get("/api/extension/info")
        await client.get("/extension/update.xml")
        assert len(reads) == 1
        (built_extension / "config.json").write_text('{"serverUrl": "x"}\n', encoding="utf-8")
        await client.get("/api/extension/info")
        assert len(reads) == 2


class TestGroupPolicyUpdates:
    async def test_update_xml_and_the_crx_agree(self, client, db_session, built_extension):
        xml = await client.get("/extension/update.xml")
        assert xml.status_code == 200
        assert xml.headers["content-type"].startswith("application/xml")
        assert xml.headers["cache-control"] == "no-cache"
        key = await load_or_create_signing_key(db_session)
        ns = "{http://www.google.com/update2/response}"
        app = ElementTree.fromstring(xml.text).find(f"{ns}app")
        check = app.find(f"{ns}updatecheck")
        assert app.get("appid") == key.extension_id
        assert check.get("version") == "1.0.0.1"
        assert check.get("codebase") == f"{SERVER}/extension/alpharouter.crx?v=1.0.0.1"
        # The app's version is for admins; it is not published here.
        assert "1.4.0" not in xml.text

        crx = await client.get("/extension/alpharouter.crx?v=1.0.0.1")
        assert crx.status_code == 200
        assert crx.headers["content-type"] == "application/x-chrome-extension"
        assert crx.content[:4] == b"Cr24" and struct.unpack("<I", crx.content[4:8])[0] == 3
        header_size = struct.unpack("<I", crx.content[8:12])[0]
        archive = zipfile.ZipFile(io.BytesIO(crx.content[12 + header_size :]))
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == "1.0.0.1"
        assert manifest["key"] == key.public_key_b64
        assert key.public_der in crx.content[12 : 12 + header_size]
        assert b"1.4.0" not in crx.content

    async def test_they_need_no_session_but_404_when_unavailable(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(extension_distribution, "resolve_extension_dist", lambda: tmp_path / "missing")
        assert (await client.get("/extension/update.xml")).status_code == 404
        assert (await client.get("/extension/alpharouter.crx")).status_code == 404


class TestTheAdminCard:
    async def test_an_admin_reads_the_settings_and_the_distribution(self, client, admin, built_extension):
        _sign_in(client, admin)
        resp = await client.get("/api/admin/extension/settings")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["settings"]["site_access"] == "per_site"
        assert body["distribution"]["available"] is True
        assert body["distribution"]["gpo_value"].endswith(";https://ai.example.com/extension/update.xml")

    async def test_saving_validates_audits_and_publishes_a_new_version(
        self, client, db_session, admin, built_extension
    ):
        headers = _sign_in(client, admin)
        body = {
            "site_access": "all_sites",
            "allowed_sites": [],
            "blocked_sites": ["Bank.example", "*.gambling.example"],
            "page_content_models": [],
            "agent_models": [],
            "agent_max_steps": 30,
            "agent_auto_mode": False,
            "agent_review_model": None,
        }
        resp = await client.put("/api/admin/extension/settings", json=body, headers=headers)
        assert resp.status_code == 200, resp.text
        saved = resp.json()["settings"]
        assert saved["blocked_sites"] == ["*.gambling.example", "bank.example"]
        assert "manifest_revision" not in saved
        assert resp.json()["distribution"]["version"] == "1.0.0.1"
        assert (await load_extension_settings(db_session)).agent_max_steps == 30

        rows = (
            (
                await db_session.execute(
                    select(SecurityAuditEvent).where(SecurityAuditEvent.action == "extension_settings_updated")
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        detail = json.loads(rows[0].detail_json)
        assert detail["before"]["site_access"] == "per_site"
        assert detail["after"]["site_access"] == "all_sites"

    async def test_a_bad_value_is_a_400_that_says_why(self, client, admin, built_extension):
        headers = _sign_in(client, admin)
        body = {
            "site_access": "per_site",
            "blocked_sites": ["https://bank.example/login"],
            "agent_max_steps": 25,
        }
        resp = await client.put("/api/admin/extension/settings", json=body, headers=headers)
        assert resp.status_code == 400
        assert "Blocked sites" in resp.json()["detail"]
        auto = {"site_access": "per_site", "agent_max_steps": 25, "agent_auto_mode": True}
        resp = await client.put("/api/admin/extension/settings", json=auto, headers=headers)
        assert resp.status_code == 400
        assert "review model" in resp.json()["detail"]

    async def test_a_plain_user_cannot_read_it(self, client, user, built_extension):
        _sign_in(client, user)
        assert (await client.get("/api/admin/extension/settings")).status_code == 403

    async def test_a_read_only_admin_sees_but_cannot_change(self, client, db_session, built_extension):
        auditor = await _user(db_session, "auditor", roles=["read_only_super_admin"])
        headers = _sign_in(client, auditor)
        assert (await client.get("/api/admin/extension/settings")).status_code == 200
        body = {"site_access": "all_sites", "agent_max_steps": 25}
        assert (await client.put("/api/admin/extension/settings", json=body, headers=headers)).status_code == 403
        assert (await load_extension_settings(db_session)).site_access == "per_site"


def test_the_build_is_found_in_the_image_and_in_a_checkout(tmp_path):
    image = tmp_path / "app"
    (image / "frontend" / "dist-extension").mkdir(parents=True)
    services = image / "app" / "services" / "extension_distribution.py"
    services.parent.mkdir(parents=True)
    assert resolve_extension_dist(services) == image / "frontend" / "dist-extension"

    checkout = tmp_path / "repo"
    (checkout / "frontend" / "dist-extension").mkdir(parents=True)
    services = checkout / "backend" / "app" / "services" / "extension_distribution.py"
    services.parent.mkdir(parents=True)
    assert resolve_extension_dist(services) == checkout / "frontend" / "dist-extension"
