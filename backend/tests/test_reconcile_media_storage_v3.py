"""Tests for media storage v3 reconciliation survivor planning."""

from types import SimpleNamespace

from app.services.storage_migration_service import _plan_media_reconcile_survivors, _MediaTargetState


def _row(row_id: int, user_id: int):
    return SimpleNamespace(id=row_id, user_id=user_id)


def _target(digest: str):
    return _MediaTargetState(
        digest=digest,
        new_key=f"cdn/u/user/{digest}.png",
        mime="image/png",
        size=100,
        blob=b"x",
        old_path="old",
    )


def test_plan_keeps_newest_id_when_same_content_hash():
    rows = [_row(5, 1), _row(32, 1)]
    targets = {5: _target("abc"), 32: _target("abc")}
    keep, delete = _plan_media_reconcile_survivors(rows, targets)
    assert keep == {32}
    assert delete == {5}


def test_plan_keeps_distinct_hashes():
    rows = [_row(5, 1), _row(32, 1)]
    targets = {5: _target("abc"), 32: _target("def")}
    keep, delete = _plan_media_reconcile_survivors(rows, targets)
    assert keep == {5, 32}
    assert delete == set()


def test_plan_scoped_per_user():
    rows = [_row(1, 7), _row(2, 8)]
    targets = {1: _target("same"), 2: _target("same")}
    keep, delete = _plan_media_reconcile_survivors(rows, targets)
    assert keep == {1, 2}
    assert delete == set()
