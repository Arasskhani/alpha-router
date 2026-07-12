"""Shared bounded readers for untrusted uploads, data URLs, and HTTP bodies."""

from __future__ import annotations

import base64
import binascii

import httpx
from fastapi import UploadFile
from fastapi.responses import JSONResponse

CHUNK_BYTES = 64 * 1024


class BoundedIOError(ValueError):
    pass


class _RequestTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Cap streamed request bytes even when Content-Length is absent."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from app.config import get_settings

        limit = clamp_limit(
            get_settings().max_request_body_bytes,
            minimum=1024 * 1024,
            maximum=128 * 1024 * 1024,
        )
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        raw_length = headers.get("content-length")
        if raw_length:
            try:
                declared = int(raw_length)
            except ValueError:
                declared = 0
            if declared > limit:
                response = JSONResponse(status_code=413, content={"detail": "Request body too large"})
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body") or b"")
                if received > limit:
                    raise _RequestTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestTooLarge:
            response = JSONResponse(status_code=413, content={"detail": "Request body too large"})
            await response(scope, receive, send)


def clamp_limit(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


async def read_upload_bounded(upload: UploadFile, *, max_bytes: int) -> bytes:
    output = bytearray()
    while True:
        chunk = await upload.read(CHUNK_BYTES)
        if not chunk:
            break
        output.extend(chunk)
        if len(output) > max_bytes:
            raise BoundedIOError(f"File is too large (max {max_bytes // (1024 * 1024)} MB).")
    return bytes(output)


def decode_data_url_bounded(data_url: str, *, max_decoded_bytes: int) -> tuple[bytes, str]:
    if not isinstance(data_url, str) or not data_url.startswith("data:") or "," not in data_url:
        raise BoundedIOError("Invalid data URL")
    head, encoded = data_url.split(",", 1)
    if ";base64" not in head.lower():
        raise BoundedIOError("Only base64 data URLs are supported")
    max_encoded = 4 * ((max_decoded_bytes + 2) // 3)
    if len(encoded) > max_encoded:
        raise BoundedIOError("Decoded data exceeds the allowed limit")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BoundedIOError("Invalid base64 data URL") from exc
    if len(decoded) > max_decoded_bytes:
        raise BoundedIOError("Decoded data exceeds the allowed limit")
    mime = head[5:].split(";", 1)[0].strip() or "application/octet-stream"
    return decoded, mime


async def read_http_response_bounded(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> bytes:
    raw_length = response.headers.get("content-length")
    if raw_length:
        try:
            declared_length = int(raw_length)
        except ValueError:
            declared_length = 0
        if declared_length > max_bytes:
            raise BoundedIOError("Remote response exceeds the allowed limit")

    output = bytearray()
    async for chunk in response.aiter_bytes(CHUNK_BYTES):
        output.extend(chunk)
        if len(output) > max_bytes:
            await response.aclose()
            raise BoundedIOError("Remote response exceeds the allowed limit")
    return bytes(output)


async def bounded_get_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
) -> tuple[bytes, str]:
    from app.services.ssrf_guard import assert_response_target_safe, assert_url_safe

    assert_url_safe(url)
    async with client.stream("GET", url) as response:
        assert_response_target_safe(response)
        response.raise_for_status()
        body = await read_http_response_bounded(response, max_bytes=max_bytes)
        mime = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()
        return body, mime
