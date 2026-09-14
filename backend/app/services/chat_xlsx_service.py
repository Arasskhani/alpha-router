"""Render chat assistant content (markdown) to an Excel .xlsx file.

Security model:
- The caller is an authenticated user exporting their own chat content.
- ``openpyxl`` only constructs an OpenXML spreadsheet package; it does not
  execute macros, fetch network resources, or evaluate formulas from the
  markdown source beyond storing cell values as text/numbers.
- Tables are extracted structurally from markdown (pipe tables / ``csv``
  fences); raw HTML is never interpreted as markup.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


class ChatExportError(Exception):
    """Chat XLSX render failed."""


@dataclass(frozen=True)
class _Table:
    header: list[str]
    rows: list[list[str]]


_TABLE_BLOCK_RE = re.compile(
    r"(?:^|\n)([ \t]*\|[^\n]+\n[ \t]*\|[ \t]*:?-+:?[^\n]*(?:\n[ \t]*\|[^\n]+)*)",
)
_CSV_FENCE_RE = re.compile(r"```csv[ \t]*\r?\n([\s\S]*?)```", re.IGNORECASE)


def _split_pipe_row(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [c.strip() for c in raw.split("|")]


def _parse_markdown_table(block: str) -> _Table | None:
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    if len(lines) < 2:
        return None
    if not all(l.startswith("|") or l.endswith("|") for l in lines):
        return None
    sep_cells = _split_pipe_row(lines[1])
    if not sep_cells or not all(re.fullmatch(r":?-+:?", c) for c in sep_cells):
        return None
    header = _split_pipe_row(lines[0])
    rows = [_split_pipe_row(l) for l in lines[2:]]
    return _Table(header=header, rows=rows)


def extract_xlsx_tables(content: str) -> list[_Table]:
    """Extract tabular content for Excel export (same preference order as CSV)."""
    tables: list[_Table] = []
    for m in _TABLE_BLOCK_RE.finditer(content or ""):
        parsed = _parse_markdown_table(m.group(1))
        if parsed:
            tables.append(parsed)
    if tables:
        return tables

    for m in _CSV_FENCE_RE.finditer(content or ""):
        raw = m.group(1).strip()
        if not raw:
            continue
        lines = [l for l in raw.splitlines() if l.strip()]
        rows = [[c.strip() for c in l.split(",")] for l in lines]
        if rows:
            tables.append(_Table(header=rows[0], rows=rows[1:]))
    if tables:
        return tables

    text = (content or "").strip()
    if not text:
        return []
    return [_Table(header=["Content"], rows=[[line] for line in text.splitlines()])]


def _autosize_columns(ws, col_count: int, sample_rows: list[list[str]]) -> None:
    for idx in range(1, col_count + 1):
        letter = get_column_letter(idx)
        max_len = 8
        for row in sample_rows:
            if idx - 1 < len(row):
                max_len = max(max_len, min(len(row[idx - 1] or ""), 48))
        ws.column_dimensions[letter].width = max_len + 2


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value):
    """Neutralise spreadsheet formula injection in model-authored text.

    A cell starting with ``=``, ``+``, ``-`` or ``@`` is evaluated by Excel
    and LibreOffice (``=HYPERLINK(...)``, ``=WEBSERVICE(...)``, DDE). The text
    came from a chat reply the user asked to export, i.e. from a model that
    may have been steered by a document or web page. Prefix with an
    apostrophe so it stays literal text; numbers are left alone.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _write_table(ws, table: _Table, *, start_row: int = 1) -> int:
    """Write ``table`` starting at ``start_row``; return next free row index."""
    header_font = Font(bold=True)
    row_i = start_row
    for col_i, cell in enumerate(table.header, start=1):
        c = ws.cell(row=row_i, column=col_i, value=_safe_cell(cell))
        c.font = header_font
    row_i += 1
    for row in table.rows:
        for col_i, cell in enumerate(row, start=1):
            ws.cell(row=row_i, column=col_i, value=_safe_cell(cell))
        row_i += 1
    width_rows = [table.header, *table.rows[:40]]
    _autosize_columns(ws, max(len(table.header), 1), width_rows)
    return row_i


def render_chat_xlsx(*, content: str, title: str | None = None) -> bytes:
    """Render markdown ``content`` to a .xlsx byte string."""
    if not (content or "").strip():
        raise ChatExportError("content must not be empty")

    tables = extract_xlsx_tables(content)
    if not tables:
        raise ChatExportError("content must not be empty")

    wb = Workbook()
    # openpyxl creates one default sheet; reuse it for the first table.
    default = wb.active
    assert default is not None
    raw_title = (title or "Chat export").strip() or "Chat export"
    # Excel sheet titles: max 31 chars; forbid \ / * ? : [ ]
    sheet_title = re.sub(r'[\\/*?:\[\]]+', "_", raw_title)[:31] or "Chat export"
    default.title = sheet_title

    if len(tables) == 1:
        _write_table(default, tables[0])
    else:
        _write_table(default, tables[0])
        for i, table in enumerate(tables[1:], start=2):
            ws = wb.create_sheet(title=f"Table {i}"[:31])
            _write_table(ws, table)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
