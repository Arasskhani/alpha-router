"""A private video survives being watched.

The handler used to consume the file: it read the bytes, stamped
``ephemeral_consumed_at``, nulled the path, committed and deleted the object,
all in the same request. Every later request answered 404.

That is not a privacy control, it is a broken player. A ``<video>`` element
seeking issues a second request with a ``Range`` header and got a 404
mid-playback; a page refresh lost the video permanently - one the user had
already paid to generate.

``ephemeral_expires_at`` was always the honest control and was already being set
15 minutes out. Nothing acted on it, so the reaper is the other half of this
change: without it, a private video nobody downloads would never be deleted.
"""

from __future__ import annotations

import datetime

import pytest
from fastapi import HTTPException

from app.api.videos import _parse_single_range, get_private_video_file
from app.models.video import VideoGenerationJob

CONTENT = bytes(range(256)) * 8  # 2048 bytes


class _Request:
    def __init__(self, range_header: str | None = None) -> None:
        self.headers = {"range": range_header} if range_header else {}


@pytest.fixture(autouse=True)
def object_store(monkeypatch):
    store = {"cdn/private/video.mp4": CONTENT}
    deleted: list[str] = []

    def _get(key):
        if key not in store:
            raise FileNotFoundError(key)
        return store[key]

    monkeypatch.setattr("app.api.videos.oss.get_object_bytes", _get)
    monkeypatch.setattr("app.api.videos.oss.delete_object", deleted.append)
    return deleted


async def _job(db_session, user, *, expires_in_minutes: int = 15) -> VideoGenerationJob:
    job = VideoGenerationJob(
        id="11111111-2222-3333-4444-555555555555",
        user_id=user.id,
        model_id="bytedance/seedance-1-pro",
        prompt="a cat",
        operation="generation",
        status="completed",
        persist=0,
        ephemeral_storage_path="cdn/private/video.mp4",
        ephemeral_expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=expires_in_minutes),
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def test_watching_it_twice_works(db_session, user, object_store):
    job = await _job(db_session, user)

    first = await get_private_video_file(job.id, _Request(), user, db_session)
    second = await get_private_video_file(job.id, _Request(), user, db_session)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.body == CONTENT, "the second read used to 404"
    assert object_store == [], "the file was deleted by a read"


async def test_seeking_returns_a_partial_response(db_session, user):
    job = await _job(db_session, user)

    response = await get_private_video_file(job.id, _Request("bytes=100-199"), user, db_session)

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 100-199/{len(CONTENT)}"
    assert response.headers["content-length"] == "100"
    assert response.body == CONTENT[100:200]


async def test_a_whole_read_advertises_range_support(db_session, user):
    job = await _job(db_session, user)

    response = await get_private_video_file(job.id, _Request(), user, db_session)

    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(CONTENT))


async def test_an_expired_video_is_gone(db_session, user):
    job = await _job(db_session, user, expires_in_minutes=-1)

    with pytest.raises(HTTPException) as exc:
        await get_private_video_file(job.id, _Request(), user, db_session)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-99", (0, 99)),
        ("bytes=100-", (100, 2047)),
        ("bytes=-50", (1998, 2047)),
        ("bytes=0-99999", (0, 2047)),
        ("bytes=5000-6000", None),
        ("bytes=abc", None),
        ("bytes=0-99,200-299", None),
        ("items=0-99", None),
        (None, None),
    ],
)
def test_range_parsing(header, expected):
    assert _parse_single_range(header, 2048) == expected
