"""The operator's upload policy, wired into every path that takes a file.

``upload_file_policy`` decides; these tests are about the callers honouring
that decision end to end: the chat upload endpoint (name before bytes, bytes
after), attaching from the media library, the project media library's kind
mapping, and the Code Interpreter workspace collector. The new kind ``file``
must be stored as a document, described as ``file`` to the model, and reach
the sandbox when its bytes are text.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.media import MediaAsset
from app.models.user import User
from app.services import upload_file_policy as policy
from app.services.attachment_from_media_service import attachments_from_existing_media
from app.services.chat_markers import ATTACHMENT_MESSAGE_PREFIX
from app.services.code_interpreter_service import workspace_files_from_messages

PROCESS_URL = "/api/chat/attachments/process"
PSD_BYTES = b"8BPS" + os.urandom(200)
PY_BYTES = b"import sys\n\nprint(sys.argv)\n"

TRANSFER = {
    "max_upload_file_bytes": 25 * 1024 * 1024,
    "max_chat_attachments_total_bytes": 36 * 1024 * 1024,
    "max_chat_attachments_count": 5,
}


@pytest.fixture(autouse=True)
def _fresh_policy_cache():
    """The policy is cached per process; a test must start from the database."""

    policy.invalidate_policy_cache()
    yield
    policy.invalidate_policy_cache()


@pytest.fixture(autouse=True)
def _no_external_services(session_factory, monkeypatch):
    """No ClamAV and no object store here. The screening gate is tested in its
    own module; storage writes are acknowledged without a bucket so the
    ``MediaAsset`` row — what these tests look at — is still written."""

    monkeypatch.setattr("app.services.admin_ip_guard.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.api.chat.screen_upload", AsyncMock(return_value=None))
    monkeypatch.setattr("app.services.storage_service._put_object_once", AsyncMock(return_value=True))


def _sign_in(client, user: User) -> dict[str, str]:
    """Cookie session plus the CSRF pair a browser would send with a POST."""

    from app.config import get_settings

    settings = get_settings()
    client.cookies.set(settings.session_cookie_name, create_access_token(user.username, "user"))
    client.cookies.set(settings.csrf_cookie_name, "csrf-token")
    return {settings.csrf_header_name: "csrf-token"}


async def _post_file(client, headers, *, name: str, raw: bytes, content_type: str = "application/octet-stream"):
    return await client.post(PROCESS_URL, headers=headers, files=[("files", (name, raw, content_type))])


async def _stored_assets(db) -> list[MediaAsset]:
    return list((await db.execute(select(MediaAsset))).scalars().all())


class TestChatUploadEndpoint:
    async def test_unknown_format_is_accepted_as_kind_file_and_stored_as_document(self, client, user, db_session):
        headers = _sign_in(client, user)
        resp = await _post_file(client, headers, name="mockup.psd", raw=PSD_BYTES)
        assert resp.status_code == 200, resp.text
        [att] = resp.json()["attachments"]
        assert att["kind"] == "file"
        assert att["name"] == "mockup.psd"
        assert att["text"] is None
        assert att["binary"] is True
        assert att["mime_type"] == "application/octet-stream"
        assert att["size_bytes"] == len(PSD_BYTES)

        [asset] = await _stored_assets(db_session)
        assert asset.kind == "document"
        assert asset.file_name == "mockup.psd"

    async def test_blocked_script_is_refused_under_the_default_policy(self, client, user):
        headers = _sign_in(client, user)
        resp = await _post_file(client, headers, name="tool.py", raw=PY_BYTES, content_type="text/x-python")
        assert resp.status_code == 400, resp.text
        assert "not allowed on this platform" in resp.json()["detail"]

    async def test_unblocked_script_is_accepted_with_its_text(self, client, user, db_session):
        await policy.save_policy(
            db_session,
            mode=policy.MODE_BLOCKLIST,
            blocked=sorted(policy.DEFAULT_BLOCKED - {"py"}),
            allowed=sorted(policy.DEFAULT_ALLOWED),
        )
        await db_session.commit()

        headers = _sign_in(client, user)
        resp = await _post_file(client, headers, name="tool.py", raw=PY_BYTES, content_type="text/x-python")
        assert resp.status_code == 200, resp.text
        [att] = resp.json()["attachments"]
        assert att["kind"] == "file"
        assert att["text"] == PY_BYTES.decode().strip()
        assert "binary" not in att
        # The client's text/x-python is on the unsafe list; a file is served as
        # an opaque download whatever the browser called it.
        assert att["mime_type"] == "application/octet-stream"

    async def test_image_whose_bytes_are_svg_is_refused_by_the_content_check(self, client, user, db_session):
        headers = _sign_in(client, user)
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>'
        resp = await _post_file(client, headers, name="logo.png", raw=svg, content_type="image/png")
        assert resp.status_code == 400, resp.text
        detail = resp.json()["detail"]
        assert "HTML" in detail or "SVG" in detail
        assert await _stored_assets(db_session) == []

    async def test_blocked_name_is_refused_before_any_bytes_are_read(self, client, user, monkeypatch):
        from app.api import chat as chat_api

        reads: list[str] = []
        original = chat_api.read_upload_bounded

        async def spy(upload, **kwargs):
            reads.append(upload.filename or "")
            return await original(upload, **kwargs)

        monkeypatch.setattr(chat_api, "read_upload_bounded", spy)
        headers = _sign_in(client, user)
        resp = await _post_file(client, headers, name="setup.exe", raw=b"MZ" + b"\x00" * 64)
        assert resp.status_code == 400, resp.text
        assert "not allowed on this platform" in resp.json()["detail"]
        assert reads == []

    async def test_allowlist_mode_admits_only_the_listed_extensions(self, client, user, db_session):
        await policy.save_policy(db_session, mode=policy.MODE_ALLOWLIST, blocked=[], allowed=["pdf"])
        await db_session.commit()
        headers = _sign_in(client, user)

        refused = await _post_file(client, headers, name="notes.txt", raw=b"hello", content_type="text/plain")
        assert refused.status_code == 400, refused.text
        assert "list of allowed file types" in refused.json()["detail"]

        accepted = await _post_file(client, headers, name="paper.pdf", raw=b"%PDF-1.4\n%%EOF\n")
        assert accepted.status_code == 200, accepted.text
        [att] = accepted.json()["attachments"]
        assert att["kind"] == "document"
        assert att["mime_type"] == "application/pdf"


class TestAttachFromMedia:
    async def test_stored_document_with_unknown_extension_comes_back_as_kind_file(self, db_session, user):
        row = MediaAsset(
            user_id=user.id,
            kind="document",
            mime_type="application/octet-stream",
            file_name="x.psd",
            storage_path="u/1/x.psd",
            size_bytes=len(PSD_BYTES),
        )
        db_session.add(row)
        await db_session.flush()

        with (
            patch(
                "app.services.attachment_from_media_service.get_transfer_limits",
                AsyncMock(return_value=TRANSFER),
            ),
            patch(
                "app.services.attachment_from_media_service.read_media_bytes",
                AsyncMock(return_value=PSD_BYTES),
            ),
        ):
            [att] = await attachments_from_existing_media(db_session, user, [row.id])
        assert att["kind"] == "file"
        assert att["name"] == "x.psd"
        assert att["mime_type"] == "application/octet-stream"
        assert "text" not in att
        assert att["binary"] is True

    async def test_stored_file_with_text_bytes_carries_its_text(self, db_session, user):
        await policy.save_policy(
            db_session,
            mode=policy.MODE_BLOCKLIST,
            blocked=sorted(policy.DEFAULT_BLOCKED - {"py"}),
            allowed=sorted(policy.DEFAULT_ALLOWED),
        )
        row = MediaAsset(
            user_id=user.id,
            kind="document",
            mime_type="application/octet-stream",
            file_name="tool.py",
            storage_path="u/1/tool.py",
            size_bytes=len(PY_BYTES),
        )
        db_session.add(row)
        await db_session.flush()

        with (
            patch(
                "app.services.attachment_from_media_service.get_transfer_limits",
                AsyncMock(return_value=TRANSFER),
            ),
            patch(
                "app.services.attachment_from_media_service.read_media_bytes",
                AsyncMock(return_value=PY_BYTES),
            ),
        ):
            [att] = await attachments_from_existing_media(db_session, user, [row.id])
        assert att["kind"] == "file"
        assert att["text"] == PY_BYTES.decode().strip()
        assert "binary" not in att

    async def test_asset_the_operator_has_since_blocked_cannot_be_attached(self, db_session, user):
        """A library asset is re-classified on attach, so a later block holds."""

        from fastapi import HTTPException

        await policy.save_policy(
            db_session,
            mode=policy.MODE_BLOCKLIST,
            blocked=sorted(policy.DEFAULT_BLOCKED | {"psd"}),
            allowed=sorted(policy.DEFAULT_ALLOWED),
        )
        row = MediaAsset(
            user_id=user.id,
            kind="document",
            mime_type="application/octet-stream",
            file_name="x.psd",
            storage_path="u/1/x.psd",
            size_bytes=10,
        )
        db_session.add(row)
        await db_session.flush()

        with patch(
            "app.services.attachment_from_media_service.get_transfer_limits",
            AsyncMock(return_value=TRANSFER),
        ):
            with pytest.raises(HTTPException) as exc:
                await attachments_from_existing_media(db_session, user, [row.id])
        assert exc.value.status_code == 400
        assert "not allowed on this platform" in str(exc.value.detail)


class TestProjectMediaKind:
    async def test_kind_file_is_stored_as_a_project_document(self, db_session, user):
        from app.models.project import PROJECT_ROLE_PRIMARY_OWNER, Project, ProjectMember
        from app.services.project_media_service import upload_project_media

        class MemoryStore:
            def __init__(self) -> None:
                self.blobs: dict[str, bytes] = {}

            async def put(self, key: str, body: bytes, mime: str) -> None:
                self.blobs[key] = body

            async def get(self, key: str) -> bytes:
                return self.blobs[key]

            async def delete(self, key: str) -> None:
                self.blobs.pop(key, None)

            async def exists(self, key: str) -> bool:
                return key in self.blobs

        db_session.add(
            Project(
                id="wiring-proj",
                name="Wiring",
                status="active",
                visibility="private",
                created_by_user_id=user.id,
                revision=1,
                acl_version=1,
            )
        )
        db_session.add(ProjectMember(project_id="wiring-proj", user_id=user.id, role=PROJECT_ROLE_PRIMARY_OWNER))
        await db_session.flush()

        item = await upload_project_media(
            db_session,
            project_id="wiring-proj",
            user=user,
            file_name="mockup.psd",
            mime_type="application/octet-stream",
            content_bytes=PSD_BYTES,
            kind="file",
            object_store=MemoryStore(),
        )
        assert item["kind"] == "document"
        assert item["fileName"] == "mockup.psd"

    async def test_unknown_kind_is_still_refused(self, db_session, user):
        from app.services.project_media_service import ProjectMediaValidationError, _infer_kind

        assert _infer_kind("application/octet-stream", "file") == "document"
        with pytest.raises(ProjectMediaValidationError):
            _infer_kind("application/octet-stream", "blob")


class TestProjectMediaEndpoint:
    """The project library is a place other members download from, so the
    upload endpoint runs the same name and content policy as chat. The
    service call is stubbed: what is under test is the gate in front of it."""

    @pytest.fixture
    def store_spy(self, monkeypatch):
        spy = AsyncMock(return_value={"id": 1, "kind": "document", "fileName": "x"})
        monkeypatch.setattr("app.api.projects.upload_project_media", spy)
        monkeypatch.setattr("app.api.projects.screen_upload", AsyncMock(return_value=None))
        return spy

    async def _post(self, client, headers, *, name: str, raw: bytes):
        return await client.post(
            "/api/projects/any-project/media",
            headers=headers,
            files={"file": (name, raw, "application/octet-stream")},
        )

    async def test_a_blocked_name_never_reaches_storage_or_the_scanner(self, client, user, store_spy, monkeypatch):
        read_spy = AsyncMock(return_value=b"MZ")
        monkeypatch.setattr("app.api.projects.read_upload_bounded", read_spy)
        headers = _sign_in(client, user)
        resp = await self._post(client, headers, name="setup.exe", raw=b"MZ" * 10)
        assert resp.status_code == 400
        assert "not allowed on this platform" in resp.json()["detail"]
        read_spy.assert_not_called()
        store_spy.assert_not_called()

    async def test_bytes_that_contradict_the_name_are_refused(self, client, user, store_spy):
        headers = _sign_in(client, user)
        resp = await self._post(client, headers, name="logo.png", raw=b"<svg onload=alert(1)></svg>")
        assert resp.status_code == 400
        assert "HTML or SVG" in resp.json()["detail"]
        store_spy.assert_not_called()

    async def test_an_unknown_but_honest_file_is_passed_on(self, client, user, store_spy):
        headers = _sign_in(client, user)
        resp = await self._post(client, headers, name="mockup.psd", raw=PSD_BYTES)
        assert resp.status_code == 201, resp.text
        store_spy.assert_awaited_once()
        assert store_spy.await_args.kwargs["file_name"] == "mockup.psd"
        # The client's own kind (none here) still decides the library kind.
        assert store_spy.await_args.kwargs["kind"] is None


class TestCodeInterpreterWorkspace:
    def test_text_file_attachment_reaches_the_workspace_and_binary_does_not(self):
        payload = {
            "attachments": [
                {"name": "tool.py", "kind": "file", "text": PY_BYTES.decode(), "url": "/x"},
                {"name": "mockup.psd", "kind": "file", "text": None, "binary": True, "url": "/y"},
                {"name": "notes.txt", "kind": "document", "text": "hello", "url": "/z"},
                {"name": "shot.png", "kind": "image", "url": "/w"},
            ]
        }
        messages = [{"role": "user", "content": ATTACHMENT_MESSAGE_PREFIX + json.dumps(payload)}]
        files = workspace_files_from_messages(messages)
        assert files == {"tool.py": PY_BYTES.decode(), "notes.txt": "hello"}
