"""SQL for Insights' own tables: alerts and each user's audit-feed cursor (FR-32)."""

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime

from app.shared.clock import to_utc_text

ALERT_COLUMNS = "id, user_id, type, dedupe_key, severity, message, subject_url, created_at, read_at, dismissed_at, resolved_at"


def sync_alerts(conn: sqlite3.Connection, *, user_id: int, specs: Iterable, never_resolves: Iterable[str],
                now: datetime) -> None:
    """Insert new keys, refresh and reopen keys that fire again, and resolve open keys that stopped firing.

    Dismissal is permanent for a key: a dismissed alert is refreshed but never shown again.
    """
    stamp = to_utc_text(now)
    keys = []
    for spec in specs:
        keys.append(spec.dedupe_key)
        conn.execute(
            "INSERT INTO alerts (user_id, type, dedupe_key, severity, message, subject_url, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (user_id, dedupe_key) DO UPDATE SET"
            " severity = excluded.severity, message = excluded.message, subject_url = excluded.subject_url,"
            " resolved_at = NULL",
            (user_id, spec.type, spec.dedupe_key, spec.severity, spec.message, spec.subject_url, stamp),
        )
    exempt = list(never_resolves)
    conn.execute(
        f"UPDATE alerts SET resolved_at = ? WHERE user_id = ? AND resolved_at IS NULL"
        f" AND type NOT IN ({','.join('?' * len(exempt))})"
        f" AND dedupe_key NOT IN (SELECT value FROM json_each(?))",
        (stamp, user_id, *exempt, _json_list(keys)),
    )


def _json_list(values: list[str]) -> str:
    return json.dumps(values)


def open_alerts(conn: sqlite3.Connection, *, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {ALERT_COLUMNS} FROM alerts WHERE user_id = ? AND dismissed_at IS NULL AND resolved_at IS NULL"
        " ORDER BY read_at IS NOT NULL, CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, id DESC",
        (user_id,),
    ).fetchall()


def get_alert(conn: sqlite3.Connection, alert_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {ALERT_COLUMNS} FROM alerts WHERE id = ?", (alert_id,)).fetchone()


def mark_read(conn: sqlite3.Connection, *, alert_id: int, now: datetime) -> None:
    conn.execute("UPDATE alerts SET read_at = COALESCE(read_at, ?) WHERE id = ?", (to_utc_text(now), alert_id))


def dismiss(conn: sqlite3.Connection, *, alert_id: int, now: datetime) -> None:
    conn.execute("UPDATE alerts SET dismissed_at = COALESCE(dismissed_at, ?) WHERE id = ?",
                 (to_utc_text(now), alert_id))


def count_rows(conn: sqlite3.Connection, *, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM alerts WHERE user_id = ?", (user_id,)).fetchone()[0]


def get_cursor(conn: sqlite3.Connection, *, user_id: int) -> int:
    row = conn.execute("SELECT last_audit_event_id FROM alert_cursors WHERE user_id = ?", (user_id,)).fetchone()
    return 0 if row is None else row[0]


def set_cursor(conn: sqlite3.Connection, *, user_id: int, last_audit_event_id: int) -> None:
    conn.execute(
        "INSERT INTO alert_cursors (user_id, last_audit_event_id) VALUES (?, ?) ON CONFLICT (user_id)"
        " DO UPDATE SET last_audit_event_id = MAX(last_audit_event_id, excluded.last_audit_event_id)",
        (user_id, last_audit_event_id),
    )
