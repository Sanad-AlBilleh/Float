"""SQL for Planning's own tables."""

import sqlite3
from datetime import date, datetime

from app.shared.clock import to_utc_text


def insert_settings(conn: sqlite3.Connection, *, user_id: int, allowance_day: int, planned_allowance_cents: int,
                    opening_includes_allowance: bool) -> None:
    conn.execute(
        "INSERT INTO planning_settings (user_id, allowance_day, planned_allowance_cents, opening_includes_allowance)"
        " VALUES (?, ?, ?, ?)",
        (user_id, allowance_day, planned_allowance_cents, int(opening_includes_allowance)),
    )


def get_settings(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT user_id, allowance_day, planned_allowance_cents, opening_includes_allowance"
        " FROM planning_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def update_planned_allowance(conn: sqlite3.Connection, *, user_id: int, planned_allowance_cents: int) -> int:
    cursor = conn.execute(
        "UPDATE planning_settings SET planned_allowance_cents = ? WHERE user_id = ?",
        (planned_allowance_cents, user_id),
    )
    return cursor.rowcount


# Bills (FR-09–13) -------------------------------------------------------------------------------

SERIES_COLUMNS = (
    "id, user_id, name, amount_cents, category_id, freq, interval, anchor_date, until_date, max_count,"
    " materialized_through, ended_at, version"
)
OCCURRENCE_COLUMNS = (
    "o.id, o.series_id, s.name, s.category_id, o.scheduled_date, o.due_date, o.amount_cents, o.skipped_at,"
    " o.paid_transaction_id, o.version"
)
OCCURRENCES = "bill_occurrences AS o JOIN bill_series AS s ON s.id = o.series_id"


def insert_series(conn: sqlite3.Connection, *, user_id: int, name: str, amount_cents: int, category_id: int,
                  freq: str, interval: int, anchor: date, until: date | None, count: int | None,
                  now: datetime) -> int:
    cursor = conn.execute(
        "INSERT INTO bill_series (user_id, name, amount_cents, category_id, freq, interval, anchor_date,"
        " until_date, max_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, name, amount_cents, category_id, freq, interval, anchor.isoformat(),
         _iso(until), count, to_utc_text(now)),
    )
    return cursor.lastrowid


def get_series(conn: sqlite3.Connection, series_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {SERIES_COLUMNS} FROM bill_series WHERE id = ?", (series_id,)).fetchone()


def list_series(conn: sqlite3.Connection, *, user_id: int, active_only: bool) -> list[sqlite3.Row]:
    condition = " AND ended_at IS NULL" if active_only else ""
    return conn.execute(
        f"SELECT {SERIES_COLUMNS} FROM bill_series WHERE user_id = ?{condition} ORDER BY name, id", (user_id,)
    ).fetchall()


def insert_occurrence_if_absent(conn: sqlite3.Connection, *, series_id: int, user_id: int, scheduled_date: date,
                                amount_cents: int) -> int:
    cursor = conn.execute(
        "INSERT INTO bill_occurrences (series_id, user_id, scheduled_date, due_date, amount_cents)"
        " VALUES (?, ?, ?, ?, ?) ON CONFLICT (series_id, scheduled_date) DO NOTHING",
        (series_id, user_id, scheduled_date.isoformat(), scheduled_date.isoformat(), amount_cents),
    )
    return cursor.rowcount


def advance_watermark(conn: sqlite3.Connection, *, series_id: int, through: date) -> None:
    conn.execute(
        "UPDATE bill_series SET materialized_through = ? WHERE id = ?"
        " AND (materialized_through IS NULL OR materialized_through < ?)",
        (through.isoformat(), series_id, through.isoformat()),
    )


def get_occurrence(conn: sqlite3.Connection, occurrence_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {OCCURRENCE_COLUMNS}, o.user_id FROM {OCCURRENCES} WHERE o.id = ?", (occurrence_id,)
    ).fetchone()


def list_occurrences(conn: sqlite3.Connection, *, user_id: int, start: date, end_exclusive: date) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {OCCURRENCE_COLUMNS} FROM {OCCURRENCES}"
        " WHERE o.user_id = ? AND o.due_date >= ? AND o.due_date < ? ORDER BY o.due_date, s.name, o.id",
        (user_id, start.isoformat(), end_exclusive.isoformat()),
    ).fetchall()


def open_occurrences_due_before(conn: sqlite3.Connection, *, user_id: int, before: date) -> list[sqlite3.Row]:
    """Unpaid, unskipped occurrences due before ``before``: what safe-to-spend reserves (SRS §4.5)."""
    return conn.execute(
        f"SELECT {OCCURRENCE_COLUMNS} FROM {OCCURRENCES}"
        " WHERE o.user_id = ? AND o.due_date < ? AND o.paid_transaction_id IS NULL AND o.skipped_at IS NULL"
        " ORDER BY o.due_date, s.name, o.id",
        (user_id, before.isoformat()),
    ).fetchall()


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def link_payment(conn: sqlite3.Connection, *, occurrence_id: int, version: int, transaction_id: int) -> int:
    return conn.execute(
        "UPDATE bill_occurrences SET paid_transaction_id = ?, version = version + 1"
        " WHERE id = ? AND version = ? AND paid_transaction_id IS NULL AND skipped_at IS NULL",
        (transaction_id, occurrence_id, version),
    ).rowcount


def unlink_payment(conn: sqlite3.Connection, *, occurrence_id: int, version: int) -> int:
    return conn.execute(
        "UPDATE bill_occurrences SET paid_transaction_id = NULL, version = version + 1"
        " WHERE id = ? AND version = ? AND paid_transaction_id IS NOT NULL",
        (occurrence_id, version),
    ).rowcount


def set_skipped(conn: sqlite3.Connection, *, occurrence_id: int, version: int, skipped_at: datetime | None) -> int:
    return conn.execute(
        "UPDATE bill_occurrences SET skipped_at = ?, version = version + 1"
        " WHERE id = ? AND version = ? AND paid_transaction_id IS NULL",
        (None if skipped_at is None else to_utc_text(skipped_at), occurrence_id, version),
    ).rowcount


def update_occurrence(conn: sqlite3.Connection, *, occurrence_id: int, version: int, amount_cents: int,
                      due_date: date) -> int:
    return conn.execute(
        "UPDATE bill_occurrences SET amount_cents = ?, due_date = ?, version = version + 1"
        " WHERE id = ? AND version = ? AND paid_transaction_id IS NULL",
        (amount_cents, due_date.isoformat(), occurrence_id, version),
    ).rowcount


def end_series(conn: sqlite3.Connection, *, series_id: int, version: int, now: datetime) -> int:
    return conn.execute(
        "UPDATE bill_series SET ended_at = ?, version = version + 1 WHERE id = ? AND version = ? AND ended_at IS NULL",
        (to_utc_text(now), series_id, version),
    ).rowcount


def delete_open_occurrences_due_from(conn: sqlite3.Connection, *, series_id: int, day: date) -> int:
    return conn.execute(
        "DELETE FROM bill_occurrences WHERE series_id = ? AND due_date >= ?"
        " AND paid_transaction_id IS NULL AND skipped_at IS NULL",
        (series_id, day.isoformat()),
    ).rowcount


def has_paid_from(conn: sqlite3.Connection, *, series_id: int, scheduled_date: date) -> bool:
    return conn.execute(
        "SELECT 1 FROM bill_occurrences WHERE series_id = ? AND scheduled_date >= ?"
        " AND paid_transaction_id IS NOT NULL LIMIT 1",
        (series_id, scheduled_date.isoformat()),
    ).fetchone() is not None


def delete_unpaid_from(conn: sqlite3.Connection, *, series_id: int, scheduled_date: date) -> None:
    conn.execute(
        "DELETE FROM bill_occurrences WHERE series_id = ? AND scheduled_date >= ? AND paid_transaction_id IS NULL",
        (series_id, scheduled_date.isoformat()),
    )


def rewrite_series(conn: sqlite3.Connection, *, series_id: int, name: str, amount_cents: int, category_id: int,
                   freq: str, interval: int, anchor: date, until: date | None, count: int | None) -> None:
    """Replace a series' values and rule; ``materialized_through`` resets so the new rule is generated afresh."""
    conn.execute(
        "UPDATE bill_series SET name = ?, amount_cents = ?, category_id = ?, freq = ?, interval = ?,"
        " anchor_date = ?, until_date = ?, max_count = ?, materialized_through = NULL, version = version + 1"
        " WHERE id = ?",
        (name, amount_cents, category_id, freq, interval, anchor.isoformat(), _iso(until), count, series_id),
    )


# Savings goals (FR-14–15) ------------------------------------------------------------------------

GOAL_COLUMNS = (
    "g.id, g.user_id, g.name, g.target_cents, g.target_date, g.priority, g.auto_reserve, g.archived_at, g.version,"
    " COALESCE((SELECT SUM(m.delta_cents) FROM goal_movements AS m WHERE m.goal_id = g.id), 0) AS protected_cents"
)


def insert_goal(conn: sqlite3.Connection, *, user_id: int, name: str, target_cents: int, target_date: date | None,
                priority: int, auto_reserve: bool, now: datetime) -> int:
    return conn.execute(
        "INSERT INTO savings_goals (user_id, name, target_cents, target_date, priority, auto_reserve, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, name, target_cents, _iso(target_date), priority, int(auto_reserve), to_utc_text(now)),
    ).lastrowid


def get_goal(conn: sqlite3.Connection, goal_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {GOAL_COLUMNS} FROM savings_goals AS g WHERE g.id = ?", (goal_id,)).fetchone()


def list_goals(conn: sqlite3.Connection, *, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {GOAL_COLUMNS} FROM savings_goals AS g WHERE g.user_id = ? AND g.archived_at IS NULL"
        " ORDER BY g.priority, g.name, g.id",
        (user_id,),
    ).fetchall()


def update_goal(conn: sqlite3.Connection, *, goal_id: int, version: int, name: str, target_cents: int,
                target_date: date | None, priority: int, auto_reserve: bool) -> int:
    return conn.execute(
        "UPDATE savings_goals SET name = ?, target_cents = ?, target_date = ?, priority = ?, auto_reserve = ?,"
        " version = version + 1 WHERE id = ? AND version = ? AND archived_at IS NULL",
        (name, target_cents, _iso(target_date), priority, int(auto_reserve), goal_id, version),
    ).rowcount


def archive_goal(conn: sqlite3.Connection, *, goal_id: int, version: int, now: datetime) -> int:
    return conn.execute(
        "UPDATE savings_goals SET archived_at = ?, version = version + 1"
        " WHERE id = ? AND version = ? AND archived_at IS NULL",
        (to_utc_text(now), goal_id, version),
    ).rowcount


def insert_movement(conn: sqlite3.Connection, *, goal_id: int, delta_cents: int, moved_on: date, note: str,
                    now: datetime) -> None:
    conn.execute(
        "INSERT INTO goal_movements (goal_id, delta_cents, moved_on, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (goal_id, delta_cents, moved_on.isoformat(), note, to_utc_text(now)),
    )


def list_movements(conn: sqlite3.Connection, *, goal_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT moved_on, delta_cents FROM goal_movements WHERE goal_id = ? ORDER BY moved_on, id", (goal_id,)
    ).fetchall()


def protected_total(conn: sqlite3.Connection, *, user_id: int) -> int:
    return conn.execute(
        "SELECT COALESCE(SUM(m.delta_cents), 0) FROM goal_movements AS m"
        " JOIN savings_goals AS g ON g.id = m.goal_id WHERE g.user_id = ? AND g.archived_at IS NULL",
        (user_id,),
    ).fetchone()[0]
