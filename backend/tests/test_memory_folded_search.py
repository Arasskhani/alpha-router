"""Lexical memory search reads both sides folded the same way.

The question's terms were folded (Arabic ي and ك as Persian ی and ک, Persian
digits as 0-9) and the memory's text was not: a fact typed on an Arabic
keyboard, or with Persian digits, was never found by its words. Each memory
now keeps its text folded beside it (``content_search``), and the terms are
compared with that.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.chat import UserMemory
from app.models.project import Project, ProjectMemory
from app.services.project_memory_service import _auto_lexical_rows
from app.services.user_memory_service import _lexical_rows, create_memory, update_memory
from app.utils.text_normalize import fold_for_search

_BACKEND = Path(__file__).resolve().parents[1]
REVISION = "9240933e581a"

# The same fact as someone typing on an Arabic keyboard, with Persian digits, would store it.
ARABIC_TYPED = "كد پستي من ۱۲۳۴۵ است"
ZWNJ = "‌"

CASES = [
    ("كد ملي", "کد ملی"),
    ("۱۴۰۳ و ١٤٠٣", "1403 و 1403"),
    (f"می{ZWNJ}خواهم", "میخواهم"),
    ("Lives in TEHRAN", "lives in tehran"),
    ("مُحَمَّد", "محمد"),
    ("مسأله", "مساله"),
    ("خـــوب", "خوب"),
    ("مدرسة", "مدرسه"),
    ("  two   spaces  ", "two spaces"),
]


def _revision():
    path = next((_BACKEND / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_rev_{REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestFolding:
    @pytest.mark.parametrize(("typed", "folded"), CASES)
    def test_letters_digits_joiners_marks_and_case_compare_equal(self, typed, folded):
        assert fold_for_search(typed) == folded

    @pytest.mark.parametrize(("typed", "_folded"), CASES)
    def test_the_revision_folds_as_the_app_does(self, typed, _folded):
        assert _revision()._fold(typed) == fold_for_search(typed)


class TestPersonalMemory:
    async def test_is_found_by_its_words_however_it_was_typed(self, db_session, user):
        await create_memory(db_session, user.id, ARABIC_TYPED, origin="manual")
        await db_session.commit()
        for question in ("کد پستی من چنده؟", "zip 12345", "پستي"):
            rows = await _lexical_rows(db_session, user.id, question, limit=5)
            assert [row.content for row in rows] == [ARABIC_TYPED], question

    async def test_keeps_its_folded_text_in_step_with_its_text(self, db_session, user):
        payload, _created = await create_memory(db_session, user.id, "User lives in Shiraz", origin="manual")
        await update_memory(db_session, user.id, payload["id"], content="User lives in كرج")
        await db_session.commit()
        row = await db_session.get(UserMemory, payload["id"])
        assert row.content_search == "user lives in کرج"
        assert [r.id for r in await _lexical_rows(db_session, user.id, "کرج", limit=5)] == [row.id]
        assert await _lexical_rows(db_session, user.id, "Shiraz", limit=5) == []


class TestProjectMemory:
    async def test_is_found_by_its_words_however_it_was_typed(self, db_session, user):
        db_session.add(
            Project(
                id="proj-fold",
                name="Billing",
                status="active",
                visibility="private",
                created_by_user_id=user.id,
                revision=1,
                acl_version=1,
            )
        )
        await db_session.flush()
        db_session.add(
            ProjectMemory(
                id=str(uuid.uuid4()),
                project_id="proj-fold",
                content="تحويل نسخهٔ ۲ در آبان",
                content_hash=uuid.uuid4().hex,
                source_type="auto_chat",
                enabled=True,
            )
        )
        await db_session.commit()
        rows = await _auto_lexical_rows(db_session, "proj-fold", "تحویل نسخه 2 کی است؟", limit=5)
        assert [row.content for row in rows] == ["تحويل نسخهٔ ۲ در آبان"]


class TestTheRevision:
    @pytest.fixture
    def database(self, tmp_path):
        engine = sa.create_engine(f"sqlite:///{tmp_path / 'memories.sqlite'}")
        with engine.begin() as conn:
            for table in ("user_memories", "project_memories"):
                conn.execute(sa.text(f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY, content TEXT NOT NULL)"))
            for index in range(1, 1_203):
                conn.execute(
                    sa.text("INSERT INTO user_memories (id, content) VALUES (:id, :content)"),
                    {"id": f"m{index:05d}", "content": f"{ARABIC_TYPED} {index}"},
                )
            conn.execute(sa.text("INSERT INTO project_memories (id, content) VALUES ('p1', 'كيف')"))
        yield engine
        engine.dispose()

    def _run(self, engine, monkeypatch, step: str) -> None:
        module = _revision()
        with engine.begin() as conn:
            monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
            getattr(module, step)()

    def test_folds_every_row_in_batches_and_goes_back(self, database, monkeypatch):
        self._run(database, monkeypatch, "upgrade")
        with database.connect() as conn:
            rows = conn.execute(sa.text("SELECT id, content, content_search FROM user_memories")).fetchall()
            assert len(rows) == 1_202
            assert all(row.content_search == fold_for_search(row.content) for row in rows)
            assert conn.execute(sa.text("SELECT content_search FROM project_memories")).scalar_one() == "کیف"
        # Running it again changes nothing and finds nothing left to fold.
        self._run(database, monkeypatch, "upgrade")
        self._run(database, monkeypatch, "downgrade")
        with database.connect() as conn:
            columns = {c["name"] for c in sa.inspect(conn).get_columns("user_memories")}
        assert "content_search" not in columns
