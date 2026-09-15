"""Dependency readiness for the /ready probe.

/health is a constant liveness answer on purpose (it must never leak layout
or fingerprintable details). /ready is what the container healthcheck and a
load balancer should use: it says whether this worker can actually serve a
request right now.

Two tiers:
- *required* (database, redis): failure -> HTTP 503. Without these no chat
  turn can be authenticated, rate-limited or billed.
- *degraded* (qdrant, object storage): reported in the body but do not fail
  the probe. Knowledge retrieval and media are features, not the process; a
  restart loop would not fix an unreachable Qdrant and would take chat down
  with it.

Every check has its own short timeout so a hung dependency cannot stall the
probe past the healthcheck's own deadline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.config import get_settings

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0
REQUIRED = ("database", "redis")
DEGRADED = ("qdrant", "object_storage")


@dataclass
class CheckResult:
    name: str
    ok: bool
    required: bool
    latency_ms: float
    detail: str | None = None


@dataclass
class ReadinessReport:
    ready: bool
    checks: list[CheckResult] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "status": "ready" if self.ready else "unavailable",
            "checks": {
                c.name: {
                    "ok": c.ok,
                    "required": c.required,
                    "latency_ms": round(c.latency_ms, 1),
                    **({"detail": c.detail} if c.detail else {}),
                }
                for c in self.checks
            },
        }


async def _timed(name: str, required: bool, coro) -> CheckResult:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=CHECK_TIMEOUT_SECONDS)
        return CheckResult(name, True, required, (time.perf_counter() - start) * 1000)
    except TimeoutError:
        return CheckResult(name, False, required, (time.perf_counter() - start) * 1000, "timeout")
    except Exception as exc:  # noqa: BLE001 - the probe must report, not raise
        # Keep the detail short and free of connection strings.
        return CheckResult(name, False, required, (time.perf_counter() - start) * 1000, type(exc).__name__)


async def _check_database() -> None:
    from app.database import engine

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis() -> None:
    from app.core.redis_client import get_redis

    # The shared pool: a broken pooled connection is exactly what the probe
    # should notice, and the 2s timeouts on the client bound it.
    if not await get_redis().ping():
        raise RuntimeError("PING returned false")


async def _check_qdrant() -> None:
    import httpx

    settings = get_settings()
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    async with httpx.AsyncClient(timeout=1.5, headers=headers) as client:
        resp = await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz")
        resp.raise_for_status()


async def _check_object_storage() -> None:
    from app.services.object_storage_service import _client

    settings = get_settings()
    # boto3 is synchronous; keep it off the event loop.
    await asyncio.to_thread(_client().head_bucket, Bucket=settings.s3_bucket)


async def readiness_report() -> ReadinessReport:
    results = await asyncio.gather(
        _timed("database", True, _check_database()),
        _timed("redis", True, _check_redis()),
        _timed("qdrant", False, _check_qdrant()),
        _timed("object_storage", False, _check_object_storage()),
    )
    ready = all(r.ok for r in results if r.required)
    for r in results:
        if not r.ok:
            (logger.warning if r.required else logger.info)(
                "readiness: %s %s (%s)", r.name, "FAILED" if r.required else "degraded", r.detail
            )
    return ReadinessReport(ready=ready, checks=list(results))
