"""Artifact egress policy enforced inside the disposable sandbox."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER_PATH = Path(__file__).parents[2] / "sandbox" / "runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("alpha_router_sandbox_runner", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Boots the runner in a child interpreter exactly as the container does (JSON
# on stdin, one JSON line on stdout), with only WORKDIR redirected so the test
# never touches the real /tmp/work.
_BOOTSTRAP = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("alpha_router_sandbox_runner", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.WORKDIR = sys.argv[2]
module.main()
"""


def _run_runner(payload: dict, workdir: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, "-c", _BOOTSTRAP, str(RUNNER_PATH), str(workdir)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    return json.loads(completed.stdout.decode("utf-8").strip().splitlines()[-1])


def _sha256_of_workspace_file(name: str) -> str:
    return f"import hashlib\nprint(hashlib.sha256(open({name!r}, 'rb').read()).hexdigest())\n"


def test_runner_collects_only_new_allowlisted_regular_files(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "WORKDIR", str(tmp_path))

    (tmp_path / "input.csv").write_text("source,value\nx,1\n", encoding="utf-8")
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    (tmp_path / "report.pdf").write_bytes(pdf)
    (tmp_path / "summary.json").write_text('{"total": 1}', encoding="utf-8")
    (tmp_path / "ignored.bin").write_bytes(b"binary")
    (tmp_path / "invalid.pdf").write_bytes(b"not a pdf")
    (tmp_path / "folder.txt").mkdir()

    artifacts, warnings = runner._collect_artifacts({"input.csv"})

    assert [item["name"] for item in artifacts] == ["report.pdf", "summary.json"]
    assert base64.b64decode(artifacts[0]["content_base64"]) == pdf
    assert all(item["name"] != "input.csv" for item in artifacts)
    assert any("invalid PDF signature" in warning for warning in warnings)
    assert any("not a regular file" in warning for warning in warnings)


def test_runner_collects_non_english_artifact_names(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "WORKDIR", str(tmp_path))

    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    (tmp_path / "گزارش-مدیریتی.pdf").write_bytes(pdf)
    (tmp_path / "خلاصه.csv").write_text("name,value\na,1\n", encoding="utf-8")

    artifacts, warnings = runner._collect_artifacts(set())

    assert {item["name"] for item in artifacts} == {"گزارش-مدیریتی.pdf", "خلاصه.csv"}
    assert not any("unsafe filename" in warning for warning in warnings)


def test_runner_skips_bidi_spoofed_artifact_names(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "WORKDIR", str(tmp_path))

    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
    try:
        (tmp_path / "report\u202efdp.pdf").write_bytes(pdf)
    except OSError:  # pragma: no cover - filesystem refused the name
        pytest.skip("filesystem rejects BiDi control characters in names")

    artifacts, warnings = runner._collect_artifacts(set())

    assert artifacts == []
    assert any("unsafe filename" in warning for warning in warnings)


def test_runner_rejects_symlinks_and_size_overflow(tmp_path, monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(runner, "WORKDIR", str(tmp_path))
    monkeypatch.setattr(runner, "MAX_ARTIFACT_BYTES", 8)

    (tmp_path / "large.txt").write_text("x" * 9, encoding="utf-8")
    target = tmp_path / "target.txt"
    target.write_text("safe", encoding="utf-8")
    symlink_created = False
    try:
        (tmp_path / "link.txt").symlink_to(target)
        symlink_created = True
    except OSError:
        pass

    artifacts, warnings = runner._collect_artifacts(set())

    assert all(item["name"] not in {"large.txt", "link.txt"} for item in artifacts)
    assert any("over 5 MiB" in warning for warning in warnings)
    if symlink_created:
        assert any("not a regular file" in warning for warning in warnings)


def test_runner_materializes_binary_workspace_files_byte_exact(tmp_path):
    blob = bytes(range(256))  # not valid UTF-8, so a text write would mangle it
    payload = {
        "code": _sha256_of_workspace_file("blob.bin") + "print(open('notes.txt', encoding='utf-8').read())\n",
        "files": {"notes.txt": "hello"},
        "files_b64": {"blob.bin": base64.b64encode(blob).decode("ascii")},
    }
    result = _run_runner(payload, tmp_path)
    assert result["exit_code"] == 0, result["stderr"]
    assert result["stdout"].splitlines() == [hashlib.sha256(blob).hexdigest(), "hello"]
    assert (tmp_path / "blob.bin").read_bytes() == blob


def test_runner_skips_invalid_base64_entry_without_failing_the_run(tmp_path):
    payload = {
        "code": "import os\nprint(sorted(os.listdir('.')))\n",
        "files": {"a.txt": "x"},
        "files_b64": {"bad.bin": "this is not base64!", "good.bin": "AQID"},
    }
    result = _run_runner(payload, tmp_path)
    assert result["exit_code"] == 0, result["stderr"]
    assert result["stdout"].strip() == "['a.txt', 'good.bin']"
    assert not (tmp_path / "bad.bin").exists()
    assert (tmp_path / "good.bin").read_bytes() == b"\x01\x02\x03"


def test_runner_does_not_echo_binary_inputs_back_as_artifacts(tmp_path):
    # A binary input with an allow-listed suffix (.txt) would be picked up by
    # the artifact scan if it were not registered as an input.
    payload = {
        "code": "open('made.txt', 'w').write('new')\n",
        "files_b64": {"given.txt": base64.b64encode(b"given").decode("ascii")},
    }
    result = _run_runner(payload, tmp_path)
    assert result["exit_code"] == 0, result["stderr"]
    assert [item["name"] for item in result["artifacts"]] == ["made.txt"]


def test_runner_keeps_text_content_when_name_is_in_both_maps(tmp_path):
    payload = {
        "code": "print(open('same.txt', 'rb').read())\n",
        "files": {"same.txt": "text wins"},
        "files_b64": {"same.txt": base64.b64encode(b"binary loses").decode("ascii")},
    }
    result = _run_runner(payload, tmp_path)
    assert result["exit_code"] == 0, result["stderr"]
    assert result["stdout"].strip() == repr(b"text wins")
    assert (tmp_path / "same.txt").read_bytes() == b"text wins"


def test_runner_ignores_absent_or_non_dict_files_b64(tmp_path):
    without_key = _run_runner({"code": "print('ok')", "files": {}}, tmp_path)
    assert without_key["exit_code"] == 0 and without_key["stdout"].strip() == "ok"
    wrong_type = _run_runner({"code": "print('ok')", "files_b64": ["not", "a", "dict"]}, tmp_path)
    assert wrong_type["exit_code"] == 0 and wrong_type["stdout"].strip() == "ok"
