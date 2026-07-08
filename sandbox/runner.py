"""In-sandbox executor for the Alpha Router code interpreter.

Runs inside a disposable, network-less, read-only container. Reads a JSON payload
from stdin, materializes workspace files into /tmp/work, executes the user code
with stdout/stderr captured, and writes a single JSON result line to stdout.

This process holds NO application secrets and has NO network access (enforced by
the container flags in the caller). It is intentionally dependency-light.
"""

import contextlib
import io
import json
import os
import signal
import sys
import traceback

WORKDIR = "/tmp/work"
MAX_STREAM_CHARS = 200_000
EXEC_TIMEOUT_SECONDS = 25  # defense-in-depth; caller also enforces a wall-clock timeout


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Timeout()


def _emit(stdout: str, stderr: str, exit_code: int) -> None:
    if len(stdout) > MAX_STREAM_CHARS:
        stdout = stdout[:MAX_STREAM_CHARS] + "\n[…output truncated in sandbox…]"
    if len(stderr) > MAX_STREAM_CHARS:
        stderr = stderr[:MAX_STREAM_CHARS] + "\n[…stderr truncated in sandbox…]"
    sys.__stdout__.write(json.dumps({"stdout": stdout, "stderr": stderr, "exit_code": exit_code}))
    sys.__stdout__.flush()


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as exc:  # noqa: BLE001
        _emit("", f"sandbox payload decode error: {exc}", 1)
        return

    code = str(payload.get("code") or "")
    files = payload.get("files") or {}

    try:
        os.makedirs(WORKDIR, exist_ok=True)
        os.chdir(WORKDIR)
    except Exception as exc:  # noqa: BLE001
        _emit("", f"sandbox workspace error: {exc}", 1)
        return

    if isinstance(files, dict):
        for name, content in files.items():
            safe = os.path.basename(str(name)).strip() or "data.txt"
            try:
                with open(os.path.join(WORKDIR, safe), "w", encoding="utf-8") as fh:
                    fh.write(str(content))
            except Exception:  # noqa: BLE001
                pass

    out, err = io.StringIO(), io.StringIO()
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

    _emit(out.getvalue(), err.getvalue(), exit_code)


if __name__ == "__main__":
    main()
