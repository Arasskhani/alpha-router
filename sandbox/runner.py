"""In-sandbox executor for the Alpharouter code interpreter.

Runs inside a disposable, network-less, read-only container. Reads a JSON payload
from stdin, materializes workspace files into /tmp/work, executes the user code
with stdout/stderr captured, and writes a single JSON result line to stdout.

This process holds NO application secrets and has NO network access (enforced by
the container flags in the caller). It is intentionally dependency-light.
"""

import base64
import binascii
import contextlib
import hashlib
import io
import json
import os
import signal
import sys
import traceback
import unicodedata

WORKDIR = "/tmp/work"
MAX_STREAM_CHARS = 200_000
EXEC_TIMEOUT_SECONDS = 25  # defense-in-depth; caller also enforces a wall-clock timeout
MAX_ARTIFACTS = 5
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 10 * 1024 * 1024

# Mirror of backend/app/sandbox/filenames.py. This image ships no application
# code, so the policy is duplicated here on purpose; keep both in sync.
MAX_FILENAME_CHARS = 128
MAX_FILENAME_BYTES = 255
_ALLOWED_FORMAT_CHARS = frozenset({"\u200c", "\u200d"})
_ALLOWED_PUNCTUATION = frozenset("._- ()")
_RESERVED_NAMES = frozenset({".", ".."})
_ALLOWED_CATEGORIES = frozenset({"Mn", "Mc"})

_ARTIFACT_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _normalize_filename(name):
    return unicodedata.normalize("NFC", name).strip()


def _is_allowed_filename_char(ch):
    if ch in _ALLOWED_PUNCTUATION or ch in _ALLOWED_FORMAT_CHARS:
        return True
    if ch.isalnum():
        return True
    return unicodedata.category(ch) in _ALLOWED_CATEGORIES


def _is_safe_filename(name):
    """Accept any script but reject deceptive or non-local path components."""
    if not isinstance(name, str) or not name:
        return False
    if name != _normalize_filename(name):
        return False
    if name in _RESERVED_NAMES:
        return False
    if "/" in name or "\\" in name:
        return False
    if name[0] in "-." or name[-1] in " .":
        return False
    if len(name) > MAX_FILENAME_CHARS:
        return False
    if len(name.encode("utf-8")) > MAX_FILENAME_BYTES:
        return False
    return all(_is_allowed_filename_char(ch) for ch in name)


class _Timeout(Exception):
    pass


class _BoundedTextIO(io.StringIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.truncated = False

    def write(self, value: str) -> int:
        text = str(value)
        remaining = max(0, self.limit - self.tell())
        if len(text) > remaining:
            self.truncated = True
        if remaining:
            super().write(text[:remaining])
        return len(text)

    def bounded_value(self, marker: str) -> str:
        return self.getvalue() + (marker if self.truncated else "")


def _on_alarm(signum, frame):
    raise _Timeout()


def _emit(
    stdout: str,
    stderr: str,
    exit_code: int,
    artifacts: list[dict] | None = None,
) -> None:
    if len(stdout) > MAX_STREAM_CHARS:
        stdout = stdout[:MAX_STREAM_CHARS] + "\n[…output truncated in sandbox…]"
    if len(stderr) > MAX_STREAM_CHARS:
        stderr = stderr[:MAX_STREAM_CHARS] + "\n[…stderr truncated in sandbox…]"
    sys.__stdout__.write(
        json.dumps(
            {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "artifacts": artifacts or [],
            }
        )
    )
    sys.__stdout__.flush()


def _validate_artifact_content(name: str, content: bytes) -> str | None:
    suffix = os.path.splitext(name)[1].lower()
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            return "invalid PDF signature"
        return None
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return "text artifact is not UTF-8"
    if "\x00" in text:
        return "text artifact contains NUL bytes"
    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError:
            return "invalid JSON"
    return None


def _collect_artifacts(input_names: set[str]) -> tuple[list[dict], list[str]]:
    artifacts: list[dict] = []
    warnings: list[str] = []
    total = 0
    try:
        with os.scandir(WORKDIR) as iterator:
            entries = sorted(iterator, key=lambda item: item.name.lower())
    except OSError as exc:
        return [], [f"artifact scan failed: {exc}"]

    for entry in entries:
        # Report the canonical spelling in case the filesystem returns a
        # decomposed form of the name the code wrote.
        name = _normalize_filename(entry.name)
        if entry.name in input_names or name in input_names:
            continue
        suffix = os.path.splitext(name)[1].lower()
        if suffix not in _ARTIFACT_MIME_BY_SUFFIX:
            continue
        if not _is_safe_filename(name):
            warnings.append(f"artifact skipped (unsafe filename): {name!r}")
            continue
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            warnings.append(f"artifact skipped (not a regular file): {name}")
            continue
        if len(artifacts) >= MAX_ARTIFACTS:
            warnings.append(f"artifact skipped (maximum {MAX_ARTIFACTS} files): {name}")
            continue

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(entry.path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                content = handle.read(MAX_ARTIFACT_BYTES + 1)
        except OSError as exc:
            warnings.append(f"artifact skipped (read failed): {name}: {exc}")
            continue
        if not content:
            warnings.append(f"artifact skipped (empty file): {name}")
            continue
        if len(content) > MAX_ARTIFACT_BYTES:
            warnings.append(f"artifact skipped (over 5 MiB): {name}")
            continue
        if total + len(content) > MAX_TOTAL_ARTIFACT_BYTES:
            warnings.append(f"artifact skipped (aggregate limit): {name}")
            continue
        content_error = _validate_artifact_content(name, content)
        if content_error:
            warnings.append(f"artifact skipped ({content_error}): {name}")
            continue

        total += len(content)
        artifacts.append(
            {
                "name": name,
                "mime_type": _ARTIFACT_MIME_BY_SUFFIX[suffix],
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    return artifacts, warnings


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as exc:  # noqa: BLE001
        _emit("", f"sandbox payload decode error: {exc}", 1)
        return

    code = str(payload.get("code") or "")
    files = payload.get("files") or {}
    files_b64 = payload.get("files_b64") or {}

    try:
        os.makedirs(WORKDIR, exist_ok=True)
        os.chdir(WORKDIR)
    except Exception as exc:  # noqa: BLE001
        _emit("", f"sandbox workspace error: {exc}", 1)
        return

    input_names: set[str] = set()
    if isinstance(files, dict):
        for name, content in files.items():
            safe = _normalize_filename(os.path.basename(str(name)))
            if not _is_safe_filename(safe):
                continue
            input_names.add(safe)
            try:
                with open(os.path.join(WORKDIR, safe), "w", encoding="utf-8") as fh:
                    fh.write(str(content))
            except Exception:  # noqa: BLE001
                pass
    if isinstance(files_b64, dict):
        for name, encoded in files_b64.items():
            safe = _normalize_filename(os.path.basename(str(name)))
            # Text wins over binary for a shared name: the broker rejects the
            # duplicate upstream, this only keeps a hand-built payload from
            # silently replacing what the text channel already wrote.
            if not _is_safe_filename(safe) or safe in input_names:
                continue
            try:
                content = base64.b64decode(str(encoded), validate=True)
            except (ValueError, TypeError, binascii.Error):
                # The broker already validated the encoding; a corrupt entry
                # here must cost the run one missing file, not the whole run.
                continue
            input_names.add(safe)
            try:
                with open(os.path.join(WORKDIR, safe), "wb") as fh:
                    fh.write(content)
            except Exception:  # noqa: BLE001
                pass

    out = _BoundedTextIO(MAX_STREAM_CHARS)
    err = _BoundedTextIO(MAX_STREAM_CHARS)
    exit_code = 0

    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(EXEC_TIMEOUT_SECONDS)

    globals_ns: dict = {"__name__": "__main__", "__builtins__": __builtins__}
    try:
        compiled = compile(code, "<user_code>", "exec")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compiled, globals_ns, globals_ns)  # noqa: S102
    except _Timeout:
        err.write("\nsandbox: execution timed out.")
        exit_code = 124
    except SystemExit as exc:
        exit_code = int(exc.code) if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException:  # noqa: BLE001
        traceback.print_exc(file=err)
        exit_code = 1
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)

    artifacts: list[dict] = []
    if exit_code == 0:
        artifacts, artifact_warnings = _collect_artifacts(input_names)
        for warning in artifact_warnings:
            err.write(f"\nsandbox: {warning}")

    _emit(
        out.bounded_value("\n[…output truncated in sandbox…]"),
        err.bounded_value("\n[…stderr truncated in sandbox…]"),
        exit_code,
        artifacts,
    )


if __name__ == "__main__":
    main()
