"""One database transaction per write use case (SRS §6.4)."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run the block between ``BEGIN IMMEDIATE`` and ``COMMIT``; roll back on any exception.

    IMMEDIATE takes the write lock up front, so two writers never deadlock while upgrading
    a read lock. Nesting is a bug: services receive the open connection instead.
    """
    if conn.in_transaction:
        raise RuntimeError("transaction() cannot be nested; pass the open connection instead")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
