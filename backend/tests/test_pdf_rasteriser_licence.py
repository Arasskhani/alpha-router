"""The PDF rasteriser is BSD-licensed, and stays that way.

PyMuPDF is AGPL-3.0 or a commercial Artifex licence. It was imported in one
function, for one job - rendering a page to a bitmap for OCR - while all text
extraction already went through ``pypdf`` (BSD). PDFium via ``pypdfium2``
(BSD-3-Clause / Apache-2.0) does the same job; measured on Latin, Persian and
mixed scans before the swap, the OCR text was identical and peak memory the
same.

These tests make the swap permanent: no module in ``app`` may import MuPDF,
and the rasteriser that is in use must be the one the licence position rests
on.
"""

from __future__ import annotations

import ast
import importlib.metadata as metadata
from io import BytesIO
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[1] / "app"
_REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"
_FORBIDDEN = {"pymupdf", "fitz"}


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_nothing_in_the_application_imports_mupdf():
    offenders = sorted(
        str(path.relative_to(_APP.parent)) for path in _APP.rglob("*.py") if _imports_of(path) & _FORBIDDEN
    )
    assert offenders == [], f"MuPDF (AGPL / commercial) is imported by: {offenders}"


def test_mupdf_is_not_a_declared_dependency():
    lines = [line.split("#", 1)[0].strip().lower() for line in _REQUIREMENTS.read_text().splitlines()]
    assert not any(line.startswith("pymupdf") for line in lines), "PyMuPDF is still in requirements.txt"


def test_the_rasteriser_in_use_is_bsd_licensed():
    licence = metadata.metadata("pypdfium2").get("License-Expression") or metadata.metadata("pypdfium2").get("License")
    assert licence and "BSD" in licence, f"pypdfium2 reports licence {licence!r}"


def test_the_rasteriser_renders_a_grayscale_page_at_the_requested_dpi():
    """The one thing the OCR path needs from it."""

    import pypdfium2 as pdfium
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)  # A4 in points
    buffer = BytesIO()
    writer.write(buffer)

    document = pdfium.PdfDocument(buffer.getvalue())
    page = document[0]
    bitmap = page.render(scale=150 / 72, grayscale=True)
    image = bitmap.to_pil().convert("L")

    assert image.mode == "L"
    assert image.size[0] == pytest.approx(595 * 150 / 72, abs=1)
    assert image.size[1] == pytest.approx(842 * 150 / 72, abs=1)
    image.close()
    bitmap.close()
    page.close()
    document.close()
