"""Numbered SQL migrations, each applied exactly once in its own transaction (NFR-02)."""

import re
import sqlite3
from pathlib import Path

from app.db.connection import connect, enable_wal

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_VERSION = re.compile(r"\d{4}_[a-z0-9_]+")


def apply_migrations(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration in ``directory`` that is not yet recorded; return their versions."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version TEXT PRIMARY KEY, applied_at TEXT NOT NULL) STRICT"
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        version = path.stem
        if not _VERSION.fullmatch(version):
            raise ValueError(f"Unexpected migration file name: {path.name}")
        if version in done:
            continue
        script = path.read_text(encoding="utf-8")
        # executescript() cannot take parameters or join an open transaction, so the
        # script carries its own BEGIN/COMMIT. `version` is a validated file name.
        try:
            conn.executescript(
                f"BEGIN IMMEDIATE;\n{script}\n;\n"
                "INSERT INTO schema_migrations (version, applied_at) "
                f"VALUES ('{version}', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));\n"
                "COMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied


def initialize_database(db_path: Path) -> list[str]:
    """Create the data directory and database file, enable WAL, and apply migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        enable_wal(conn)
        return apply_migrations(conn)
    finally:
        conn.close()
