"""The audit trail is append-only and shares its change's transaction (FR-33, AT-25)."""

import json
import sqlite3
from datetime import date

import pytest

from app.application.audit import record
from app.db.unit_of_work import transaction
from tests.factories import make_user


def write(conn, clock, user, **fields):
    values = {"entity_type": "transaction", "entity_id": 7, "action": "update"}
    values.update(fields)
    return record(conn, actor_user_id=user.id, now=clock.now_utc(), **values)


def test_records_json_with_sorted_keys(conn, clock):
    ana = make_user(conn, clock)
    event_id = write(conn, clock, ana, before={"b": 2, "a": 1},
                     after={"amount_cents": 500, "occurred_on": date(2026, 9, 30)}, request_id="req-1")
    row = conn.execute("SELECT * FROM audit_events WHERE id = ?", (event_id,)).fetchone()
    assert row["before_json"] == '{"a": 1, "b": 2}'
    assert json.loads(row["after_json"]) == {"amount_cents": 500, "occurred_on": "2026-09-30"}
    assert (row["request_id"], row["household_id"], row["actor_user_id"]) == ("req-1", None, ana.id)


def test_audit_events_cannot_be_changed_or_deleted(conn, clock):
    write(conn, clock, make_user(conn, clock))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_events SET action = 'tampered'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_events")


def test_audit_rows_roll_back_with_their_transaction(conn, clock):
    ana = make_user(conn, clock)
    with pytest.raises(RuntimeError):
        with transaction(conn):
            write(conn, clock, ana)
            raise RuntimeError("the change failed")
    assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0
