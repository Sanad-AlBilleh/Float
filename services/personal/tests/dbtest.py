"""A SQL Server test database for this service (Assignment 2 §5: CI never touches Azure SQL).

``TEST_DATABASE_URL`` names it, for example ``mssql://sa:<password>@localhost:1433/personal_test``. In CI it is
a GitHub Actions service container; locally it is the compose ``db`` container, and when the variable is not
set the SA password is read from the repository's .env. The database is created if it is missing and
migrated once per test run; every test then starts from empty tables.
"""

import os
from pathlib import Path
from urllib.parse import quote

from app.db.connection import connect
from app.db.migrations import apply_migrations

REPO_ROOT = Path(__file__).resolve().parents[3]

# Empties every table except the migration log and the health row, keeping the fixed categories, and
# restarts the IDs so tests can rely on them. Constraints and triggers are switched off while it runs
# (the append-only triggers would refuse the DELETE), then switched back on and re-checked.
RESET = """
DECLARE @sql NVARCHAR(MAX) = N'';
SELECT @sql += N'ALTER TABLE ' + QUOTENAME(name) + N' NOCHECK CONSTRAINT ALL; DISABLE TRIGGER ALL ON '
    + QUOTENAME(name) + N';' FROM sys.tables WHERE name NOT IN (N'schema_migrations', N'health_probe');
SELECT @sql += N'DELETE FROM ' + QUOTENAME(name)
    + CASE WHEN name = N'categories' THEN N' WHERE owner_user_id IS NOT NULL' ELSE N'' END + N';'
    FROM sys.tables WHERE name NOT IN (N'schema_migrations', N'health_probe');
SELECT @sql += N'ALTER TABLE ' + QUOTENAME(name) + N' WITH CHECK CHECK CONSTRAINT ALL; ENABLE TRIGGER ALL ON '
    + QUOTENAME(name) + N';' FROM sys.tables WHERE name NOT IN (N'schema_migrations', N'health_probe');
SELECT @sql += N'DBCC CHECKIDENT(' + QUOTENAME(t.name, '''') + N', RESEED, '
    + CASE WHEN t.name = N'categories' THEN N'11' ELSE N'0' END + N') WITH NO_INFOMSGS;'
    FROM sys.identity_columns AS ic JOIN sys.tables AS t ON t.object_id = ic.object_id
    WHERE ic.last_value IS NOT NULL;
EXEC sp_executesql @sql;
"""


def _dotenv_password() -> str | None:
    env = REPO_ROOT / ".env"
    if not env.is_file():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("MSSQL_SA_PASSWORD="):
            return line.partition("=")[2].strip()
    return None


def test_database_url(service: str) -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    password = os.environ.get("MSSQL_SA_PASSWORD") or _dotenv_password()
    if not password:
        raise RuntimeError("Set TEST_DATABASE_URL (or MSSQL_SA_PASSWORD) to run the database tests")
    return f"mssql://sa:{quote(password, safe='')}@localhost:1433/{service}_test"


def prepare(url: str) -> None:
    """Create the test database if needed and bring its schema up to date."""
    server, _, name = url.rpartition("/")
    master = connect(f"{server}/master", retries=3)
    try:
        master.run_batch(f"IF DB_ID(N'{name}') IS NULL CREATE DATABASE [{name}]")
    finally:
        master.close()
    conn = connect(url, retries=3)
    try:
        apply_migrations(conn)
    finally:
        conn.close()


def reset(conn) -> None:
    conn.run_batch(RESET)
