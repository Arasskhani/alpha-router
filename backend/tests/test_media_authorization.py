"""Object-level authorization matrix for user media."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api import chat, images
from app.services import media_authorization_service as media_auth


class FakeDb:
    def __init__(self, asset):
        self.asset = asset
        self.deleted = None

    async def get(self, model, asset_id):
        del model, asset_id
        return self.asset

    async def delete(self, asset):
        self.deleted = asset

    async def flush(self):
        return None


def _authorize(*, owner_id: int, actor_id: int, slugs: list[str], action: media_auth.MediaAccessAction):
    asset = SimpleNamespace(id=7, user_id=owner_id)
    actor = SimpleNamespace(id=actor_id)

    async def run():
        with patch.object(media_auth, "get_user_role_slugs", AsyncMock(return_value=slugs)):
            return await media_auth.load_authorized_media_asset(
                FakeDb(asset),
                actor,
                asset.id,
                action=action,
            )

    return asyncio.run(run())


@pytest.mark.parametrize("action", list(media_auth.MediaAccessAction))
def test_owner_can_read_and_delete_own_media(action: media_auth.MediaAccessAction) -> None:
    asset = _authorize(owner_id=10, actor_id=10, slugs=["user"], action=action)
    assert asset.id == 7


@pytest.mark.parametrize(
    "slugs",
    [
        ["user"],
        ["connections_full_administrator"],
        ["api_keys_full_administrator"],
    ],
)
@pytest.mark.parametrize("action", list(media_auth.MediaAccessAction))
def test_unrelated_roles_cannot_access_cross_user_media(
    slugs: list[str],
    action: media_auth.MediaAccessAction,
) -> None:
    with pytest.raises(HTTPException) as exc:
        _authorize(owner_id=10, actor_id=20, slugs=slugs, action=action)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Media not found"


@pytest.mark.parametrize(
    ("slugs", "action", "allowed"),
    [
        (["api_keys_full_administrator"], media_auth.MediaAccessAction.READ, False),
        (["api_keys_full_administrator"], media_auth.MediaAccessAction.DELETE, False),
        (["super_admin"], media_auth.MediaAccessAction.READ, True),
        (["super_admin"], media_auth.MediaAccessAction.DELETE, True),
        (["read_only_full_administrator"], media_auth.MediaAccessAction.READ, True),
        (["read_only_full_administrator"], media_auth.MediaAccessAction.DELETE, False),
    ],
)
def test_cross_user_media_requires_exact_permission(
    slugs: list[str],
    action: media_auth.MediaAccessAction,
    allowed: bool,
) -> None:
    if allowed:
        assert _authorize(owner_id=10, actor_id=20, slugs=slugs, action=action).id == 7
    else:
        with pytest.raises(HTTPException) as exc:
            _authorize(owner_id=10, actor_id=20, slugs=slugs, action=action)
        assert exc.value.status_code == 404


def test_missing_and_forbidden_assets_are_indistinguishable() -> None:
    actor = SimpleNamespace(id=20)

    async def run_missing():
        return await media_auth.load_authorized_media_asset(
            FakeDb(None),
            actor,
            999,
            action=media_auth.MediaAccessAction.READ,
        )

    with pytest.raises(HTTPException) as missing:
        asyncio.run(run_missing())
    with pytest.raises(HTTPException) as forbidden:
        _authorize(
            owner_id=10,
            actor_id=20,
            slugs=["connections_full_administrator"],
            action=media_auth.MediaAccessAction.READ,
        )
    assert (missing.value.status_code, missing.value.detail) == (
        forbidden.value.status_code,
        forbidden.value.detail,
    )


def _asset(owner_id: int = 10) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        user_id=owner_id,
        mime_type="image/png",
        file_name="test.png",
        storage_path="tests/media/test.png",
    )


def test_chat_file_route_applies_shared_object_authorization() -> None:
    async def run():
        with (
            patch.object(
                media_auth,
                "get_user_role_slugs",
                AsyncMock(return_value=["connections_full_administrator"]),
            ),
            patch.object(chat, "read_media_bytes", AsyncMock(return_value=b"secret")),
        ):
            await chat.media_file(
                7,
                request=SimpleNamespace(headers={}),
                user=SimpleNamespace(id=20),
                db=FakeDb(_asset()),
            )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 404


def test_chat_delete_route_requires_cross_user_write_permission() -> None:
    db = FakeDb(_asset())

    async def run():
        with patch.object(
            media_auth,
            "get_user_role_slugs",
            AsyncMock(return_value=["api_keys_full_administrator"]),
        ):
            await chat.delete_media(7, user=SimpleNamespace(id=20), db=db)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 404
    assert db.deleted is None


def test_reference_image_route_applies_shared_object_authorization() -> None:
    async def run():
        with (
            patch.object(
                media_auth,
                "get_user_role_slugs",
                AsyncMock(return_value=["connections_full_administrator"]),
            ),
            patch.object(images, "read_media_bytes", AsyncMock(return_value=b"secret")),
        ):
            await images.resolve_reference_image_for_upstream(
                FakeDb(_asset()),
                SimpleNamespace(id=20),
                "/api/chat/media/7/file",
            )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 404
    assert exc.value.detail == "Reference image not found"
