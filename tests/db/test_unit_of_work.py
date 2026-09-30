import sqlite3

import pytest

from app.db.connection import connect, enable_wal
from app.db.unit_of_work import transaction


@pytest.fixture
def table(conn):
    conn.execute("CREATE TABLE t (x INTEGER NOT NULL) STRICT")
    return conn


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]


def test_commits_when_the_block_succeeds(table):
    with transaction(table):
        table.execute("INSERT INTO t VALUES (1)")
    assert count(table) == 1
    assert not table.in_transaction


def test_rolls_back_every_write_when_the_block_fails(table):
    with pytest.raises(RuntimeError, match="boom"):
        with transaction(table):
            table.execute("INSERT INTO t VALUES (1)")
            table.execute("INSERT INTO t VALUES (2)")
            raise RuntimeError("boom")
    assert count(table) == 0
    assert not table.in_transaction


def test_nesting_is_rejected(table):
    with transaction(table):
        with pytest.raises(RuntimeError, match="nested"):
            with transaction(table):
                pass


def test_write_lock_is_taken_up_front(tmp_path):
    path = tmp_path / "lock.sqlite3"
    first, second = connect(path), connect(path)
    enable_wal(first)
    second.execute("PRAGMA busy_timeout = 0")
    try:
        with transaction(first):
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                second.execute("BEGIN IMMEDIATE")
    finally:
        first.close()
        second.close()
