"""SQL for the Ledger's own tables: ledger_settings, categories, and transactions."""

import sqlite3
from datetime import date, datetime

from app.shared.clock import to_utc_text

COLUMNS = (
    "id, user_id, kind, amount_cents, occurred_on, category_id, income_source, origin, one_off, note, version"
)


def insert_settings(conn: sqlite3.Connection, *, user_id: int, tracking_start: date, opening_balance_cents: int) -> None:
    conn.execute(
        "INSERT INTO ledger_settings (user_id, tracking_start_date, opening_balance_cents) VALUES (?, ?, ?)",
        (user_id, tracking_start.isoformat(), opening_balance_cents),
    )


def get_settings(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT user_id, tracking_start_date, opening_balance_cents FROM ledger_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def list_categories(conn: sqlite3.Connection, user_id: int | None = None) -> list[sqlite3.Row]:
    """The fixed categories, plus ``user_id``'s own when given."""
    return conn.execute(
        "SELECT id, slug, name, owner_user_id FROM categories WHERE owner_user_id IS NULL OR owner_user_id = ?"
        " ORDER BY owner_user_id IS NOT NULL, id",
        (user_id,),
    ).fetchall()


def all_category_names(conn: sqlite3.Connection) -> dict[int, str]:
    return {row[0]: row[1] for row in conn.execute("SELECT id, name FROM categories")}


def insert_category(conn: sqlite3.Connection, *, user_id: int, name: str) -> int:
    return conn.execute("INSERT INTO categories (slug, name, owner_user_id) VALUES (?, ?, ?)",
                        (f"u{user_id}:{name.lower()}", name, user_id)).lastrowid


def insert_transaction(conn: sqlite3.Connection, *, user_id: int, kind: str, amount_cents: int, occurred_on: date,
                       category_id: int | None, income_source: str | None, origin: str, one_off: bool, note: str,
                       now: datetime) -> int:
    stamp = to_utc_text(now)
    cursor = conn.execute(
        "INSERT INTO transactions (user_id, kind, amount_cents, occurred_on, category_id, income_source, origin,"
        " one_off, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, kind, amount_cents, occurred_on.isoformat(), category_id, income_source, origin,
         int(one_off), note, stamp, stamp),
    )
    return cursor.lastrowid


def get_transaction(conn: sqlite3.Connection, transaction_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {COLUMNS} FROM transactions WHERE id = ?", (transaction_id,)).fetchone()


def update_manual(conn: sqlite3.Connection, *, transaction_id: int, user_id: int, version: int, kind: str,
                  amount_cents: int, occurred_on: date, category_id: int | None, income_source: str | None,
                  one_off: bool, note: str, now: datetime) -> int:
    cursor = conn.execute(
        "UPDATE transactions SET kind = ?, amount_cents = ?, occurred_on = ?, category_id = ?, income_source = ?,"
        " one_off = ?, note = ?, updated_at = ?, version = version + 1"
        " WHERE id = ? AND user_id = ? AND version = ?",
        (kind, amount_cents, occurred_on.isoformat(), category_id, income_source, int(one_off), note,
         to_utc_text(now), transaction_id, user_id, version),
    )
    return cursor.rowcount


def update_linked(conn: sqlite3.Connection, *, transaction_id: int, amount_cents: int, occurred_on: date,
                  category_id: int | None, now: datetime) -> None:
    conn.execute(
        "UPDATE transactions SET amount_cents = ?, occurred_on = ?, category_id = ?, updated_at = ?,"
        " version = version + 1 WHERE id = ?",
        (amount_cents, occurred_on.isoformat(), category_id, to_utc_text(now), transaction_id),
    )


def delete_transaction(conn: sqlite3.Connection, *, transaction_id: int, user_id: int, version: int | None = None) -> int:
    if version is None:
        cursor = conn.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (transaction_id, user_id))
    else:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ? AND version = ?",
            (transaction_id, user_id, version),
        )
    return cursor.rowcount


def list_transactions(conn: sqlite3.Connection, *, user_id: int, limit: int,
                      before: tuple[date, int] | None) -> list[sqlite3.Row]:
    if before is None:
        return conn.execute(
            f"SELECT {COLUMNS} FROM transactions WHERE user_id = ? ORDER BY occurred_on DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    day, last_id = before
    return conn.execute(
        f"SELECT {COLUMNS} FROM transactions WHERE user_id = ?"
        " AND (occurred_on < ? OR (occurred_on = ? AND id < ?)) ORDER BY occurred_on DESC, id DESC LIMIT ?",
        (user_id, day.isoformat(), day.isoformat(), last_id, limit),
    ).fetchall()


def balance(conn: sqlite3.Connection, *, user_id: int, as_of: date) -> int | None:
    row = conn.execute(
        "SELECT ls.opening_balance_cents + COALESCE(SUM("
        "   CASE t.kind WHEN 'income' THEN t.amount_cents ELSE -t.amount_cents END), 0)"
        " FROM ledger_settings AS ls"
        " LEFT JOIN transactions AS t"
        "   ON t.user_id = ls.user_id AND t.occurred_on BETWEEN ls.tracking_start_date AND ?"
        " WHERE ls.user_id = ? GROUP BY ls.user_id",
        (as_of.isoformat(), user_id),
    ).fetchone()
    return None if row is None else row[0]


def has_income(conn: sqlite3.Connection, *, user_id: int, source: str, start: date, end_inclusive: date) -> bool:
    row = conn.execute(
        "SELECT 1 FROM transactions WHERE user_id = ? AND kind = 'income' AND income_source = ?"
        " AND occurred_on BETWEEN ? AND ? LIMIT 1",
        (user_id, source, start.isoformat(), end_inclusive.isoformat()),
    ).fetchone()
    return row is not None


def expense_rows(conn: sqlite3.Connection, *, user_id: int, start: date, end_exclusive: date) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, amount_cents, occurred_on, category_id, origin, one_off FROM transactions"
        " WHERE user_id = ? AND kind = 'expense' AND occurred_on >= ? AND occurred_on < ?"
        " ORDER BY occurred_on, id",
        (user_id, start.isoformat(), end_exclusive.isoformat()),
    ).fetchall()
