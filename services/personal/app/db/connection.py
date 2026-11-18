"""SQL Server connections with pymssql (Assignment 2, ADR-7).

The A1 code was written against Python's sqlite3, so this module gives it the same small surface:
``conn.execute(sql, params)`` returns a cursor with ``fetchone``/``fetchall``/``rowcount``/``lastrowid``,
and rows can be read by column name or by position. Queries keep ``?`` placeholders; they are turned
into pymssql's ``%s`` here. Dates come back as ISO strings, exactly as SQLite stored them, so the
domain code that parses them did not have to change.

Azure SQL serverless pauses when idle and refuses connections for up to about a minute while it
resumes (error 40613, or a DB-Lib timeout 20002/20003/20009 with pymssql). ``connect`` retries those
with exponential backoff instead of failing the first request after a pause.
"""

import logging
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pymssql

logger = logging.getLogger("float.db")

RETRYABLE = {40613, 40197, 40501, 49918, 49919, 49920, 20002, 20003, 20009, 20047}
# Constraint violations, NOT NULL, and the THROW 5000x in our triggers all mean "the data was refused".
INTEGRITY = {2627, 2601, 547, 515, 50001, 50002, 50003}


class DatabaseError(Exception):
    """Any database failure, with SQL Server's error number when there is one."""

    def __init__(self, message: str, number: int | None = None) -> None:
        super().__init__(message)
        self.number = number


class IntegrityError(DatabaseError):
    """A constraint, a unique index, or one of our triggers refused the change."""


class DatabaseUnavailable(DatabaseError):
    """The database could not be reached after every retry."""


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    user: str
    password: str
    database: str
    encryption: str | None

    @classmethod
    def parse(cls, url: str) -> "Target":
        """``mssql://user:password@host:1433/database?encrypt=require`` (password URL-encoded)."""
        parts = urlparse(url)
        if parts.scheme not in {"mssql", "mssql+pymssql"} or not parts.hostname or not parts.path.strip("/"):
            raise ValueError("DATABASE_URL must look like mssql://user:password@host:1433/database")
        options = parse_qs(parts.query)
        return cls(
            host=parts.hostname,
            port=parts.port or 1433,
            user=unquote(parts.username or ""),
            password=unquote(parts.password or ""),
            database=parts.path.strip("/"),
            encryption=(options.get("encrypt") or [None])[0],
        )


def _number(error: BaseException) -> int | None:
    args = getattr(error, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def _wrap(error: BaseException) -> DatabaseError:
    number = _number(error)
    if number in INTEGRITY or isinstance(error, pymssql.IntegrityError):
        return IntegrityError(str(error), number)
    return DatabaseError(str(error), number)


def _plain(value: Any) -> Any:
    """DATE and DATETIME2 values become ISO text, the format the domain code already parses; whole
    DECIMAL values (SQL Server's type for some computed numbers) become int."""
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class Row(tuple):
    """A result row readable by position (``row[0]``) and by column name (``row["id"]``)."""

    _index: dict[str, int]

    def __new__(cls, values: Sequence[Any], index: dict[str, int]) -> "Row":
        row = super().__new__(cls, (_plain(value) for value in values))
        row._index = index
        return row

    def __getitem__(self, key):  # type: ignore[override]
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self) -> list[str]:
        return list(self._index)


def _sql(query: str) -> str:
    """sqlite3's ``?`` placeholders become pymssql's ``%s``; a literal ``%`` must be doubled (with parameters only)."""
    return query.replace("%", "%%").replace("?", "%s")


class Cursor:
    def __init__(self, cursor, lastrowid: int | None) -> None:
        self._cursor = cursor
        self.rowcount: int = cursor.rowcount
        self.lastrowid = lastrowid
        description = cursor.description or ()
        self._index = {column[0]: position for position, column in enumerate(description)}

    def fetchone(self) -> Row | None:
        if not self._index:
            return None
        values = self._cursor.fetchone()
        return None if values is None else Row(values, self._index)

    def fetchall(self) -> list[Row]:
        if not self._index:
            return []
        return [Row(values, self._index) for values in self._cursor.fetchall()]

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class Connection:
    """One pymssql connection in autocommit mode; ``app.db.unit_of_work.transaction`` groups writes."""

    def __init__(self, raw) -> None:
        self._raw = raw
        self.in_transaction = False

    def execute(self, query: str, params: Sequence[Any] = ()) -> Cursor:
        cursor = self._raw.cursor()
        try:
            if params:
                cursor.execute(_sql(query), tuple(params))
            else:
                cursor.execute(query)
        except pymssql.Error as error:
            raise _wrap(error) from error
        lastrowid = cursor.lastrowid if query.lstrip()[:6].upper() == "INSERT" else None
        lastrowid = int(lastrowid) if lastrowid is not None else None  # pymssql gives a Decimal
        return Cursor(cursor, lastrowid)

    def executemany(self, query: str, rows: Sequence[Sequence[Any]]) -> None:
        for params in rows:
            self.execute(query, params)

    def run_batch(self, batch: str) -> None:
        """Run a T-SQL batch with no parameters (migrations). ``%`` and ``?`` are left as written."""
        cursor = self._raw.cursor()
        try:
            cursor.execute(batch)
        except pymssql.Error as error:
            raise _wrap(error) from error

    def close(self) -> None:
        self._raw.close()


def connect(url: str, *, retries: int = 8, first_delay: float = 1.0, max_delay: float = 30.0,
            login_timeout: int = 30) -> Connection:
    """Open a connection, retrying while an Azure SQL serverless database resumes (ADR-8)."""
    target = Target.parse(url)
    delay = first_delay
    for attempt in range(retries + 1):
        try:
            raw = pymssql.connect(server=target.host, port=str(target.port), user=target.user,
                                  password=target.password, database=target.database, autocommit=True,
                                  login_timeout=login_timeout, timeout=60, encryption=target.encryption,
                                  tds_version="7.4")
            return Connection(raw)
        except pymssql.Error as error:
            number = _number(error)
            retryable = number in RETRYABLE or number is None or "timed out" in str(error).lower() \
                or "unable to connect" in str(error).lower()
            if not retryable or attempt == retries:
                raise DatabaseUnavailable(f"could not connect to the database: {error}", number) from error
            logger.warning("database not ready (error %s), retrying in %.0f s", number, delay)
            time.sleep(delay)
            delay = min(delay * 2, max_delay)
    raise AssertionError("unreachable")
