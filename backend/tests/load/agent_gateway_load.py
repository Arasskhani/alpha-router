"""Bounded async load gate for the OpenAI-compatible Agent gateway.

This script never prints prompts, API keys, or response bodies. It uses Private
Mode and disables persistence so repeated load runs do not create chat history.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field

import httpx


@dataclass
class Result:
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    status_codes: dict[str, int] = field(default_factory=dict)
    latencies_ms: list[float] = field(default_factory=list)
    first_token_ms: list[float] = field(default_factory=list)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return round(ordered[index], 2)


async def _one_request(
    client: httpx.AsyncClient,
    *,
    url: str,
    api_key: str,
    model: str,
    agent: str,
    prompt: str,
    cancel_after_first_token: bool,
) -> tuple[int, float, float | None, bool]:
    started = time.perf_counter()
    first_token: float | None = None
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "persist_chat": False,
        "private_mode": True,
        "agent_slug": agent,
        "alpharouter": {"session_id": f"load-{uuid.uuid4()}"},
    }
    async with client.stream(
        "POST",
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Client-App": "phase9-load-gate",
        },
        json=body,
    ) as response:
        if response.status_code >= 400:
            await response.aread()
            return (
                response.status_code,
                (time.perf_counter() - started) * 1000,
                None,
                False,
            )
        cancelled = False
        async for chunk in response.aiter_bytes():
            if chunk and first_token is None:
                first_token = (time.perf_counter() - started) * 1000
                if cancel_after_first_token:
                    cancelled = True
                    break
        return (
            response.status_code,
            (time.perf_counter() - started) * 1000,
            first_token,
            cancelled,
        )


async def _run(args: argparse.Namespace) -> Result:
    api_key = os.getenv("ALPHAROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ALPHAROUTER_API_KEY is required")
    result = Result()
    lock = asyncio.Lock()
    stop_at = time.monotonic() + args.duration_seconds
    limits = httpx.Limits(
        max_connections=max(args.concurrency * 2, 20),
        max_keepalive_connections=max(args.concurrency, 10),
    )
    timeout = httpx.Timeout(args.timeout_seconds)

    async with httpx.AsyncClient(
        verify=not args.insecure,
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
    ) as client:

        async def worker(worker_index: int) -> None:
            request_index = 0
            while time.monotonic() < stop_at:
                request_index += 1
                should_cancel = (
                    args.cancel_ratio > 0
                    and (worker_index + request_index)
                    % max(
                        1,
                        round(1 / args.cancel_ratio),
                    )
                    == 0
                )
                try:
                    status, latency, first, cancelled = await _one_request(
                        client,
                        url=args.url,
                        api_key=api_key,
                        model=args.model,
                        agent=args.agent,
                        prompt=args.prompt,
                        cancel_after_first_token=should_cancel,
                    )
                    async with lock:
                        result.status_codes[str(status)] = result.status_codes.get(str(status), 0) + 1
                        result.latencies_ms.append(latency)
                        if first is not None:
                            result.first_token_ms.append(first)
                        if cancelled:
                            result.cancelled += 1
                        elif 200 <= status < 300:
                            result.completed += 1
                        else:
                            result.failed += 1
                except (httpx.HTTPError, asyncio.TimeoutError):
                    async with lock:
                        result.failed += 1

        await asyncio.gather(*(worker(index) for index in range(args.concurrency)))
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a privacy-safe Alpharouter Agent gateway load gate.")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8080/v1/chat/completions",
    )
    parser.add_argument("--model", default="openrouter/auto")
    parser.add_argument("--agent", required=True)
    parser.add_argument(
        "--prompt",
        default="Reply with a short health-check acknowledgement.",
    )
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--cancel-ratio", type=float, default=0.05)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=10_000)
    parser.add_argument("--insecure", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not 1 <= args.concurrency <= 2_000:
        raise SystemExit("--concurrency must be between 1 and 2000")
    if not 1 <= args.duration_seconds <= 86_400:
        raise SystemExit("--duration-seconds must be between 1 and 86400")
    if not 0 <= args.cancel_ratio <= 1:
        raise SystemExit("--cancel-ratio must be between 0 and 1")
    started = time.perf_counter()
    result = asyncio.run(_run(args))
    elapsed = max(0.001, time.perf_counter() - started)
    attempted = result.completed + result.failed + result.cancelled
    non_cancelled = max(1, result.completed + result.failed)
    error_rate = result.failed / non_cancelled
    p95 = _percentile(result.latencies_ms, 0.95)
    report = {
        "attempted": attempted,
        "completed": result.completed,
        "failed": result.failed,
        "intentionally_cancelled": result.cancelled,
        "status_codes": result.status_codes,
        "requests_per_second": round(attempted / elapsed, 2),
        "error_rate": round(error_rate, 6),
        "latency_ms": {
            "mean": round(statistics.fmean(result.latencies_ms), 2) if result.latencies_ms else None,
            "p50": _percentile(result.latencies_ms, 0.50),
            "p95": p95,
            "p99": _percentile(result.latencies_ms, 0.99),
        },
        "first_token_ms": {
            "p50": _percentile(result.first_token_ms, 0.50),
            "p95": _percentile(result.first_token_ms, 0.95),
            "p99": _percentile(result.first_token_ms, 0.99),
        },
        "thresholds": {
            "max_error_rate": args.max_error_rate,
            "max_p95_ms": args.max_p95_ms,
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    passed = attempted > 0 and error_rate <= args.max_error_rate and p95 is not None and p95 <= args.max_p95_ms
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
