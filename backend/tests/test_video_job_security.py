"""Video job ownership and serialization helpers."""

import json


from app.models.video import VideoGenerationJob
from app.services.video_job_service import serialize_job


def test_serialize_job_hides_provider_polling_url():
    job = VideoGenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        user_id=1,
        model_id="google/veo-3.1-lite",
        operation="generation",
        status="running",
        prompt="sunrise",
        params_json=json.dumps({"duration": 4, "resolution": "720p"}),
        provider_job_id="prov-1",
        provider_polling_url="https://openrouter.ai/api/v1/videos/prov-1",
        media_asset_id=None,
    )
    payload = serialize_job(job)
    assert payload["id"] == job.id
    assert payload["status"] == "running"
    assert "provider_polling_url" not in payload
    assert "provider_job_id" not in payload


def test_serialize_job_optional_provider_id():
    job = VideoGenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        user_id=1,
        model_id="google/veo-3.1-lite",
        operation="generation",
        status="queued",
        prompt="sunrise",
        provider_job_id="prov-1",
    )
    payload = serialize_job(job, include_provider=True)
    assert payload["provider_job_id"] == "prov-1"
    assert "provider_polling_url" not in payload


def test_serialize_job_ingesting_has_no_media_url():
    """The 'ingesting' status must not expose a media_url yet."""
    job = VideoGenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        user_id=1,
        model_id="google/veo-3.1-lite",
        operation="generation",
        status="ingesting",
        prompt="sunrise",
    )
    payload = serialize_job(job)
    assert payload["status"] == "ingesting"
    assert payload["media_url"] is None


def test_serialize_job_completed_has_media_url():
    """The 'completed' status must include a media_url when media_asset_id is set."""
    job = VideoGenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        user_id=1,
        model_id="google/veo-3.1-lite",
        operation="generation",
        status="completed",
        prompt="sunrise",
        media_asset_id=42,
    )
    payload = serialize_job(job)
    assert payload["status"] == "completed"
    assert payload["media_url"] is not None


def test_serialize_job_exposes_request_log_id_from_params():
    job = VideoGenerationJob(
        id="11111111-1111-1111-1111-111111111111",
        user_id=1,
        model_id="google/veo-3.1-lite",
        operation="generation",
        status="completed",
        prompt="sunrise",
        params_json=json.dumps({"duration": 4, "request_log_id": 99}),
        media_asset_id=42,
    )
    payload = serialize_job(job)
    assert payload["request_log_id"] == 99
