"""SQL for Planning's own tables."""

import sqlite3


def insert_settings(conn: sqlite3.Connection, *, user_id: int, allowance_day: int, planned_allowance_cents: int) -> None:
    conn.execute(
        "INSERT INTO planning_settings (user_id, allowance_day, planned_allowance_cents) VALUES (?, ?, ?)",
        (user_id, allowance_day, planned_allowance_cents),
    )


def get_settings(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT user_id, allowance_day, planned_allowance_cents FROM planning_settings WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def update_planned_allowance(conn: sqlite3.Connection, *, user_id: int, planned_allowance_cents: int) -> int:
    cursor = conn.execute(
        "UPDATE planning_settings SET planned_allowance_cents = ? WHERE user_id = ?",
        (planned_allowance_cents, user_id),
    )
    return cursor.rowcount
