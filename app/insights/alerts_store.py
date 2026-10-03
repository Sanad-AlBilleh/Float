"""Stored alerts: sync, list, read, and dismiss (FR-32). Runs on the caller's open connection."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from app.insights import repository
from app.insights.alerts import NEVER_RESOLVES, AlertSpec
from app.shared.errors import NotFoundError

SQLITE_MAX_ID = 2**63 - 1


@dataclass(frozen=True)
class Alert:
    id: int
    type: str
    severity: str
    message: str
    subject_url: str
    read: bool


def sync_alerts(conn: sqlite3.Connection, *, user_id: int, specs: list[AlertSpec], now: datetime) -> None:
    repository.sync_alerts(conn, user_id=user_id, specs=specs, never_resolves=NEVER_RESOLVES, now=now)


def list_alerts(conn: sqlite3.Connection, *, user_id: int) -> list[Alert]:
    return [Alert(row["id"], row["type"], row["severity"], row["message"], row["subject_url"],
                  row["read_at"] is not None) for row in repository.open_alerts(conn, user_id=user_id)]


def _own(conn: sqlite3.Connection, user_id: int, alert_id: int) -> None:
    row = repository.get_alert(conn, alert_id) if 1 <= alert_id <= SQLITE_MAX_ID else None
    if row is None or row["user_id"] != user_id:
        raise NotFoundError("No such alert.")


def mark_read(conn: sqlite3.Connection, *, user_id: int, alert_id: int, now: datetime) -> None:
    _own(conn, user_id, alert_id)
    repository.mark_read(conn, alert_id=alert_id, now=now)


def dismiss(conn: sqlite3.Connection, *, user_id: int, alert_id: int, now: datetime) -> None:
    _own(conn, user_id, alert_id)
    repository.dismiss(conn, alert_id=alert_id, now=now)


def alert_row_count(conn: sqlite3.Connection, *, user_id: int) -> int:
    return repository.count_rows(conn, user_id=user_id)


def get_cursor(conn: sqlite3.Connection, *, user_id: int) -> int:
    return repository.get_cursor(conn, user_id=user_id)


def set_cursor(conn: sqlite3.Connection, *, user_id: int, last_audit_event_id: int) -> None:
    repository.set_cursor(conn, user_id=user_id, last_audit_event_id=last_audit_event_id)
