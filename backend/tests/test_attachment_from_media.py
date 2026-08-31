"""Attach-from-media: authorize, reference URLs, extract documents, never re-persist."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.chat import ChatSession
from app.models.media import MediaAsset
from app.models.project import (
    PROJECT_ROLE_CONTRIBUTOR,
    PROJECT_ROLE_PRIMARY_OWNER,
    PROJECT_ROLE_VIEWER,
    Project,
    ProjectMediaAsset,
    ProjectMember,
)
from app.models.user import User
from app.services.attachment_from_media_service import (
    attachments_from_existing_media,
    resolve_attach_scope,
    unique_positive_ids,
)

PROJ = "from-media-1"
OTHER = "from-media-other"

TRANSFER = {
    "max_upload_file_bytes": 25 * 1024 * 1024,
    "max_chat_attachments_total_bytes": 36 * 1024 * 1024,
    "max_chat_attachments_count": 5,
}


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False), engine


async def _user(db, username):
    u = User(
        username=username,
        email=f"{username}@test",
        hashed_password="x",
        auth_provider="local",
        is_active=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _project(db, owner, *members):
    db.add(
        Project(
            id=PROJ,
            name="From media",
            status="active",
            visibility="private",
            created_by_user_id=owner.id,
            revision=1,
            acl_version=1,
        )
    )
    db.add(ProjectMember(project_id=PROJ, user_id=owner.id, role=PROJECT_ROLE_PRIMARY_OWNER))
    for user, role in members:
        db.add(ProjectMember(project_id=PROJ, user_id=user.id, role=role))
    await db.flush()


def _personal(db, user, **kwargs):
    row = MediaAsset(
        user_id=user.id,
        kind=kwargs.get("kind", "image"),
        mime_type=kwargs.get("mime_type", "image/png"),
        file_name=kwargs.get("file_name", "shot.png"),
        storage_path=kwargs.get("storage_path", "u/1/shot.png"),
        size_bytes=kwargs.get("size_bytes", 1200),
    )
    db.add(row)
    return row


def _project_media(db, user, **kwargs):
    row = ProjectMediaAsset(
        project_id=kwargs.get("project_id", PROJ),
        uploaded_by_user_id=user.id,
        kind=kwargs.get("kind", "image"),
        mime_type=kwargs.get("mime_type", "image/png"),
        file_name=kwargs.get("file_name", "team.png"),
        storage_path=kwargs.get("storage_path", "p/1/team.png"),
        size_bytes=kwargs.get("size_bytes", 900),
    )
    db.add(row)
    return row


async def _session(db, user, **kwargs):
    row = ChatSession(
        id=kwargs.get("id", "sess-1"),
        user_id=user.id,
        title="Chat",
        model_id="model-1",
        project_id=kwargs.get("project_id"),
    )
    db.add(row)
    await db.flush()
    return row


def _run(coro):
    return asyncio.run(coro)


def test_unique_positive_ids_dedupes_and_drops_junk():
    assert unique_positive_ids([2, -1, 2, 0, 3, 3]) == [2, 3]


def test_personal_image_is_referenced_without_persist():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                other = await _user(db, "other")
                mine = _personal(db, owner)
                _personal(db, other, file_name="theirs.png")
                await db.flush()
                with patch(
                    "app.services.attachment_from_media_service.get_transfer_limits",
                    AsyncMock(return_value=TRANSFER),
                ):
                    out = await attachments_from_existing_media(db, owner, [mine.id])
                assert len(out) == 1
                assert out[0]["url"] == f"/api/chat/media/{mine.id}/file"
                assert out[0]["kind"] == "image"
                assert out[0]["name"] == "shot.png"
                assert "data_url" not in out[0]
        finally:
            await engine.dispose()

    _run(run())


def test_personal_media_hidden_from_other_user():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                other = await _user(db, "other")
                mine = _personal(db, owner)
                await db.flush()
                with patch(
                    "app.services.attachment_from_media_service.get_transfer_limits",
                    AsyncMock(return_value=TRANSFER),
                ):
                    with pytest.raises(HTTPException) as exc:
                        await attachments_from_existing_media(db, other, [mine.id])
                assert exc.value.status_code == 404
                assert exc.value.detail == "Media not found"
        finally:
            await engine.dispose()

    _run(run())


def test_missing_personal_media_is_404():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                with patch(
                    "app.services.attachment_from_media_service.get_transfer_limits",
                    AsyncMock(return_value=TRANSFER),
                ):
                    with pytest.raises(HTTPException) as exc:
                        await attachments_from_existing_media(db, owner, [99999])
                assert exc.value.status_code == 404
        finally:
            await engine.dispose()

    _run(run())


def test_video_and_svg_are_rejected():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                video = _personal(
                    db,
                    owner,
                    kind="video",
                    mime_type="video/mp4",
                    file_name="clip.mp4",
                )
                svg = _personal(
                    db,
                    owner,
                    kind="image",
                    mime_type="image/svg+xml",
                    file_name="icon.svg",
                )
                await db.flush()
                with patch(
                    "app.services.attachment_from_media_service.get_transfer_limits",
                    AsyncMock(return_value=TRANSFER),
                ):
                    with pytest.raises(HTTPException) as exc:
                        await attachments_from_existing_media(db, owner, [video.id])
                    assert exc.value.status_code == 400
                    assert "Video" in str(exc.value.detail)
                    with pytest.raises(HTTPException) as exc:
                        await attachments_from_existing_media(db, owner, [svg.id])
                    assert exc.value.status_code == 400
        finally:
            await engine.dispose()

    _run(run())


def test_document_extracts_text_from_existing_bytes():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                doc = _personal(
                    db,
                    owner,
                    kind="document",
                    mime_type="text/plain",
                    file_name="notes.txt",
                    size_bytes=11,
                )
                await db.flush()
                with (
                    patch(
                        "app.services.attachment_from_media_service.get_transfer_limits",
                        AsyncMock(return_value=TRANSFER),
                    ),
                    patch(
                        "app.services.attachment_from_media_service.read_media_bytes",
                        AsyncMock(return_value=b"hello notes"),
                    ),
                ):
                    out = await attachments_from_existing_media(db, owner, [doc.id])
                assert out[0]["kind"] == "document"
                assert out[0]["text"] == "hello notes"
                assert out[0]["url"] == f"/api/chat/media/{doc.id}/file"
        finally:
            await engine.dispose()

    _run(run())


def test_count_limit_uses_unique_ids():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                rows = [_personal(db, owner, file_name=f"a{i}.png") for i in range(6)]
                await db.flush()
                ids = [r.id for r in rows]
                tight = {**TRANSFER, "max_chat_attachments_count": 2}
                with patch(
                    "app.services.attachment_from_media_service.get_transfer_limits",
                    AsyncMock(return_value=tight),
                ):
                    with pytest.raises(HTTPException) as exc:
                        await attachments_from_existing_media(db, owner, ids)
                    assert exc.value.status_code == 400
                    assert "up to 2" in str(exc.value.detail)
                    # duplicates collapse before the limit
                    first = rows[0].id
                    out = await attachments_from_existing_media(
                        db, owner, [first, first, first]
                    )
                    assert len(out) == 1
        finally:
            await engine.dispose()

    _run(run())


def test_project_member_can_reference_project_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                viewer = await _user(db, "viewer")
                await _project(db, owner, (viewer, PROJECT_ROLE_VIEWER))
                asset = _project_media(db, owner)
                session = await _session(db, viewer, id="proj-chat", project_id=PROJ)
                await db.flush()
                with patch(
                    "app.services.attachment_from_media_service.get_transfer_limits",
                    AsyncMock(return_value=TRANSFER),
                ):
                    out = await attachments_from_existing_media(
                        db,
                        viewer,
                        [asset.id],
                        chat_session_id=session.id,
                    )
                assert out[0]["url"] == f"/api/projects/{PROJ}/media/{asset.id}/download"
                assert "data_url" not in out[0]
        finally:
            await engine.dispose()

    _run(run())


def test_non_member_cannot_attach_project_media():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                stranger = await _user(db, "stranger")
                await _project(db, owner)
                asset = _project_media(db, owner)
                session = await _session(db, stranger, id="x", project_id=PROJ)
                await db.flush()
                with patch(
                    "app.services.attachment_from_media_service.get_transfer_limits",
                    AsyncMock(return_value=TRANSFER),
                ):
                    with pytest.raises(HTTPException) as exc:
                        await attachments_from_existing_media(
                            db,
                            stranger,
                            [asset.id],
                            chat_session_id=session.id,
                        )
                assert exc.value.status_code in (403, 404)
        finally:
            await engine.dispose()

    _run(run())


def test_project_media_from_other_project_is_404():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                await _project(db, owner)
                db.add(
                    Project(
                        id=OTHER,
                        name="Other",
                        status="active",
                        visibility="private",
                        created_by_user_id=owner.id,
                        revision=1,
                        acl_version=1,
                    )
                )
                db.add(
                    ProjectMember(
                        project_id=OTHER,
                        user_id=owner.id,
                        role=PROJECT_ROLE_PRIMARY_OWNER,
                    )
                )
                foreign = _project_media(db, owner, project_id=OTHER)
                session = await _session(db, owner, id="here", project_id=PROJ)
                await db.flush()
                with patch(
                    "app.services.attachment_from_media_service.get_transfer_limits",
                    AsyncMock(return_value=TRANSFER),
                ):
                    with pytest.raises(HTTPException) as exc:
                        await attachments_from_existing_media(
                            db,
                            owner,
                            [foreign.id],
                            chat_session_id=session.id,
                        )
                assert exc.value.status_code == 404
        finally:
            await engine.dispose()

    _run(run())


def test_project_id_must_match_chat_scope():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                await _project(db, owner)
                session = await _session(db, owner, id="here", project_id=PROJ)
                await db.flush()
                with pytest.raises(HTTPException) as exc:
                    await resolve_attach_scope(
                        db, project_id=OTHER, chat_session_id=session.id
                    )
                assert exc.value.status_code == 400
                with pytest.raises(HTTPException) as exc:
                    await resolve_attach_scope(
                        db, project_id=PROJ, chat_session_id=None
                    )
                assert exc.value.status_code == 400
                assert await resolve_attach_scope(
                    db, project_id=None, chat_session_id=session.id
                ) == PROJ
        finally:
            await engine.dispose()

    _run(run())


def test_project_document_extracts_without_persist():
    async def run():
        factory, engine = await _factory()
        try:
            async with factory() as db:
                owner = await _user(db, "owner")
                contrib = await _user(db, "contrib")
                await _project(db, owner, (contrib, PROJECT_ROLE_CONTRIBUTOR))
                doc = _project_media(
                    db,
                    owner,
                    kind="document",
                    mime_type="text/plain",
                    file_name="brief.txt",
                    size_bytes=5,
                )
                session = await _session(db, contrib, id="p", project_id=PROJ)
                await db.flush()
                with (
                    patch(
                        "app.services.attachment_from_media_service.get_transfer_limits",
                        AsyncMock(return_value=TRANSFER),
                    ),
                    patch(
                        "app.services.attachment_from_media_service.read_project_media_bytes",
                        AsyncMock(return_value=(doc, b"brief")),
                    ),
                ):
                    out = await attachments_from_existing_media(
                        db,
                        contrib,
                        [doc.id],
                        chat_session_id=session.id,
                        project_id=PROJ,
                    )
                assert out[0]["text"] == "brief"
                assert out[0]["url"] == f"/api/projects/{PROJ}/media/{doc.id}/download"
        finally:
            await engine.dispose()

    _run(run())
