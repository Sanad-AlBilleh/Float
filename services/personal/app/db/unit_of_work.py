"""One database transaction per write use case (SRS §6.4), now on SQL Server."""

from collections.abc import Iterator
from contextlib import contextmanager

from app.db.connection import Connection


@contextmanager
def transaction(conn: Connection) -> Iterator[Connection]:
    """Run the block between ``BEGIN TRANSACTION`` and ``COMMIT``; roll back on any exception.

    SQLite's ``BEGIN IMMEDIATE`` took the write lock up front. SQL Server locks rows as they are
    written instead; the ``version`` columns and unique constraints still stop two writers from
    overwriting each other, which is what the A1 rules relied on. Nesting is a bug.
    """
    if conn.in_transaction:
        raise RuntimeError("transaction() cannot be nested; pass the open connection instead")
    conn.execute("BEGIN TRANSACTION")
    conn.in_transaction = True
    try:
        yield conn
    except BaseException:
        conn.in_transaction = False
        conn.execute("IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION")
        raise
    else:
        conn.in_transaction = False
        conn.execute("COMMIT TRANSACTION")
