"""Nothing acted on ``ephemeral_expires_at`` until now.

The column was set 15 minutes out when a private video was stored, but the only
thing that ever deleted the object was the consume-on-read in the download
handler. So a private video the user never downloaded was never deleted at all,
and removing consume-on-read without a reaper would have turned an occasional
leak into a permanent one.
"""

from __future__ import annotations

import datetime

import pytest

from app.models.video import VideoGenerationJob
from app.services import video_job_service


@pytest.fixture
def deleted(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("app.services.object_storage_service.delete_object", calls.append)
    return calls


async def _job(db_session, user, *, job_id: str, minutes: int) -> VideoGenerationJob:
    job = VideoGenerationJob(
        id=job_id,
        user_id=user.id,
        model_id="bytedance/seedance-1-pro",
        prompt="a cat",
        operation="generation",
        status="completed",
        persist=0,
        ephemeral_storage_path=f"cdn/private/{job_id}.mp4",
        ephemeral_expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes),
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def test_an_expired_video_object_is_deleted(db_session, user, session_factory, monkeypatch, deleted):
    monkeypatch.setattr(video_job_service, "AsyncSessionLocal", session_factory)
    expired = await _job(db_session, user, job_id="aaaaaaaa-0000-0000-0000-000000000001", minutes=-5)
    await db_session.commit()

    removed = await video_job_service.purge_expired_private_videos()

    assert removed == 1
    assert deleted == [f"cdn/private/{expired.id}.mp4"]
    await db_session.refresh(expired)
    assert expired.ephemeral_storage_path is None


async def test_a_live_video_is_left_alone(db_session, user, session_factory, monkeypatch, deleted):
    monkeypatch.setattr(video_job_service, "AsyncSessionLocal", session_factory)
    live = await _job(db_session, user, job_id="aaaaaaaa-0000-0000-0000-000000000002", minutes=10)
    await db_session.commit()

    removed = await video_job_service.purge_expired_private_videos()

    assert removed == 0
    assert deleted == []
    await db_session.refresh(live)
    assert live.ephemeral_storage_path is not None


async def test_the_scheduler_runs_it():
    """Without a registration the reaper is dead code and the leak is permanent."""

    from app.services import scheduler

    assert "job_purge_expired_private_videos" in scheduler.start_scheduler.__code__.co_names
