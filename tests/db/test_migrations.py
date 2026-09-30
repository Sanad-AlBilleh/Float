import sqlite3

import pytest

from app.db.connection import connect
from app.db.migrations import MIGRATIONS_DIR, apply_migrations, initialize_database

ALL_VERSIONS = sorted(path.stem for path in MIGRATIONS_DIR.glob("*.sql"))
EXPECTED_SLUGS = [
    "groceries", "eating_out", "transport", "housing", "utilities", "subscriptions",
    "study", "leisure", "health", "travel", "other",
]


def test_fixed_categories_are_seeded(conn):
    rows = conn.execute("SELECT slug FROM categories ORDER BY id").fetchall()
    assert [row["slug"] for row in rows] == EXPECTED_SLUGS


def test_categories_cannot_be_renamed_or_deleted(conn):
    with pytest.raises(sqlite3.IntegrityError, match="fixed"):
        conn.execute("UPDATE categories SET name = 'Food' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError, match="fixed"):
        conn.execute("DELETE FROM categories WHERE id = 11")


def test_migrations_are_applied_once(conn):
    assert apply_migrations(conn) == []
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ALL_VERSIONS
    assert versions[0] == "0001_foundation"


def test_connection_enforces_foreign_keys_and_waits_for_locks(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_failed_migration_leaves_no_trace(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_good.sql").write_text("CREATE TABLE a (x INTEGER) STRICT;", encoding="utf-8")
    (directory / "0002_bad.sql").write_text(
        "CREATE TABLE b (x INTEGER) STRICT;\nINSERT INTO missing VALUES (1);", encoding="utf-8"
    )
    conn = connect(tmp_path / "db.sqlite3")
    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(conn, directory)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "a" in tables and "b" not in tables
    assert [row[0] for row in conn.execute("SELECT version FROM schema_migrations")] == ["0001_good"]
    assert not conn.in_transaction
    conn.close()


def test_unexpected_file_names_are_rejected(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "init.sql").write_text("SELECT 1;", encoding="utf-8")
    conn = connect(tmp_path / "db.sqlite3")
    with pytest.raises(ValueError, match="init.sql"):
        apply_migrations(conn, directory)
    conn.close()


def test_initialize_database_creates_directory_and_enables_wal(tmp_path):
    db_path = tmp_path / "nested" / "float.sqlite3"
    assert initialize_database(db_path) == ALL_VERSIONS
    assert initialize_database(db_path) == []
    conn = connect(db_path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
