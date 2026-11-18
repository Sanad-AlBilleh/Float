"""Versioned migrations: applied once, in order, each file in one transaction (Assignment 2 §4)."""

import pytest

from app.db.connection import IntegrityError
from app.db.migrations import MIGRATIONS_DIR, apply_migrations, batches


def applied(conn) -> list[str]:
    return [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]


def test_every_migration_file_is_recorded_and_a_second_run_applies_nothing(conn):
    assert applied(conn) == sorted(path.stem for path in MIGRATIONS_DIR.glob("*.sql"))
    assert apply_migrations(conn) == []


def test_audit_events_are_append_only(conn):
    conn.execute("INSERT INTO audit_events (entity_type, action, occurred_at) VALUES ('household', 'create', 'x')")
    with pytest.raises(IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_events SET action = 'tampered'")


def test_users_and_ledger_rows_are_plain_numbers_here(conn):
    """No foreign key points outside this database: users and transactions live in the personal service."""
    foreign = conn.execute(
        "SELECT OBJECT_NAME(parent_object_id), OBJECT_NAME(referenced_object_id) FROM sys.foreign_keys").fetchall()
    assert {row[1] for row in foreign} <= {"households", "shared_expenses", "household_bill_series"}


def test_batches_split_on_go_lines_only():
    script = "CREATE TABLE a (x INT);\nGO\nCREATE TRIGGER t ON a AFTER UPDATE AS SELECT 1; -- GOOD\n go \n"
    assert batches(script) == ["CREATE TABLE a (x INT);", "CREATE TRIGGER t ON a AFTER UPDATE AS SELECT 1; -- GOOD"]


@pytest.fixture
def scratch(conn, tmp_path):
    """Test-only migrations numbered 9xx, removed again afterwards."""
    yield tmp_path
    for table in ("zz_ok", "zz_bad"):
        conn.run_batch(f"IF OBJECT_ID(N'{table}', N'U') IS NOT NULL DROP TABLE {table}")
    conn.execute("DELETE FROM schema_migrations WHERE version LIKE '9%'")


def test_a_failed_migration_leaves_no_trace(conn, scratch):
    (scratch / "900_ok.sql").write_text("CREATE TABLE zz_ok (x INT);")
    (scratch / "901_bad.sql").write_text("CREATE TABLE zz_bad (x INT);\nGO\nINSERT INTO zz_bad VALUES ('not a number');")
    with pytest.raises(Exception):
        apply_migrations(conn, scratch)
    assert "900_ok" in applied(conn) and "901_bad" not in applied(conn)
    assert conn.execute("SELECT OBJECT_ID(N'zz_bad', N'U')").fetchone()[0] is None
    (scratch / "901_bad.sql").write_text("CREATE TABLE zz_bad (x INT);")  # a fixed file is tried again
    assert apply_migrations(conn, scratch) == ["901_bad"]


def test_unexpected_file_names_are_rejected(conn, scratch):
    (scratch / "1_init.sql").write_text("SELECT 1;")
    with pytest.raises(ValueError, match="1_init.sql"):
        apply_migrations(conn, scratch)
