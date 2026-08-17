"""Isolated parser subprocess entrypoint.

The parent process supplies source bytes over stdin. This runner disables
network APIs before loading document libraries and emits bounded JSON only.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import socket
import sys
from pathlib import Path


class _NetworkDisabledError(OSError):
    pass


def _network_disabled(*_args, **_kwargs):
    raise _NetworkDisabledError("Network access is disabled in the parser sandbox")


def _disable_network() -> None:
    class DisabledSocket:
        def __init__(self, *_args, **_kwargs):
            _network_disabled()

    socket.socket = DisabledSocket  # type: ignore[assignment]
    socket.create_connection = _network_disabled  # type: ignore[assignment]
    socket.getaddrinfo = _network_disabled  # type: ignore[assignment]
    socket.gethostbyname = _network_disabled  # type: ignore[assignment]
    socket.gethostbyname_ex = _network_disabled  # type: ignore[assignment]


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--file-name", required=True)
    parser.add_argument("--mime-type", default="")
    args = parser.parse_args()
    _disable_network()
    backend_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(backend_root))
    data = sys.stdin.buffer.read()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from app.services.knowledge_file_service import (
                UnsafeDocumentError,
                parse_document,
                validate_document,
            )
    except Exception as exc:  # noqa: BLE001 - subprocess boundary reports imports safely
        sys.stderr.write(f"ERROR:{type(exc).__name__}:{str(exc)[:500]}")
        return 4
    try:
        with contextlib.redirect_stdout(sys.stderr):
            validated = validate_document(
                file_name=args.file_name,
                data=data,
                claimed_mime_type=args.mime_type,
            )
            parsed = parse_document(data, validated)
    except UnsafeDocumentError as exc:
        sys.stderr.write(f"UNSAFE:{str(exc)[:1000]}")
        return 3
    except Exception as exc:  # noqa: BLE001 - subprocess boundary must map parser crashes
        sys.stderr.write(f"ERROR:{type(exc).__name__}:{str(exc)[:500]}")
        return 4
    payload = {
        "segments": [
            {
                "text": segment.text,
                "page_number": segment.page_number,
                "section": segment.section,
            }
            for segment in parsed.segments
        ],
        "character_count": parsed.character_count,
        "metadata": parsed.metadata,
        "security_flags": list(parsed.security_flags),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
