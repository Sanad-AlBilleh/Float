"""SQLite connections with the pragmas Float requires on every connection (SRS §6.4)."""

import sqlite3
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection in autocommit mode; writes go through ``transaction()``.

    ``check_same_thread=False`` because FastAPI may run a request's dependency and its
    endpoint on different worker threads. Each connection still serves only one request.
    """
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def enable_wal(conn: sqlite3.Connection) -> str:
    """Switch the database file to write-ahead logging and return the resulting mode."""
    return conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
