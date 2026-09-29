"""Keep each memory's text folded for lexical search.

Revision ID: 9240933e581a
Revises: d1e2f3a4b5c6
Create Date: 2026-09-29

Lexical recall folded the question (Arabic ي and ك as Persian ی and ک,
Persian digits as 0-9) and compared it with the memory's text as it was
typed: "کد" never found "كد", "1403" never found "۱۴۰۳". Each memory now
carries ``content_search``, its text folded the same way as the question's
terms, and the app keeps it in step with the text.

The backfill folds in Python, in batches, with a copy of the folding as it
is today so that later changes to the app's folding do not change what this
revision did. A row it missed would still be found by its original text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9240933e581a"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("user_memories", "project_memories")
_COLUMN = "content_search"
_BATCH = 500

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DIACRITICS_RE = re.compile("[\u064b-\u065f\u0670]")
_FOLD = str.maketrans(
    {
        **{chr(0x06F0 + i): str(i) for i in range(10)},
        **{chr(0x0660 + i): str(i) for i in range(10)},
        "ي": "ی",
        "ك": "ک",
        "ى": "ی",
        "ة": "ه",
        "ۀ": "ه",
        "أ": "ا",
        "إ": "ا",
        "ٱ": "ا",
        "آ": "ا",
        "ؤ": "و",
        "ئ": "ی",
        "ـ": None,
    }
)


def _fold(text: str | None) -> str:
    """app.utils.text_normalize.fold_for_search, as of this revision."""
    raw = ("" if text is None else str(text)).replace("\u200c", "")
    cleaned = unicodedata.normalize("NFC", raw)
    cleaned = _CONTROL_RE.sub("", cleaned)
    cleaned = _DIACRITICS_RE.sub("", cleaned.replace("\u200d", "").translate(_FOLD))
    return _WHITESPACE_RE.sub(" ", cleaned).strip().casefold()


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _backfill(table: str) -> None:
    bind = op.get_bind()
    select = sa.text(f"SELECT id, content FROM {table} WHERE {_COLUMN} IS NULL ORDER BY id LIMIT :n")
    update = sa.text(f"UPDATE {table} SET {_COLUMN} = :folded WHERE id = :id")
    while True:
        rows = bind.execute(select, {"n": _BATCH}).fetchall()
        if not rows:
            return
        bind.execute(update, [{"id": row.id, "folded": _fold(row.content)} for row in rows])


def upgrade() -> None:
    for table in _TABLES:
        columns = _columns(table)
        if not columns:
            continue
        if _COLUMN not in columns:
            op.add_column(table, sa.Column(_COLUMN, sa.Text(), nullable=True))
        _backfill(table)


def downgrade() -> None:
    for table in _TABLES:
        if _COLUMN in _columns(table):
            op.drop_column(table, _COLUMN)
