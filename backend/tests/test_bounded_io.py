"""Boundary tests for shared untrusted I/O readers."""

import asyncio
import base64
import io
from unittest.mock import patch

import httpx
import pytest
from fastapi import UploadFile

from app.services.bounded_io import (
    BoundedIOError,
    RequestBodyLimitMiddleware,
    bounded_get_bytes,
    decode_data_url_bounded,
    read_http_response_bounded,
    read_upload_bounded,
)
from app.services.ssrf_guard import SSRFBlockedError


def test_upload_reader_accepts_exact_limit_and_rejects_one_byte_over() -> None:
    exact = UploadFile(filename="exact.bin", file=io.BytesIO(b"x" * 8))
    over = UploadFile(filename="over.bin", file=io.BytesIO(b"x" * 9))
    assert asyncio.run(read_upload_bounded(exact, max_bytes=8)) == b"x" * 8
    with pytest.raises(BoundedIOError):
        asyncio.run(read_upload_bounded(over, max_bytes=8))


def test_data_url_checks_encoded_and_decoded_boundaries() -> None:
    exact = "data:application/octet-stream;base64," + base64.b64encode(b"123456").decode()
    assert decode_data_url_bounded(exact, max_decoded_bytes=6)[0] == b"123456"
    with pytest.raises(BoundedIOError):
        decode_data_url_bounded(exact, max_decoded_bytes=5)
    with pytest.raises(BoundedIOError, match="Invalid base64"):
        decode_data_url_bounded("data:text/plain;base64,%%%%", max_decoded_bytes=100)
    with pytest.raises(BoundedIOError):
        decode_data_url_bounded("not-a-data-url", max_decoded_bytes=100)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


def test_http_reader_caps_chunked_body_without_content_length() -> None:
    stream = ChunkStream([b"1234", b"56789"])
    response = httpx.Response(200, stream=stream)
    with pytest.raises(BoundedIOError):
        asyncio.run(read_http_response_bounded(response, max_bytes=8))
    assert stream.closed


def test_http_reader_accepts_exact_limit_and_rejects_declared_oversize() -> None:
    exact = httpx.Response(200, content=b"12345678")
    assert asyncio.run(read_http_response_bounded(exact, max_bytes=8)) == b"12345678"
    declared = httpx.Response(
        200,
        headers={"content-length": "9"},
        stream=ChunkStream([b"1"]),
    )
    with pytest.raises(BoundedIOError):
        asyncio.run(read_http_response_bounded(declared, max_bytes=8))


def test_request_middleware_caps_chunked_body_without_content_length() -> None:
    sent = []
    chunks = [b"x" * (512 * 1024), b"x" * (512 * 1024 + 1)]

    async def receive():
        body = chunks.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(chunks)}

    async def send(message):
        sent.append(message)

    async def drain(scope, receive, send):
        del scope
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})

    scope = {
        "type": "http",
        "path": "/api/chat/media/store",
        "headers": [],
    }
    middleware = RequestBodyLimitMiddleware(drain)
    with patch(
        "app.services.request_body_limit_service.effective_request_body_limit_bytes",
        return_value=1024 * 1024,
    ):
        asyncio.run(middleware(scope, receive, send))
    assert any(message.get("status") == 413 for message in sent)


def test_bounded_get_revalidates_each_manual_redirect_hop() -> None:
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "https://cdn.example/image"})
        return httpx.Response(200, content=b"safe", headers={"content-type": "image/png"})

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        ) as client:
            with (
                patch("app.services.ssrf_guard.assert_url_safe") as validate,
                patch("app.services.ssrf_guard.assert_response_target_safe"),
            ):
                body, mime = await bounded_get_bytes(
                    client,
                    "https://public.example/start",
                    max_bytes=10,
                )
                assert [call.args[0] for call in validate.call_args_list] == [
                    "https://public.example/start",
                    "https://cdn.example/image",
                ]
                return body, mime

    assert asyncio.run(run()) == (b"safe", "image/png")
    assert requested == ["https://public.example/start", "https://cdn.example/image"]


def test_bounded_get_blocks_redirect_before_second_request() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("app.services.ssrf_guard.assert_response_target_safe"):
                await bounded_get_bytes(client, "https://public.example/", max_bytes=10)

    with (
        patch(
            "app.services.ssrf_guard._resolve_hosts",
            return_value=["93.184.216.34"],
        ),
        patch("app.services.ssrf_guard._private_ranges_allowed", return_value=False),
        pytest.raises(SSRFBlockedError),
    ):
        asyncio.run(run())
    assert requests == 1


def _run_middleware(path: str, body: bytes, *, content_type: str):
    """Drive RequestBodyLimitMiddleware with one chunked (no Content-Length) body."""
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        del scope
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = {
        "type": "http",
        "path": path,
        "headers": [(b"content-type", content_type.encode())],
    }
    asyncio.run(RequestBodyLimitMiddleware(app)(scope, receive, send))
    return sent


def test_json_routes_get_the_small_ceiling_and_upload_routes_the_large_one() -> None:
    five_mib = b"{" + b" " * (5 * 1024 * 1024) + b"}"
    with (
        patch(
            "app.services.request_body_limit_service.effective_request_body_limit_bytes",
            return_value=1024 * 1024 * 1024,
        ),
        patch(
            "app.services.request_body_limit_service.get_settings",
            return_value=type("S", (), {"max_json_body_bytes": 4 * 1024 * 1024})(),
        ),
    ):
        # Pre-auth JSON route: 5 MiB must be refused although the upload ceiling is 1 GiB.
        sent = _run_middleware("/api/auth/login", five_mib, content_type="application/json")
        assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [413]

        # Chat completions may carry inline images: same 5 MiB passes.
        sent = _run_middleware("/api/chat/completions", five_mib, content_type="application/json")
        assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [200]

        # Multipart upload route: passes too.
        sent = _run_middleware(
            "/api/admin/knowledge/bases/1/documents", five_mib, content_type="multipart/form-data; boundary=x"
        )
        assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [200]


def test_no_second_response_start_when_handler_already_answered() -> None:
    sent: list[dict] = []
    chunks = [b"x" * 1024, b"x" * (200 * 1024)]

    async def receive():
        body = chunks.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(chunks)}

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        del scope
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while (await receive()).get("more_body"):
            pass

    scope = {"type": "http", "path": "/api/auth/login", "headers": []}
    with patch(
        "app.services.request_body_limit_service.request_body_limit_for",
        return_value=64 * 1024,
    ):
        asyncio.run(RequestBodyLimitMiddleware(app)(scope, receive, send))
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert len(starts) == 1 and starts[0]["status"] == 200


def test_published_limit_is_cached_by_mtime(tmp_path, monkeypatch) -> None:
    from app.services import request_body_limit_service as svc

    monkeypatch.setattr(svc, "request_body_limit_path", lambda: tmp_path / "request-body-limit.json")
    monkeypatch.setattr(svc, "_published_cache", (0.0, None, None))
    reads = {"n": 0}
    real = svc.read_published_request_body_limit_mb

    def counting():
        reads["n"] += 1
        return real()

    monkeypatch.setattr(svc, "read_published_request_body_limit_mb", counting)
    (tmp_path / "request-body-limit.json").write_text('{"request_body_mb": 64}', encoding="utf-8")

    assert svc.effective_request_body_limit_bytes() == 64 * 1024 * 1024
    for _ in range(50):
        svc.effective_request_body_limit_bytes()
    assert reads["n"] == 1, "one parse per TTL window, not one per request"
