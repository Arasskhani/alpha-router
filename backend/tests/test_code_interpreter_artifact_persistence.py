"""Code-interpreter artifacts are stored as owner-scoped Media assets."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import proxy_service
from app.services.code_interpreter_service import SandboxArtifact


def _artifact() -> SandboxArtifact:
    content = b"%PDF-1.4\n%%EOF"
    return SandboxArtifact(
        name="management-report.pdf",
        mime_type="application/pdf",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


async def test_persist_code_interpreter_artifact_uses_owner_and_session_metadata():
    media_db = AsyncMock()
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = SimpleNamespace(id="session-1", user_id=7)
    media_db.execute = AsyncMock(return_value=query_result)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=media_db)
    context.__aexit__ = AsyncMock(return_value=None)
    stored_asset = SimpleNamespace(id=42, file_name="management-report.pdf")

    async def run():
        with (
            patch.object(proxy_service, "AsyncSessionLocal", return_value=context),
            patch.object(
                proxy_service,
                "store_generated_blob",
                AsyncMock(return_value=stored_asset),
            ) as store,
        ):
            result = await proxy_service._persist_code_interpreter_artifacts(
                (_artifact(),),
                user_id=7,
                username="owner",
                chat_session_id="session-1",
                model_id="openrouter/auto",
                source_prompt="Create a management report",
            )
        return result, store

    result, store = await run()
    assert result == [
        proxy_service.StoredCodeArtifact(
            asset_id=42,
            name="management-report.pdf",
            url="/api/chat/media/42/file",
        )
    ]
    kwargs = store.await_args.kwargs
    assert kwargs["user_id"] == 7
    assert kwargs["chat_session_id"] == "session-1"
    assert kwargs["kind"] == "document"
    assert kwargs["metadata"]["source"] == "code_interpreter"
    media_db.commit.assert_awaited_once()


async def test_persist_code_interpreter_artifact_rejects_foreign_session():
    media_db = AsyncMock()
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = None
    media_db.execute = AsyncMock(return_value=query_result)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=media_db)
    context.__aexit__ = AsyncMock(return_value=None)

    async def run():
        with patch.object(proxy_service, "AsyncSessionLocal", return_value=context):
            await proxy_service._persist_code_interpreter_artifacts(
                (_artifact(),),
                user_id=7,
                username="owner",
                chat_session_id="foreign-session",
                model_id="openrouter/auto",
                source_prompt="report",
            )

    with pytest.raises(ValueError, match="unavailable"):
        await run()


def test_artifact_links_use_canonical_authenticated_media_route():
    markdown = proxy_service._artifact_links_markdown(
        [
            proxy_service.StoredCodeArtifact(
                asset_id=42,
                name="management-report.pdf",
                url="/api/chat/media/42/file",
            )
        ]
    )
    assert "[management-report.pdf](/api/chat/media/42/file)" in markdown
    assert "sandbox:" not in markdown
