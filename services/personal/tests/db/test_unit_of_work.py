"""transaction(): commit on success, roll back everything on failure, no nesting (SQL Server)."""

import pytest

from app.db.connection import IntegrityError
from app.db.unit_of_work import transaction


@pytest.fixture
def table(conn):
    conn.execute("CREATE TABLE #t (x INT NOT NULL PRIMARY KEY)")  # a temporary table: this connection only
    return conn


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM #t").fetchone()[0]


def test_commits_when_the_block_succeeds(table):
    with transaction(table):
        table.execute("INSERT INTO #t VALUES (1)")
    assert count(table) == 1
    assert not table.in_transaction


def test_rolls_back_every_write_when_the_block_fails(table):
    with pytest.raises(RuntimeError, match="boom"):
        with transaction(table):
            table.execute("INSERT INTO #t VALUES (1)")
            table.execute("INSERT INTO #t VALUES (2)")
            raise RuntimeError("boom")
    assert count(table) == 0
    assert not table.in_transaction


def test_a_constraint_violation_rolls_back_the_whole_block(table):
    with pytest.raises(IntegrityError):
        with transaction(table):
            table.execute("INSERT INTO #t VALUES (1)")
            table.execute("INSERT INTO #t VALUES (1)")
    assert count(table) == 0


def test_transactions_cannot_be_nested(table):
    with transaction(table):
        with pytest.raises(RuntimeError, match="nested"):
            with transaction(table):
                pass
