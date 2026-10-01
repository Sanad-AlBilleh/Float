"""Append-only audit trail, written in the same transaction as the change it describes (FR-33)."""

import json
import sqlite3
from datetime import datetime
from typing import Any

from app.shared.clock import to_utc_text


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, default=str)


def record(conn: sqlite3.Connection, *, actor_user_id: int | None, entity_type: str, entity_id: int | None,
           action: str, now: datetime, before: Any = None, after: Any = None, household_id: int | None = None,
           request_id: str | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO audit_events (actor_user_id, household_id, entity_type, entity_id, action, before_json,"
        " after_json, request_id, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (actor_user_id, household_id, entity_type, entity_id, action, _json(before), _json(after),
         request_id, to_utc_text(now)),
    )
    return cursor.lastrowid
