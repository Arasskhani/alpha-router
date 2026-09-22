"""Binary attachments reach the Code Interpreter sandbox as bytes.

Documents with extracted text keep today's text path; only attachments
without text are hydrated from media storage, with ownership checks and
skip-with-a-note limits instead of a 413.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
from dataclasses import fields
from unittest.mock import AsyncMock

import pytest

from app.config import get_settings
from app.models.media import MediaAsset
from app.services import code_interpreter_service as cis
from app.services import proxy_service
from app.services.code_interpreter_service import (
    ATTACH_PREFIX,
    code_interpreter_workspace_message,
    hydrate_binary_workspace_files,
    run_python_sandbox,
)

PSD_BYTES = b"8BPS\x00\x01" + bytes(range(256))


def _attach_message(*attachments: dict) -> dict:
    return {"role": "user", "content": ATTACH_PREFIX + json.dumps({"attachments": list(attachments)})}


def _binary_att(name: str, url: str, size: int | None = None) -> dict:
    payload = {
        "name": name,
        "kind": "file",
        "mime_type": "application/octet-stream",
        "url": url,
        "text": None,
        "binary": True,
    }
    if size is not None:
        payload["size_bytes"] = size
    return payload


async def _personal_asset(db_session, owner_id: int, file_name: str = "mockup.psd") -> MediaAsset:
    row = MediaAsset(
        user_id=owner_id,
        kind="document",
        mime_type="application/octet-stream",
        file_name=file_name,
        storage_path=f"cdn/u/{owner_id}/{file_name}",
        size_bytes=len(PSD_BYTES),
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.fixture
def stub_media_reader(monkeypatch):
    """Object storage is not available in tests; serve bytes by asset id."""
    reader = AsyncMock(return_value=PSD_BYTES)
    monkeypatch.setattr(cis, "read_media_bytes", reader)
    return reader


@pytest.fixture
def stub_project_reader(monkeypatch):
    reader = AsyncMock(return_value=None)
    monkeypatch.setattr(cis, "read_project_media_bytes", reader)
    return reader


# ---- hydrate_binary_workspace_files ----


async def test_personal_binary_attachment_is_added_as_bytes(db_session, user, stub_media_reader):
    row = await _personal_asset(db_session, user.id)
    messages = [_attach_message(_binary_att("mockup.psd", f"/api/chat/media/{row.id}/file"))]

    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={}, max_files=10, max_total_bytes=1_000_000
    )

    assert files["mockup.psd"] == PSD_BYTES
    assert files["mockup.psd"].startswith(b"8BPS")
    assert notes == []
    stub_media_reader.assert_awaited_once()
    assert stub_media_reader.await_args.args[0].id == row.id


async def test_another_users_personal_asset_is_skipped(db_session, user, stub_media_reader):
    from app.core.security import hash_password
    from app.models.user import User

    other = User(
        username="other_user",
        email="other_user@test",
        hashed_password=hash_password("x"),
        auth_provider="local",
        is_active=True,
    )
    db_session.add(other)
    await db_session.flush()
    row = await _personal_asset(db_session, other.id, "secret.psd")
    messages = [_attach_message(_binary_att("secret.psd", f"/api/chat/media/{row.id}/file"))]

    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={"a.txt": "hi"}, max_files=10, max_total_bytes=1_000_000
    )

    assert files == {"a.txt": "hi"}
    stub_media_reader.assert_not_awaited()
    assert notes == ["secret.psd was not copied into the workspace: it is not available to your account."]


async def test_unknown_asset_id_is_skipped_silently_for_reads(db_session, user, stub_media_reader):
    messages = [_attach_message(_binary_att("gone.psd", "/api/chat/media/999999/file"))]
    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={}, max_files=10, max_total_bytes=1_000_000
    )
    assert files == {}
    assert len(notes) == 1 and "gone.psd" in notes[0]
    stub_media_reader.assert_not_awaited()


async def test_foreign_url_shape_is_ignored(db_session, user, stub_media_reader, stub_project_reader):
    messages = [_attach_message(_binary_att("x.bin", "https://example.com/x.bin"))]
    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={}, max_files=10, max_total_bytes=1_000_000
    )
    assert files == {}
    assert notes == []
    stub_media_reader.assert_not_awaited()
    stub_project_reader.assert_not_awaited()


async def test_project_media_goes_through_membership_reader(db_session, user, stub_project_reader):
    stub_project_reader.return_value = (object(), b"PK\x03\x04zip")
    messages = [_attach_message(_binary_att("bundle.zip", "/api/projects/proj-abc/media/42/download"))]

    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={}, max_files=10, max_total_bytes=1_000_000
    )

    assert files["bundle.zip"] == b"PK\x03\x04zip"
    assert notes == []
    stub_project_reader.assert_awaited_once()
    kwargs = stub_project_reader.await_args.kwargs
    assert kwargs["user"] is user
    assert kwargs["project_id"] == "proj-abc"
    assert kwargs["media_id"] == 42


async def test_project_media_none_is_skipped(db_session, user, stub_project_reader):
    stub_project_reader.return_value = None
    messages = [_attach_message(_binary_att("bundle.zip", "/api/projects/proj-abc/media/42/download"))]
    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={}, max_files=10, max_total_bytes=1_000_000
    )
    assert files == {}
    assert len(notes) == 1 and "bundle.zip" in notes[0]


async def test_project_media_http_error_is_skipped(db_session, user, stub_project_reader):
    from fastapi import HTTPException

    stub_project_reader.side_effect = HTTPException(status_code=403, detail="not a member")
    messages = [_attach_message(_binary_att("bundle.zip", "/api/projects/proj-abc/media/42/download"))]
    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={}, max_files=10, max_total_bytes=1_000_000
    )
    assert files == {}
    assert len(notes) == 1


async def test_document_with_text_stays_text_and_fetches_nothing(
    db_session, user, stub_media_reader, stub_project_reader
):
    row = await _personal_asset(db_session, user.id, "report.pdf")
    messages = [
        _attach_message(
            {
                "name": "report.pdf",
                "kind": "document",
                "mime_type": "application/pdf",
                "url": f"/api/chat/media/{row.id}/file",
                "text": "Quarterly numbers",
            },
            # Extraction ran and found nothing: an empty text file, not a binary.
            {
                "name": "empty.txt",
                "kind": "document",
                "mime_type": "text/plain",
                "url": f"/api/chat/media/{row.id}/file",
                "text": "",
            },
        )
    ]
    text_files = cis.workspace_files_from_messages(messages)
    assert text_files == {"report.pdf": "Quarterly numbers"}

    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files=text_files, max_files=10, max_total_bytes=1_000_000
    )

    assert files == {"report.pdf": "Quarterly numbers"}
    assert notes == []
    stub_media_reader.assert_not_awaited()
    stub_project_reader.assert_not_awaited()


async def test_per_file_limit_skips_with_note(db_session, user, stub_media_reader):
    row = await _personal_asset(db_session, user.id)
    messages = [_attach_message(_binary_att("mockup.psd", f"/api/chat/media/{row.id}/file"))]

    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={}, max_files=10, max_total_bytes=1_000_000, max_file_bytes=100
    )

    assert files == {}
    assert notes == [
        f"mockup.psd ({len(PSD_BYTES)}.0 B) was not copied into the workspace: the per-file limit is 100.0 B."
    ]


async def test_declared_oversize_is_refused_without_a_read(db_session, user, stub_media_reader):
    row = await _personal_asset(db_session, user.id)
    huge = 38 * 1024 * 1024 + 200 * 1024
    messages = [_attach_message(_binary_att("mockup.psd", f"/api/chat/media/{row.id}/file", size=huge))]

    files, notes = await hydrate_binary_workspace_files(
        db_session,
        user=user,
        messages=messages,
        files={},
        max_files=10,
        max_total_bytes=64 * 1024 * 1024,
        max_file_bytes=16 * 1024 * 1024,
    )

    assert files == {}
    assert notes == ["mockup.psd (38.2 MB) was not copied into the workspace: the per-file limit is 16.0 MB."]
    stub_media_reader.assert_not_awaited()


async def test_total_limit_skips_with_note(db_session, user, stub_media_reader):
    row = await _personal_asset(db_session, user.id)
    messages = [_attach_message(_binary_att("mockup.psd", f"/api/chat/media/{row.id}/file"))]
    existing = {"notes.txt": "x" * 900}

    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files=existing, max_files=10, max_total_bytes=1000
    )

    assert files == existing
    assert len(notes) == 1
    assert notes[0].startswith("mockup.psd (") and "total workspace limit" in notes[0]


async def test_count_limit_skips_with_note(db_session, user, stub_media_reader):
    row = await _personal_asset(db_session, user.id)
    messages = [_attach_message(_binary_att("mockup.psd", f"/api/chat/media/{row.id}/file"))]

    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={"a.txt": "a"}, max_files=1, max_total_bytes=1_000_000
    )

    assert files == {"a.txt": "a"}
    assert notes == ["mockup.psd was not copied into the workspace: the workspace is limited to 1 files."]
    stub_media_reader.assert_not_awaited()


async def test_name_collision_keeps_text_file_and_renames_binary(db_session, user, stub_media_reader):
    row = await _personal_asset(db_session, user.id, "data.csv")
    messages = [_attach_message(_binary_att("data.csv", f"/api/chat/media/{row.id}/file"))]
    existing = {"data.csv": "a,b\n1,2\n"}

    files, notes = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files=existing, max_files=10, max_total_bytes=1_000_000
    )

    assert files["data.csv"] == "a,b\n1,2\n"
    assert files["data_2.csv"] == PSD_BYTES
    assert notes == []


async def test_binary_spreadsheet_keeps_its_real_extension(db_session, user, stub_media_reader):
    row = await _personal_asset(db_session, user.id, "book.xlsx")
    messages = [_attach_message(_binary_att("book.xlsx", f"/api/chat/media/{row.id}/file"))]
    files, _ = await hydrate_binary_workspace_files(
        db_session, user=user, messages=messages, files={}, max_files=10, max_total_bytes=1_000_000
    )
    assert "book.xlsx" in files


# ---- inventory message ----


def test_workspace_message_marks_binary_and_appends_notes():
    text = code_interpreter_workspace_message(
        {"blob.bin": b"\x00\x01\x02", "data.csv": "é"},
        notes=["big.psd (38.2 MB) was not copied into the workspace: the per-file limit is 16.0 MB."],
    )
    assert "- blob.bin (3 bytes) (binary)" in text
    assert "- data.csv (2 bytes)" in text
    assert "(binary)" not in text.split("- data.csv")[1].split("\n")[0]
    assert "'rb'" in text
    assert "Not copied:\n- big.psd (38.2 MB)" in text


def test_workspace_message_without_binary_has_no_binary_hint():
    text = code_interpreter_workspace_message({"data.csv": "a"})
    assert "(binary)" not in text
    assert "Not copied" not in text


# ---- sandbox transport ----


@pytest.fixture
def broker_env(monkeypatch):
    monkeypatch.setenv("CODE_SANDBOX_BROKER_URL", "http://sandbox-broker:8081")
    monkeypatch.setenv("CODE_SANDBOX_BROKER_TOKEN", "t" * 48)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_broker_sends_bytes_as_files_b64(monkeypatch, broker_env):
    from app.sandbox.executor import DockerBrokerSandboxExecutor

    execute = AsyncMock(return_value={"stdout": "ok", "stderr": "", "exit_code": 0})
    monkeypatch.setattr(DockerBrokerSandboxExecutor, "execute", execute)

    out = await run_python_sandbox("print(1)", {"blob.bin": b"\x00\xff", "data.csv": "a,b"})

    assert out.exit_code == 0
    execute.assert_awaited_once()
    args, kwargs = execute.await_args.args, execute.await_args.kwargs
    assert args[1] == {"data.csv": "a,b"}
    assert kwargs == {"files_b64": {"blob.bin": base64.b64encode(b"\x00\xff").decode("ascii")}}


async def test_broker_text_only_omits_files_b64_keyword(monkeypatch, broker_env):
    from app.sandbox.executor import DockerBrokerSandboxExecutor

    async def legacy_execute(self, code, files):
        del self, code
        assert files == {"data.csv": "a,b"}
        return {"stdout": "ok", "stderr": "", "exit_code": 0}

    monkeypatch.setattr(DockerBrokerSandboxExecutor, "execute", legacy_execute)

    out = await run_python_sandbox("print(1)", {"data.csv": "a,b"})
    assert out.exit_code == 0
    assert "ok" in out.output


async def test_subprocess_writes_bytes_intact():
    blob = bytes(range(256)) * 3
    code = (
        "import hashlib\nprint(hashlib.sha256(open('blob.bin','rb').read()).hexdigest())\nprint(open('t.txt').read())"
    )
    out = await cis._run_in_subprocess(code, {"blob.bin": blob, "t.txt": "hello"})
    assert out.exit_code == 0, out.output
    assert hashlib.sha256(blob).hexdigest() in out.output
    assert "hello" in out.output


# ---- preflight wiring ----


def test_preflight_hydrates_binaries_and_carries_notes():
    source = inspect.getsource(proxy_service.preflight_stream_chat)
    assert "hydrate_binary_workspace_files(" in source
    assert "code_interpreter_workspace_notes=workspace_notes" in source
    names = {f.name for f in fields(proxy_service.ResolvedStreamContext)}
    assert "code_interpreter_workspace_notes" in names
    ctx = proxy_service.ResolvedStreamContext(ai_model=None, api_key=None, base_url="", provider_type="", model_id="")
    assert ctx.code_interpreter_workspace_notes == []


def test_turn_context_passes_notes_to_inventory():
    from app.services import chat_turn_context

    source = inspect.getsource(chat_turn_context)
    assert 'notes=getattr(resolved, "code_interpreter_workspace_notes", None)' in source
