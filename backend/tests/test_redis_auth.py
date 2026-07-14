"""Phase 9: Redis auth wiring — password injection into the Redis URL."""

from app.config import build_redis_url


def test_password_injected_when_missing():
    url = build_redis_url("redis://redis:6379/0", "s3cr3t")
    assert url == "redis://:s3cr3t@redis:6379/0"


def test_password_injected_with_username():
    url = build_redis_url("redis://app@redis:6379/0", "s3cr3t")
    assert url == "redis://app:s3cr3t@redis:6379/0"


def test_existing_password_is_preserved():
    url = build_redis_url("redis://:existing@redis:6379/0", "s3cr3t")
    assert url == "redis://:existing@redis:6379/0"


def test_empty_password_leaves_url_unchanged():
    url = build_redis_url("redis://redis:6379/0", "")
    assert url == "redis://redis:6379/0"


def test_rediss_scheme_supported():
    url = build_redis_url("rediss://redis:6379/0", "s3cr3t")
    assert url == "rediss://:s3cr3t@redis:6379/0"


def test_non_redis_scheme_left_unchanged():
    url = build_redis_url("http://redis:6379/0", "s3cr3t")
    assert url == "http://redis:6379/0"


def test_empty_url_returned_unchanged():
    assert build_redis_url("", "s3cr3t") == ""
