"""SQL for Identity's own tables: users, sessions, and login_attempts. Always parameterized."""

import sqlite3
from datetime import datetime

from app.shared.clock import from_utc_text, to_utc_text


def insert_user(conn: sqlite3.Connection, *, username: str, display_name: str, password_hash: str, now: datetime) -> int:
    stamp = to_utc_text(now)
    cursor = conn.execute(
        "INSERT INTO users (username, display_name, password_hash, created_at, password_changed_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (username, display_name, password_hash, stamp, stamp),
    )
    return cursor.lastrowid


def find_user_by_username(conn: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, display_name, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()


def get_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, username, display_name, password_hash FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def update_password(conn: sqlite3.Connection, *, user_id: int, password_hash: str, now: datetime) -> None:
    conn.execute(
        "UPDATE users SET password_hash = ?, password_changed_at = ? WHERE id = ?",
        (password_hash, to_utc_text(now), user_id),
    )


def insert_session(
    conn: sqlite3.Connection, *, user_id: int, token_hash: str, csrf_token: str, now: datetime, expires_at: datetime
) -> int:
    stamp = to_utc_text(now)
    cursor = conn.execute(
        "INSERT INTO sessions (user_id, token_hash, csrf_token, created_at, last_seen_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, token_hash, csrf_token, stamp, stamp, to_utc_text(expires_at)),
    )
    return cursor.lastrowid


def find_session(conn: sqlite3.Connection, token_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT s.id AS session_id, s.csrf_token, s.last_seen_at, s.expires_at,"
        " u.id AS user_id, u.username, u.display_name"
        " FROM sessions AS s JOIN users AS u ON u.id = s.user_id"
        " WHERE s.token_hash = ?",
        (token_hash,),
    ).fetchone()


def touch_session(conn: sqlite3.Connection, session_id: int, now: datetime) -> None:
    conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (to_utc_text(now), session_id))


def delete_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def delete_session_by_token_hash(conn: sqlite3.Connection, token_hash: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_other_sessions(conn: sqlite3.Connection, *, user_id: int, keep_session_id: int) -> None:
    conn.execute("DELETE FROM sessions WHERE user_id = ? AND id <> ?", (user_id, keep_session_id))


def record_attempt(
    conn: sqlite3.Connection, *, username_key: str, client_address: str, now: datetime, succeeded: bool
) -> None:
    conn.execute(
        "INSERT INTO login_attempts (username_key, client_address, attempted_at, succeeded) VALUES (?, ?, ?, ?)",
        (username_key, client_address, to_utc_text(now), int(succeeded)),
    )


def username_failures(conn: sqlite3.Connection, *, username_key: str, since: datetime) -> list[datetime]:
    """Failed attempts for a username after ``since`` and after its most recent success."""
    rows = conn.execute(
        "SELECT attempted_at FROM login_attempts"
        " WHERE username_key = ? AND succeeded = 0 AND attempted_at > ?"
        " AND attempted_at > COALESCE("
        "   (SELECT MAX(attempted_at) FROM login_attempts WHERE username_key = ? AND succeeded = 1), '')",
        (username_key, to_utc_text(since), username_key),
    ).fetchall()
    return [from_utc_text(row[0]) for row in rows]


def address_failures(conn: sqlite3.Connection, *, client_address: str, since: datetime) -> list[datetime]:
    rows = conn.execute(
        "SELECT attempted_at FROM login_attempts WHERE client_address = ? AND succeeded = 0 AND attempted_at > ?",
        (client_address, to_utc_text(since)),
    ).fetchall()
    return [from_utc_text(row[0]) for row in rows]


def prune_attempts(conn: sqlite3.Connection, *, before: datetime) -> None:
    conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (to_utc_text(before),))
