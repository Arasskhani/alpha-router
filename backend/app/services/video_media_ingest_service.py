"""Provider-neutral, SSRF-safe ingestion of generated video assets."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse


from app.services.bounded_io import decode_data_url_bounded
from app.services.ssrf_guard import assert_response_target_safe, assert_url_safe, safe_client
from app.services.storage_service import video_output_limit


def _host_allowed(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts)


async def fetch_video_asset(
    *,
    url: str,
    api_key: str | None = None,
    requires_auth: bool = False,
    allowed_hosts: tuple[str, ...] = (),
    max_bytes: int | None = None,
) -> tuple[bytes, str]:
    """Fetch an adapter result while preventing credential leakage and SSRF."""
    limit = int(max_bytes or video_output_limit())
    if url.startswith("data:"):
        return decode_data_url_bounded(url, max_decoded_bytes=limit)

    current = url
    for _ in range(4):
        assert_url_safe(current)
        if allowed_hosts and not _host_allowed(current, allowed_hosts):
            raise ValueError("Provider asset host is not allowlisted")
        headers: dict[str, str] = {}
        if requires_auth:
            if not api_key:
                raise ValueError("Provider asset requires credentials")
            headers["Authorization"] = f"Bearer {api_key}"
        async with safe_client() as client:
            async with client.stream("GET", current, headers=headers) as response:
                assert_response_target_safe(response)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Provider redirect has no location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise ValueError("Generated video exceeds configured size limit")
                    chunks.append(chunk)
                mime = (response.headers.get("content-type") or "video/mp4").split(";", 1)[0].strip().lower()
                blob = b"".join(chunks)
                if mime not in {"video/mp4", "video/webm"}:
                    if blob[4:8] == b"ftyp":
                        mime = "video/mp4"
                    elif blob[:4] == b"\x1aE\xdf\xa3":
                        mime = "video/webm"
                    else:
                        raise ValueError("Provider returned an unsupported video MIME type")
                return blob, mime
    raise ValueError("Too many provider redirects")
