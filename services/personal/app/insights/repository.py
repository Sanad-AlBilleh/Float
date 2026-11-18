"""SQL for Insights' own tables: alerts and each user's audit-feed cursor (FR-32)."""

import json
from collections.abc import Iterable
from datetime import datetime

from app.db.connection import Connection, Row
from app.shared.clock import to_utc_text

ALERT_COLUMNS = "id, user_id, type, dedupe_key, severity, message, subject_url, created_at, read_at, dismissed_at, resolved_at"


def sync_alerts(conn: Connection, *, user_id: int, specs: Iterable, never_resolves: Iterable[str],
                now: datetime) -> None:
    """Insert new keys, refresh and reopen keys that fire again, and resolve open keys that stopped firing.

    Dismissal is permanent for a key: a dismissed alert is refreshed but never shown again.
    """
    stamp = to_utc_text(now)
    keys = []
    for spec in specs:
        keys.append(spec.dedupe_key)
        # SQLite's INSERT ... ON CONFLICT DO UPDATE is an UPDATE first, then an INSERT if nothing matched,
        # inside the caller's transaction.
        updated = conn.execute(
            "UPDATE alerts SET severity = ?, message = ?, subject_url = ?, resolved_at = NULL"
            " WHERE user_id = ? AND dedupe_key = ?",
            (spec.severity, spec.message, spec.subject_url, user_id, spec.dedupe_key),
        ).rowcount
        if not updated:
            conn.execute(
                "INSERT INTO alerts (user_id, type, dedupe_key, severity, message, subject_url, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, spec.type, spec.dedupe_key, spec.severity, spec.message, spec.subject_url, stamp),
            )
    exempt = list(never_resolves)
    conn.execute(
        f"UPDATE alerts SET resolved_at = ? WHERE user_id = ? AND resolved_at IS NULL"
        f" AND type NOT IN ({','.join('?' * len(exempt))})"
        f" AND dedupe_key NOT IN (SELECT value FROM OPENJSON(?))",
        (stamp, user_id, *exempt, _json_list(keys)),
    )


def _json_list(values: list[str]) -> str:
    return json.dumps(values)


def open_alerts(conn: Connection, *, user_id: int) -> list[Row]:
    return conn.execute(
        f"SELECT {ALERT_COLUMNS} FROM alerts WHERE user_id = ? AND dismissed_at IS NULL AND resolved_at IS NULL"
        " ORDER BY CASE WHEN read_at IS NULL THEN 0 ELSE 1 END,"
        " CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, id DESC",
        (user_id,),
    ).fetchall()


def get_alert(conn: Connection, alert_id: int) -> Row | None:
    return conn.execute(f"SELECT {ALERT_COLUMNS} FROM alerts WHERE id = ?", (alert_id,)).fetchone()


def mark_read(conn: Connection, *, alert_id: int, now: datetime) -> None:
    conn.execute("UPDATE alerts SET read_at = COALESCE(read_at, ?) WHERE id = ?", (to_utc_text(now), alert_id))


def dismiss(conn: Connection, *, alert_id: int, now: datetime) -> None:
    conn.execute("UPDATE alerts SET dismissed_at = COALESCE(dismissed_at, ?) WHERE id = ?",
                 (to_utc_text(now), alert_id))


def count_rows(conn: Connection, *, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM alerts WHERE user_id = ?", (user_id,)).fetchone()[0]


def get_cursor(conn: Connection, *, user_id: int) -> int:
    row = conn.execute("SELECT last_audit_event_id FROM alert_cursors WHERE user_id = ?", (user_id,)).fetchone()
    return 0 if row is None else row[0]


def set_cursor(conn: Connection, *, user_id: int, last_audit_event_id: int) -> None:
    updated = conn.execute(
        "UPDATE alert_cursors SET last_audit_event_id = CASE WHEN last_audit_event_id > ? THEN last_audit_event_id"
        " ELSE ? END WHERE user_id = ?",
        (last_audit_event_id, last_audit_event_id, user_id),
    ).rowcount
    if not updated:
        conn.execute("INSERT INTO alert_cursors (user_id, last_audit_event_id) VALUES (?, ?)",
                     (user_id, last_audit_event_id))
