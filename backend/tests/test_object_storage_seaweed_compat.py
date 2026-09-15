"""Contract/security-oriented tests for S3-compatible object storage (SeaweedFS)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.services import object_storage_service as oss


def test_media_object_key_cdn_layout(monkeypatch):
    monkeypatch.setenv("MEDIA_CDN_PREFIX", "cdn")
    from app.config import get_settings

    get_settings.cache_clear()
    key = oss.media_object_key("jdoe", "abc123", ".png")
    assert key == "cdn/u/jdoe/abc123.png"
    get_settings.cache_clear()


def test_verify_connection_message_mentions_seaweedfs():
    oss._client.cache_clear()
    with patch.object(oss, "_client") as client_factory:
        client = MagicMock()
        client.list_buckets.side_effect = EndpointConnectionError(endpoint_url="http://seaweedfs:8333")
        client_factory.return_value = client
        with patch("app.services.object_storage_service.get_settings") as gs:
            gs.return_value.s3_endpoint_url = "http://seaweedfs:8333"
            with pytest.raises(RuntimeError) as exc:
                oss.verify_connection()
    msg = str(exc.value)
    assert "Object storage unavailable" in msg
    assert "seaweedfs" in msg.lower()
    assert "docker compose up -d seaweedfs" in msg


def test_ensure_bucket_creates_when_missing():
    oss._client.cache_clear()
    client = MagicMock()
    not_found = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}},
        "HeadBucket",
    )
    client.head_bucket.side_effect = [not_found, None]
    client.create_bucket.return_value = {}
    with (
        patch.object(oss, "_client", return_value=client),
        patch("app.services.object_storage_service.get_settings") as gs,
    ):
        gs.return_value.s3_bucket = "alpha-router-media"
        gs.return_value.s3_endpoint_url = "http://seaweedfs:8333"
        with patch.object(oss, "verify_connection"):
            oss.ensure_bucket()
    client.create_bucket.assert_called_once_with(Bucket="alpha-router-media")


def test_client_uses_path_style_addressing():
    oss._client.cache_clear()
    with (
        patch("app.services.object_storage_service.boto3.client") as boto_client,
        patch("app.services.object_storage_service.get_settings") as gs,
    ):
        gs.return_value.s3_endpoint_url = "http://seaweedfs:8333"
        gs.return_value.s3_access_key = "k"
        gs.return_value.s3_secret_key = "s"
        gs.return_value.s3_region = "us-east-1"
        gs.return_value.s3_use_ssl = False
        oss._client()
        kwargs = boto_client.call_args.kwargs
        assert kwargs["endpoint_url"] == "http://seaweedfs:8333"
        assert kwargs["config"].s3 == {"addressing_style": "path"}
    oss._client.cache_clear()
