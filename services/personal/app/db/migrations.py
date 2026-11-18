"""Numbered T-SQL migrations, each applied exactly once, in order, at startup (Assignment 2 §4).

Files live in ``migrations/`` next to ``app/`` (``001_init.sql``, ``002_….sql``). A file is split into
batches on lines that say ``GO``, the same rule as sqlcmd, because some statements (CREATE TRIGGER)
must be alone in their batch. Each file and its ``schema_migrations`` row are one transaction, so a
failing migration leaves nothing behind and is tried again on the next start. Applied files are never
edited: a fix is a new file. Nothing here drops or recreates a table that holds data.
"""

import logging
import re
from pathlib import Path

from app.db.connection import Connection

logger = logging.getLogger("float.migrations")

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
_VERSION = re.compile(r"\d{3}_[a-z0-9_]+")
_GO = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)


def batches(script: str) -> list[str]:
    return [part.strip() for part in _GO.split(script) if part.strip()]


def apply_migrations(conn: Connection, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration in ``directory`` that is not yet recorded; return the versions applied."""
    conn.run_batch(
        "IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NULL "
        "CREATE TABLE dbo.schema_migrations (version NVARCHAR(100) NOT NULL PRIMARY KEY,"
        " applied_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    applied: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        version = path.stem
        if not _VERSION.fullmatch(version):
            raise ValueError(f"Unexpected migration file name: {path.name}")
        if version in done:
            continue
        conn.run_batch("BEGIN TRANSACTION")
        try:
            for batch in batches(path.read_text(encoding="utf-8")):
                conn.run_batch(batch)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
            conn.run_batch("COMMIT TRANSACTION")
        except BaseException:
            conn.run_batch("IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION")
            raise
        logger.info("migration applied: %s", path.name)
        applied.append(version)
    if not applied:
        logger.info("migrations: nothing to apply")
    return applied
