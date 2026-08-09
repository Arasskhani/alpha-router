"""Artifact egress policy enforced inside the disposable sandbox."""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import pytest


def _load_runner():
    runner_path = Path(__file__).parents[2] / "sandbox" / "runner.py"
    spec = importlib.util.spec_from_file_location("alpha_router_sandbox_runner", runner_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
