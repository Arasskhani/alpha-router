"""Sandboxed Python code interpreter for in-app chat."""

from __future__ import annotations

import ast
import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.branding import PRODUCT_NAME
from app.sandbox.filenames import (
    MAX_FILENAME_BYTES,
    is_safe_filename,
    normalize_filename,
    scrub_filename_chars,
)
from app.services.chat_markers import ATTACHMENT_MESSAGE_PREFIX

PYTHON_BLOCK_RE = re.compile(r"```(?:python|py)\s*\n([\s\S]*?)```", re.IGNORECASE)
ATTACH_PREFIX = ATTACHMENT_MESSAGE_PREFIX
FILE_SECTION_RE = re.compile(r"---\s+([^\n]+?)\s+---\n", re.MULTILINE)
MAX_CODE_OUTPUT_CHARS = 50_000
MAX_WORKSPACE_FILE_BYTES = 512_000
DEFAULT_MAX_WORKSPACE_FILES = 500
DEFAULT_MAX_WORKSPACE_TOTAL_BYTES = 16 * 1024 * 1024
CODE_TIMEOUT_SECONDS = 20
MAX_CODE_ITERATIONS = 3
MAX_ARTIFACTS = 5
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 10 * 1024 * 1024
_SPREADSHEET_EXTENSIONS = frozenset({".xls", ".xlsx", ".xlsm"})
_MAX_WORKSPACE_STEM_CHARS = 100
_ARTIFACT_MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
}
_ALLOWED_TEXT_SUFFIXES = frozenset(
    {
        ".csv",
        ".tsv",
        ".txt",
        ".json",
        ".md",
        ".log",
        ".xml",
        ".yaml",
        ".yml",
        ".sql",
        ".ini",
        ".cfg",
        ".conf",
        ".toml",
    }
)

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


@dataclass(frozen=True)
class SandboxArtifact:
    name: str
    mime_type: str
    size_bytes: int
    sha256: str
    content: bytes


@dataclass(frozen=True)
class SandboxExecutionResult:
    output: str
    exit_code: int
    artifacts: tuple[SandboxArtifact, ...] = ()


@dataclass(frozen=True)
class WorkspaceFile:
    name: str
    size_bytes: int
    sha256: str
    content: str


@dataclass(frozen=True)
class WorkspaceManifest:
    files: tuple[WorkspaceFile, ...]
    total_bytes: int

    def as_files_dict(self) -> dict[str, str]:
        return {item.name: item.content for item in self.files}


class WorkspaceLimitError(ValueError):
    """Raised before provider billing when a Code Interpreter workspace is unsafe."""

    def __init__(
        self,
        message: str,
        *,
        file_count: int,
        total_bytes: int,
        max_files: int,
        max_total_bytes: int,
    ) -> None:
        super().__init__(message)
        self.file_count = file_count
        self.total_bytes = total_bytes
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes

    def api_detail(self) -> dict[str, object]:
        return {
            "code": "code_interpreter_workspace_limit",
            "message": str(self),
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "max_files": self.max_files,
            "max_total_bytes": self.max_total_bytes,
        }


CODE_INTERPRETER_SYSTEM = (
    f"You have access to a Python code interpreter in {PRODUCT_NAME} "
    "(pandas, numpy, ReportLab, arabic_reshaper, python-bidi, json, math, statistics, re, csv, datetime). "
    "When calculations, data analysis, or parsing would help, you MUST write Python in a ```python fenced block. "
    f"{PRODUCT_NAME} runs the last ```python block automatically and returns stdout/stderr. "
    "Without a ```python block, no code runs. "
    "Write self-contained code; attachment files from the user are placed in the working directory. "
    "Spreadsheet uploads (Excel) are pre-converted to CSV text and saved with a .csv extension — "
    "open them with pd.read_csv('filename.csv'), never pd.read_excel. "
    "The sandbox is locked down: os, sys, pathlib, subprocess, shutil, and network modules are BLOCKED "
    "and any import of them stops execution with 'Import not allowed'. "
    "Never import them and never touch the filesystem or environment directly. "
    "Read inputs by plain filename in the current directory (pd.read_csv('data.csv')) and write outputs by "
    "plain filename (open('report.pdf','wb'), df.to_csv('summary.csv', index=False)); do not build absolute paths "
    "and do not check whether a file exists. "
    "When the user asks for downloadable output, save new .pdf, .csv, .json, .txt, or .md files "
    "in the current working directory. The platform collects valid files and supplies download URLs. "
    "Output filenames may be written in any language, so a Persian or Arabic name such as "
    "'گزارش-مدیریتی.pdf' is accepted and downloadable — never rename a file to English and never "
    "tell the user that a non-English filename was rejected. Only avoid path separators, a leading "
    "dot or dash, and names longer than 128 characters. "
    "For charts inside a PDF, use ReportLab graphics (reportlab.graphics.charts, e.g. VerticalBarChart); "
    "matplotlib is NOT installed. "
    "For Persian/Arabic PDF text, the font 'DejaVuSans' is ALREADY registered with ReportLab — set "
    "fontName='DejaVuSans' (or use the pre-set ALPHA_DEJAVU_FONT variable) and shape text with arabic_reshaper "
    "plus python-bidi. Do not import os and do not check the font path. "
    "Never invent sandbox:, file:, /mnt/data, or Media URLs yourself. "
    "Use English-only comments in Python code unless the user explicitly asks for Persian/Farsi comments. "
    "Keep all code LTR (standard Python layout) even when using Persian comments. "
    "After execution, summarize results clearly for the user."
)

CODE_INTERPRETER_NUDGE = (
    "You have the code interpreter enabled but did not emit a ```python fenced block, "
    "so nothing was executed. Write a self-contained ```python block that performs the "
    "requested analysis or calculation now. "
    "If workspace files are listed below, read them from the current working directory. "
    "Spreadsheet data is provided as CSV — use pd.read_csv(filename). "
    "Do not reply with only prose until after you emit runnable code."
)


def code_interpreter_system_message() -> str:
    return CODE_INTERPRETER_SYSTEM


def code_interpreter_nudge_message(workspace_files: dict[str, str] | None = None) -> str:
    files = workspace_files or {}
    if not files:
        return CODE_INTERPRETER_NUDGE
    inventory = code_interpreter_workspace_message(files)
    return f"{CODE_INTERPRETER_NUDGE}\n\n{inventory}"


def code_interpreter_workspace_message(workspace_files: dict[str, str]) -> str:
    """Tell the model the exact sanitized filenames available in the sandbox CWD."""
    if not workspace_files:
        return ""
    lines = [
        "These attachment files are already in the sandbox working directory. "
        f"There are {len(workspace_files)} files. Use these exact filenames (do not invent names):",
    ]
    for name in sorted(workspace_files):
        size = len(workspace_files[name].encode("utf-8"))
        lines.append(f"- {name} ({size} bytes)")
    lines.append(
        "Example: df = pd.read_csv('filename.csv'); print(df.head()); print(df.describe())."
    )
    return "\n".join(lines)


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
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "__import__":
                raise ValueError("Dynamic import is not allowed")


def _bounded_stem(stem: str, *, suffix: str) -> str:
    """Trim a stem to the filename policy budget, counting UTF-8 bytes.

    Non-Latin scripts spend 2-4 bytes per character, so a character-only cap can
    still overflow the per-name byte limit and lose the whole name to a fallback.
    """
    trimmed = stem.strip("._- ")[:_MAX_WORKSPACE_STEM_CHARS].strip("._- ")
    budget = MAX_FILENAME_BYTES - len(suffix.encode("utf-8"))
    while trimmed and len(trimmed.encode("utf-8")) > budget:
        trimmed = trimmed[:-1].strip("._- ")
    return trimmed or "data"


def sanitize_workspace_filename(name: str, *, used: set[str] | None = None) -> str:
    """Normalize an attachment name for the sandbox while keeping its script.

    Persian, Arabic, Cyrillic and CJK names survive intact so the model can refer
    to the file the user actually uploaded; only characters the sandbox filename
    policy rejects are folded away. Spreadsheet uploads always end in ``.csv``
    because they are converted to CSV text before they reach the sandbox.
    """
    raw = normalize_filename(Path(name or "").name) or "data.txt"
    suffix = Path(raw).suffix.lower()
    stem = normalize_filename(Path(raw).stem) or "data"
    if suffix in _SPREADSHEET_EXTENSIONS:
        suffix = ".csv"
    elif suffix not in _ALLOWED_TEXT_SUFFIXES:
        if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix or ""):
            pass
        else:
            suffix = ".txt"

    safe_stem = _bounded_stem(scrub_filename_chars(stem), suffix=suffix)
    # Prefer a letter-led name so models do not trip on purely numeric filenames.
    if not any(ch.isalpha() for ch in safe_stem):
        safe_stem = f"data_{safe_stem}"
    candidate = normalize_filename(f"{safe_stem}{suffix}")
    if not is_safe_filename(candidate):
        candidate = f"data{suffix or '.txt'}"
        if not is_safe_filename(candidate):
            candidate = "data.csv"

    if used is not None:
        base_stem = Path(candidate).stem
        base_suffix = Path(candidate).suffix
        index = 2
        while candidate in used:
            candidate = f"{base_stem}_{index}{base_suffix}"
            index += 1
        used.add(candidate)
    return candidate


def build_workspace_manifest(
    messages: list[dict],
    *,
    max_files: int = DEFAULT_MAX_WORKSPACE_FILES,
    max_total_bytes: int = DEFAULT_MAX_WORKSPACE_TOTAL_BYTES,
    max_file_bytes: int = MAX_WORKSPACE_FILE_BYTES,
) -> WorkspaceManifest:
    """Build a validated workspace without silently dropping or truncating content."""
    files: list[WorkspaceFile] = []
    used_names: set[str] = set()
    total_bytes = 0

    def add_file(name: str, content: str) -> None:
        nonlocal total_bytes
        safe = sanitize_workspace_filename(name, used=used_names)
        if not safe:
            return
        encoded = content.encode("utf-8")
        next_count = len(files) + 1
        next_total = total_bytes + len(encoded)
        if next_count > max_files:
            raise WorkspaceLimitError(
                f"Code Interpreter workspace contains {next_count} files; the configured limit is {max_files}.",
                file_count=next_count,
                total_bytes=next_total,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )
        if len(encoded) > max_file_bytes:
            raise WorkspaceLimitError(
                f"Workspace file '{safe}' is {len(encoded)} bytes; the per-file limit is {max_file_bytes} bytes.",
                file_count=next_count,
                total_bytes=next_total,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )
        if next_total > max_total_bytes:
            raise WorkspaceLimitError(
                f"Code Interpreter workspace is {next_total} bytes; the configured total limit is {max_total_bytes} bytes.",
                file_count=next_count,
                total_bytes=next_total,
                max_files=max_files,
                max_total_bytes=max_total_bytes,
            )
        files.append(
            WorkspaceFile(
                name=safe,
                size_bytes=len(encoded),
                sha256=hashlib.sha256(encoded).hexdigest(),
                content=content,
            )
        )
        total_bytes = next_total

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
    return WorkspaceManifest(files=tuple(files), total_bytes=total_bytes)


def workspace_files_from_messages(
    messages: list[dict],
    *,
    max_files: int = DEFAULT_MAX_WORKSPACE_FILES,
    max_total_bytes: int = DEFAULT_MAX_WORKSPACE_TOTAL_BYTES,
    max_file_bytes: int = MAX_WORKSPACE_FILE_BYTES,
) -> dict[str, str]:
    """Compatibility wrapper returning the manifest as broker workspace files."""
    return build_workspace_manifest(
        messages,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        max_file_bytes=max_file_bytes,
    ).as_files_dict()


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


def _error_result(message: str) -> SandboxExecutionResult:
    return SandboxExecutionResult(output=message, exit_code=1)


def _validate_artifact_content(name: str, content: bytes) -> None:
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            raise ValueError("Invalid PDF artifact")
        return
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Artifact text must be UTF-8") from exc
    if "\x00" in text:
        raise ValueError("Artifact text contains NUL bytes")
    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON artifact") from exc


def _decode_broker_artifacts(value: object) -> tuple[SandboxArtifact, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_ARTIFACTS:
        raise ValueError("Invalid artifact list")

    total = 0
    artifacts: list[SandboxArtifact] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid artifact entry")
        name = item.get("name")
        mime_type = item.get("mime_type")
        encoded = item.get("content_base64")
        digest = item.get("sha256")
        size_bytes = item.get("size_bytes")
        if not is_safe_filename(name):
            raise ValueError("Invalid artifact filename")
        expected_mime = _ARTIFACT_MIME_BY_SUFFIX.get(Path(name).suffix.lower())
        if not expected_mime or mime_type != expected_mime:
            raise ValueError("Invalid artifact MIME type")
        if not isinstance(encoded, str) or not isinstance(digest, str):
            raise ValueError("Invalid artifact payload")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
            raise ValueError("Invalid artifact size")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid artifact encoding") from exc
        if not content or len(content) != size_bytes or len(content) > MAX_ARTIFACT_BYTES:
            raise ValueError("Invalid artifact size")
        total += len(content)
        if total > MAX_TOTAL_ARTIFACT_BYTES:
            raise ValueError("Artifact aggregate exceeds limit")
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != digest.lower():
            raise ValueError("Invalid artifact digest")
        _validate_artifact_content(name, content)
        artifacts.append(
            SandboxArtifact(
                name=name,
                mime_type=expected_mime,
                size_bytes=len(content),
                sha256=actual_digest,
                content=content,
            )
        )
    return tuple(artifacts)


def _collect_local_artifacts(
    root: Path,
    excluded_names: set[str],
) -> tuple[SandboxArtifact, ...]:
    artifacts: list[SandboxArtifact] = []
    total = 0
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        # Filesystems may hand back a decomposed spelling of the name the code
        # wrote, so compare and report the canonical form.
        name = normalize_filename(path.name)
        if path.name in excluded_names or name in excluded_names:
            continue
        if path.is_symlink() or not path.is_file():
            continue
        expected_mime = _ARTIFACT_MIME_BY_SUFFIX.get(path.suffix.lower())
        if not expected_mime or not is_safe_filename(name):
            continue
        if len(artifacts) >= MAX_ARTIFACTS:
            break
        try:
            if path.stat().st_size > MAX_ARTIFACT_BYTES:
                continue
            content = path.read_bytes()
        except OSError:
            continue
        if not content or len(content) > MAX_ARTIFACT_BYTES:
            continue
        if total + len(content) > MAX_TOTAL_ARTIFACT_BYTES:
            continue
        try:
            _validate_artifact_content(name, content)
        except ValueError:
            continue
        total += len(content)
        artifacts.append(
            SandboxArtifact(
                name=name,
                mime_type=expected_mime,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                content=content,
            )
        )
    return tuple(artifacts)


def _safe_broker_detail(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    if isinstance(detail, list):
        text = "; ".join(str(item) for item in detail)
    elif detail is None:
        return None
    else:
        text = str(detail)
    text = " ".join(text.split())
    if not text:
        return None
    return text[:200]


def _broker_http_error_message(response: httpx.Response) -> str:
    detail = _safe_broker_detail(response)
    status = response.status_code
    if status == 401:
        message = "Code interpreter error: sandbox broker authentication failed."
    elif status == 422:
        message = (
            "Code interpreter error: sandbox rejected the workspace payload "
            "(invalid filename or size)."
        )
    elif status == 429:
        message = "Code interpreter error: sandbox capacity is busy; try again shortly."
    elif status == 502:
        message = "Code interpreter error: sandbox container failed to run."
    elif status == 503:
        message = (
            "Code interpreter error: sandbox runtime unavailable "
            "(missing image or Docker access)."
        )
    else:
        message = f"Code interpreter error: sandbox execution unavailable (HTTP {status})."
    if detail and status in {422, 429, 502, 503}:
        return f"{message} Detail: {detail}"
    return message


# Pre-register the bundled DejaVu font so user code can build Persian/Arabic PDFs
# with ReportLab by name ('DejaVuSans') without importing os or probing the
# filesystem (both are blocked by validate_python_code).
DEJAVU_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_FONT_NAME = "DejaVuSans"

_PRELUDE = (
    "import json, math, statistics, re, csv, io\n"
    "from datetime import datetime\n"
    "try:\n    import pandas as pd\n"
    "except ImportError:\n    pd = None\n"
    f"ALPHA_DEJAVU_FONT_PATH = {DEJAVU_FONT_PATH!r}\n"
    f"ALPHA_DEJAVU_FONT = {DEJAVU_FONT_NAME!r}\n"
    "try:\n"
    "    from reportlab.pdfbase import pdfmetrics as _alpha_pdfmetrics\n"
    "    from reportlab.pdfbase.ttfonts import TTFont as _AlphaTTFont\n"
    "    _alpha_pdfmetrics.registerFont(_AlphaTTFont(ALPHA_DEJAVU_FONT, ALPHA_DEJAVU_FONT_PATH))\n"
    "except Exception:\n"
    "    pass\n\n"
)


async def run_python_sandbox(
    code: str,
    workspace_files: dict[str, str] | None = None,
) -> SandboxExecutionResult:
    """Execute user code and return bounded output plus validated artifacts.

    Uses the authenticated internal sandbox broker. A scrubbed subprocess is
    available only through an explicit development-only opt-in.
    """
    validate_python_code(code)
    workspace_files = workspace_files or {}

    from app.config import get_settings

    settings = get_settings()
    broker_url = (settings.code_sandbox_broker_url or "").strip()
    if broker_url:
        if len((settings.code_sandbox_broker_token or "").strip()) < 32:
            return _error_result(
                "Code interpreter error: sandbox broker authentication is not configured."
            )
        return await _run_via_broker(code, workspace_files, settings, broker_url)
    if (settings.code_sandbox_image or "").strip():
        return _error_result(
            "Code interpreter error: legacy sandbox image configuration requires the sandbox broker."
        )
    if settings.environment == "development" and settings.allow_insecure_code_subprocess:
        return await _run_in_subprocess(code, workspace_files)
    return _error_result("Code interpreter error: sandbox broker is required.")


async def _run_via_broker(
    code: str,
    workspace_files: dict[str, str],
    settings,
    broker_url: str,
) -> SandboxExecutionResult:
    """Submit and poll an explicit broker job; cancellation deletes the job."""
    from app.sandbox.executor import (
        DockerBrokerSandboxExecutor,
        SandboxExecutorError,
        SandboxJobCancelled,
    )

    timeout = int(settings.code_sandbox_timeout_seconds or CODE_TIMEOUT_SECONDS)
    token = (settings.code_sandbox_broker_token or "").strip()
    executor = DockerBrokerSandboxExecutor(
        base_url=broker_url,
        token=token,
        execution_timeout_seconds=timeout,
    )
    try:
        result = await executor.execute(
            _PRELUDE + code + "\n",
            workspace_files,
        )
    except httpx.RequestError:
        return _error_result("Code interpreter error: sandbox broker unavailable.")
    except SandboxJobCancelled:
        return _error_result("Code interpreter error: sandbox execution was cancelled.")
    except SandboxExecutorError as exc:
        if exc.status_code == 504:
            return _error_result("Code interpreter error: execution timed out.")
        if exc.status_code == 413:
            return _error_result(
                "Code interpreter error: sandbox input or output exceeds the allowed limit."
            )
        if exc.status_code == 422:
            detail = " ".join(str(exc.detail).split())[:200]
            return _error_result(
                "Code interpreter error: sandbox rejected the workspace payload "
                f"(invalid filename or size). Detail: {detail}"
            )
        if exc.status_code == 401:
            return _error_result(
                "Code interpreter error: sandbox broker authentication failed."
            )
        if exc.status_code == 429:
            detail = " ".join(str(exc.detail).split())[:200]
            return _error_result(
                "Code interpreter error: sandbox capacity is busy; try again shortly. "
                f"Detail: {detail}"
            )
        detail = " ".join(str(exc.detail).split())[:200]
        suffix = f" Detail: {detail}" if detail else ""
        if exc.status_code == 502:
            return _error_result(
                f"Code interpreter error: sandbox container failed to run.{suffix}"
            )
        if exc.status_code == 503:
            return _error_result(
                "Code interpreter error: sandbox runtime unavailable "
                f"(missing image or Docker access).{suffix}"
            )
        return _error_result(
            f"Code interpreter error: sandbox execution unavailable "
            f"(HTTP {exc.status_code}).{suffix}"
        )
    if not isinstance(result, dict):
        return _error_result("Code interpreter error: invalid sandbox response.")
    try:
        exit_code = int(result.get("exit_code") or 0)
        artifacts = _decode_broker_artifacts(result.get("artifacts"))
    except (TypeError, ValueError):
        return _error_result("Code interpreter error: invalid sandbox response.")

    return SandboxExecutionResult(
        output=_format_execution_result(
            str(result.get("stdout") or ""),
            str(result.get("stderr") or ""),
            exit_code,
        ),
        exit_code=exit_code,
        artifacts=artifacts if exit_code == 0 else (),
    )


async def _run_in_subprocess(
    code: str,
    workspace_files: dict[str, str],
) -> SandboxExecutionResult:
    """Legacy in-process execution (no container). Retained for dev/no-docker setups."""
    with tempfile.TemporaryDirectory(prefix="alpha-router-code-") as tmp:
        root = Path(tmp)
        for name, content in workspace_files.items():
            path = root / Path(name).name
            path.write_text(content, encoding="utf-8")

        script = root / "alpha_router_user_code.py"
        script.write_text(_PRELUDE + code + "\n", encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(script),
            cwd=str(root),
            env={
                "PATH": os.defpath,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
            },
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
            return _error_result("Code interpreter error: execution timed out (20s limit).")

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        exit_code = proc.returncode or 0
        artifacts = (
            _collect_local_artifacts(
                root,
                set(workspace_files) | {"alpha_router_user_code.py"},
            )
            if exit_code == 0
            else ()
        )
        return SandboxExecutionResult(
            output=_format_execution_result(stdout, stderr, exit_code),
            exit_code=exit_code,
            artifacts=artifacts,
        )


def format_code_output_for_chat(result: SandboxExecutionResult | str) -> str:
    output = result.output if isinstance(result, SandboxExecutionResult) else result
    return f"\n\n---\n**Code output:**\n```text\n{output.strip()}\n```\n\n"


def code_interpreter_error_hint(output: str) -> str:
    """Targeted remediation appended to a failed run so the model self-corrects.

    Returns an empty string when no specific guidance applies, so callers can
    conditionally include it in the follow-up message to the model.
    """
    text = (output or "").lower()
    if "import not allowed" in text or "dynamic import" in text:
        return (
            "Your code used a blocked import (such as os, sys, pathlib, subprocess, or shutil). "
            "These are unavailable in the sandbox. Do not access the filesystem or environment "
            "directly. Read attachment files by their plain filename in the current directory "
            "(e.g. pd.read_csv('data.csv')) and write outputs by plain filename "
            "(e.g. open('report.pdf', 'wb')). For PDF fonts, the font 'DejaVuSans' is already "
            "registered with ReportLab — set fontName='DejaVuSans' directly and never import os or "
            "check whether the font file exists. Rewrite the code without the blocked import."
        )
    if "no module named 'matplotlib'" in text or "modulenotfounderror" in text and "matplotlib" in text:
        return (
            "matplotlib is not installed. For charts inside a PDF, use ReportLab graphics "
            "(reportlab.graphics.charts, e.g. VerticalBarChart) instead."
        )
    return ""
