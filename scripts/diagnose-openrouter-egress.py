#!/usr/bin/env python3
"""Measure what it costs this host to open a connection to a provider.

Run it inside the app container when upstream calls fail with ConnectTimeout:

    docker compose cp scripts/diagnose-openrouter-egress.py alpha-router:/tmp/diag.py
    docker compose exec alpha-router python /tmp/diag.py

It answers three questions, in order:

1. Is DNS the slow part? (Docker's embedded resolver stalls are a classic.)
2. Is the TCP or the TLS handshake the slow part, and does it ever exceed the
   15 s connect budget the app allows?
3. Does keeping the connection alive avoid all of that? The video path forces
   ``Connection: close`` and disables keep-alive, so it pays 1-3 again for
   every poll — up to ~240 times per video. This prints both side by side.

Nothing is written and no API key is used: every request is an unauthenticated
GET that only needs the connection to be established.
"""

from __future__ import annotations

import socket
import ssl
import statistics
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "openrouter.ai"
PORT = 443
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
CONNECT_BUDGET = 15.0  # what the app allows today


def _resolve(host: str) -> tuple[float, list]:
    started = time.monotonic()
    infos = socket.getaddrinfo(host, PORT, type=socket.SOCK_STREAM)
    return time.monotonic() - started, infos


def fresh_handshake(host: str) -> tuple[float, float, float, str] | str:
    """(dns, tcp, tls, ip) for one brand-new connection, or an error string."""
    try:
        dns, infos = _resolve(host)
    except Exception as exc:  # noqa: BLE001 -- a diagnostic reports every failure mode
        return f"DNS FAILED: {type(exc).__name__}: {exc}"
    family, socktype, proto, _canon, addr = infos[0]
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(CONNECT_BUDGET)
    started = time.monotonic()
    try:
        sock.connect(addr)
        tcp = time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 -- a diagnostic reports every failure mode
        sock.close()
        return f"TCP FAILED after {time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}"
    started = time.monotonic()
    try:
        context = ssl.create_default_context()
        tls_sock = context.wrap_socket(sock, server_hostname=host)
        tls = time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 -- a diagnostic reports every failure mode
        sock.close()
        return f"TLS FAILED after {time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}"
    tls_sock.close()
    return dns, tcp, tls, addr[0]


def main() -> int:
    print(f"host={HOST} rounds={ROUNDS} connect_budget={CONNECT_BUDGET}s\n")

    print("A. One brand-new connection per request (what video does today)")
    totals: list[float] = []
    failures = 0
    for index in range(ROUNDS):
        result = fresh_handshake(HOST)
        if isinstance(result, str):
            failures += 1
            print(f"  {index + 1:>2}. {result}")
            continue
        dns, tcp, tls, ip = result
        total = dns + tcp + tls
        totals.append(total)
        flag = "  <-- OVER BUDGET" if total > CONNECT_BUDGET else ""
        print(f"  {index + 1:>2}. dns={dns:5.2f}s tcp={tcp:5.2f}s tls={tls:5.2f}s total={total:5.2f}s ip={ip}{flag}")

    if totals:
        print(
            f"\n  min={min(totals):.2f}s median={statistics.median(totals):.2f}s "
            f"max={max(totals):.2f}s failures={failures}/{ROUNDS}"
        )
    else:
        print(f"\n  every attempt failed ({failures}/{ROUNDS})")

    print("\nB. One connection reused for the same number of requests (what the fix does)")
    try:
        dns, infos = _resolve(HOST)
        family, socktype, proto, _canon, addr = infos[0]
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(CONNECT_BUDGET)
        started = time.monotonic()
        sock.connect(addr)
        tcp = time.monotonic() - started
        started = time.monotonic()
        tls_sock = ssl.create_default_context().wrap_socket(sock, server_hostname=HOST)
        tls = time.monotonic() - started
        print(f"  handshake once: dns={dns:.2f}s tcp={tcp:.2f}s tls={tls:.2f}s")
        request = (
            f"GET /api/v1/models HTTP/1.1\r\nHost: {HOST}\r\n"
            "User-Agent: alpharouter-egress-check\r\nConnection: keep-alive\r\n\r\n"
        ).encode()
        kept = 0
        for index in range(ROUNDS):
            started = time.monotonic()
            tls_sock.sendall(request)
            chunk = tls_sock.recv(65536)
            if not chunk:
                print(f"  {index + 1:>2}. connection closed by the server after {kept} request(s)")
                break
            kept += 1
            print(f"  {index + 1:>2}. reused connection, first byte in {time.monotonic() - started:5.2f}s")
        tls_sock.close()
        print(f"\n  {kept}/{ROUNDS} requests served over a single handshake")
    except Exception as exc:  # noqa: BLE001 -- a diagnostic reports every failure mode
        print(f"  keep-alive test failed: {type(exc).__name__}: {exc}")

    print("\nHow to read this:")
    print("  * dns consistently slow            -> the container's resolver, not OpenRouter")
    print("  * tcp/tls slow or failing at times -> the network path to Cloudflare")
    print("  * A unreliable but B clean         -> connection reuse alone fixes it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
