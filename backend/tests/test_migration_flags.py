from app.services.migration_flags import value_is_migration_completed


def test_value_is_migration_completed():
    assert value_is_migration_completed("true")
    assert value_is_migration_completed("1")
    assert not value_is_migration_completed(None)
    assert not value_is_migration_completed("false")
