"""Sandboxed Python code interpreter for in-app chat."""

from __future__ import annotations

import ast
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path

PYTHON_BLOCK_RE = re.compile(r"```(?:python|py)\s*\n([\s\S]*?)```", re.IGNORECASE)
ATTACH_PREFIX = "__NITRO_ATTACH_JSON__:"
FILE_SECTION_RE = re.compile(r"---\s+([^\n]+?)\s+---\n", re.MULTILINE)
MAX_CODE_OUTPUT_CHARS = 50_000
MAX_WORKSPACE_FILE_BYTES = 512_000
CODE_TIMEOUT_SECONDS = 20
MAX_CODE_ITERATIONS = 3

BLOCKED_ROOT_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "shutil",
        "pathlib",
        "importlib",
        "ctypes",
        "multiprocessing",
        "pickle",
        "sqlite3",
        "http",
        "urllib",
        "requests",
        "httpx",
        "builtins",
        "pty",
        "fcntl",
        "resource",
        "signal",
        "tempfile",
    }
)

CODE_INTERPRETER_SYSTEM = (
    "You have access to a Python code interpreter in NITRO (pandas, json, math, statistics, re, csv, datetime). "
    "When calculations, data analysis, or parsing would help, write Python in a ```python fenced block. "
    "NITRO runs the last ```python block automatically and returns stdout/stderr. "
    "Write self-contained code; attachment files from the user are placed in the working directory under their filenames. "
    "Use English-only comments in Python code unless the user explicitly asks for Persian/Farsi comments. "
    "Keep all code LTR (standard Python layout) even when using Persian comments. "
    "After execution, summarize results clearly for the user."
)


def code_interpreter_system_message() -> str:
    return CODE_INTERPRETER_SYSTEM


def extract_last_python_block(text: str) -> str | None:
    matches = PYTHON_BLOCK_RE.findall(text or "")
    if not matches:
        return None
    code = matches[-1].strip()
    return code or None


def validate_python_code(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"Invalid Python syntax: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = (alias.name or "").split(".")[0]
                if root in BLOCKED_ROOT_MODULES:
                    raise ValueError(f"Import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BLOCKED_ROOT_MODULES:
                raise ValueError(f"Import not allowed: {node.module}")


def workspace_files_from_messages(messages: list[dict]) -> dict[str, str]:
    """Collect text attachment / document sections for the sandbox working directory."""
    files: dict[str, str] = {}

    def add_file(name: str, content: str) -> None:
        safe = Path(name).name.strip() or "data.txt"
        if not safe or safe in files:
            return
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_WORKSPACE_FILE_BYTES:
            content = encoded[:MAX_WORKSPACE_FILE_BYTES].decode("utf-8", errors="ignore")
        files[safe] = content

    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            if content.startswith(ATTACH_PREFIX):
                try:
                    payload = json.loads(content[len(ATTACH_PREFIX) :])
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict):
                    for att in payload.get("attachments") or []:
                        if not isinstance(att, dict):
                            continue
                        name = str(att.get("name") or "data.txt")
                        if att.get("kind") == "document" and att.get("text"):
                            add_file(name, str(att["text"]))
                continue
            parts = FILE_SECTION_RE.split(content)
            if len(parts) >= 3:
                for i in range(1, len(parts), 2):
                    name = parts[i].strip()
                    body = parts[i + 1] if i + 1 < len(parts) else ""
                    if name and body.strip():
                        add_file(name, body.strip())
        elif isinstance(content, list):
            text_bits: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_bits.append(str(part.get("text") or ""))
            merged = "\n".join(t for t in text_bits if t.strip())
            if merged:
                parts = FILE_SECTION_RE.split(merged)
                if len(parts) >= 3:
                    for i in range(1, len(parts), 2):
                        name = parts[i].strip()
                        body = parts[i + 1] if i + 1 < len(parts) else ""
                        if name and body.strip():
                            add_file(name, body.strip())
    return files


def _format_execution_result(stdout: str, stderr: str, exit_code: int) -> str:
    out = (stdout or "").strip()
    err = (stderr or "").strip()
    if len(out) > MAX_CODE_OUTPUT_CHARS:
        out = out[:MAX_CODE_OUTPUT_CHARS] + "\n[…output truncated…]"
    if len(err) > MAX_CODE_OUTPUT_CHARS:
        err = err[:MAX_CODE_OUTPUT_CHARS] + "\n[…stderr truncated…]"
    lines = ["Code interpreter execution result:"]
    if out:
        lines.append(f"stdout:\n{out}")
    if err:
        lines.append(f"stderr:\n{err}")
    if exit_code != 0 and not err:
        lines.append(f"exit_code: {exit_code}")
    if len(lines) == 1:
        lines.append("(no output)")
    return "\n".join(lines)


async def run_python_sandbox(code: str, workspace_files: dict[str, str] | None = None) -> str:
    validate_python_code(code)
    workspace_files = workspace_files or {}

    with tempfile.TemporaryDirectory(prefix="nitro-code-") as tmp:
        root = Path(tmp)
        for name, content in workspace_files.items():
            path = root / Path(name).name
            path.write_text(content, encoding="utf-8")

        script = root / "nitro_user_code.py"
        prelude = (
            "import json, math, statistics, re, csv, io\n"
            "from datetime import datetime\n"
            "try:\n    import pandas as pd\n"
            "except ImportError:\n    pd = None\n\n"
        )
        script.write_text(prelude + code + "\n", encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(script),
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=CODE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return "Code interpreter error: execution timed out (20s limit)."

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        return _format_execution_result(stdout, stderr, proc.returncode or 0)


def format_code_output_for_chat(result: str) -> str:
    return f"\n\n---\n**Code output:**\n```text\n{result.strip()}\n```\n\n"
