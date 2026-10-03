"""SQL for the Households tables only."""

import sqlite3
from datetime import date, datetime

from app.shared.clock import to_utc_text

HOUSEHOLD_COLUMNS = "id, name, owner_user_id, archived_at, version"


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


# Households and membership (FR-17–19) ------------------------------------------------------------

def insert_household(conn: sqlite3.Connection, *, name: str, owner_id: int, now: datetime) -> int:
    return conn.execute("INSERT INTO households (name, owner_user_id, created_at) VALUES (?, ?, ?)",
                        (name, owner_id, to_utc_text(now))).lastrowid


def get_household(conn: sqlite3.Connection, household_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {HOUSEHOLD_COLUMNS} FROM households WHERE id = ?", (household_id,)).fetchone()


def rename(conn: sqlite3.Connection, *, household_id: int, version: int, name: str) -> int:
    return conn.execute("UPDATE households SET name = ?, version = version + 1"
                        " WHERE id = ? AND version = ? AND archived_at IS NULL",
                        (name, household_id, version)).rowcount


def set_owner(conn: sqlite3.Connection, *, household_id: int, version: int, owner_id: int) -> int:
    return conn.execute("UPDATE households SET owner_user_id = ?, version = version + 1"
                        " WHERE id = ? AND version = ? AND archived_at IS NULL",
                        (owner_id, household_id, version)).rowcount


def archive(conn: sqlite3.Connection, *, household_id: int, version: int, now: datetime) -> int:
    return conn.execute("UPDATE households SET archived_at = ?, version = version + 1"
                        " WHERE id = ? AND version = ? AND archived_at IS NULL",
                        (to_utc_text(now), household_id, version)).rowcount


def insert_membership(conn: sqlite3.Connection, *, household_id: int, user_id: int, role: str,
                      now: datetime) -> None:
    conn.execute("INSERT INTO memberships (household_id, user_id, role, status, joined_at) VALUES (?, ?, ?, 'active', ?)",
                 (household_id, user_id, role, to_utc_text(now)))


def memberships(conn: sqlite3.Connection, *, household_id: int) -> list[sqlite3.Row]:
    """Every membership row, newest first per user, so the first row per user is the current one."""
    return conn.execute(
        "SELECT user_id, role, status, joined_at, ended_at FROM memberships WHERE household_id = ?"
        " ORDER BY status = 'active' DESC, id DESC",
        (household_id,),
    ).fetchall()


def active_membership(conn: sqlite3.Connection, *, household_id: int, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT user_id, role, status, joined_at, ended_at FROM memberships"
        " WHERE household_id = ? AND user_id = ? AND status = 'active'",
        (household_id, user_id),
    ).fetchone()


def latest_membership(conn: sqlite3.Connection, *, household_id: int, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT user_id, role, status, joined_at, ended_at FROM memberships WHERE household_id = ? AND user_id = ?"
        " ORDER BY id DESC LIMIT 1",
        (household_id, user_id),
    ).fetchone()


def count_active_members(conn: sqlite3.Connection, *, household_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM memberships WHERE household_id = ? AND status = 'active'",
                        (household_id,)).fetchone()[0]


def count_active_households(conn: sqlite3.Connection, *, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM memberships WHERE user_id = ? AND status = 'active'",
                        (user_id,)).fetchone()[0]


def user_household_ids(conn: sqlite3.Connection, *, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT household_id, MAX(status = 'active') AS active FROM memberships WHERE user_id = ?"
        " GROUP BY household_id ORDER BY active DESC, household_id",
        (user_id,),
    ).fetchall()


def end_membership(conn: sqlite3.Connection, *, household_id: int, user_id: int, status: str, now: datetime) -> int:
    return conn.execute("UPDATE memberships SET status = ?, ended_at = ?"
                        " WHERE household_id = ? AND user_id = ? AND status = 'active'",
                        (status, to_utc_text(now), household_id, user_id)).rowcount


def end_all_memberships(conn: sqlite3.Connection, *, household_id: int, now: datetime) -> None:
    conn.execute("UPDATE memberships SET status = 'left', ended_at = ? WHERE household_id = ? AND status = 'active'",
                 (to_utc_text(now), household_id))


def set_role(conn: sqlite3.Connection, *, household_id: int, user_id: int, role: str) -> None:
    conn.execute("UPDATE memberships SET role = ? WHERE household_id = ? AND user_id = ? AND status = 'active'",
                 (role, household_id, user_id))


# Invitations (FR-18) ------------------------------------------------------------------------------

def insert_invitation(conn: sqlite3.Connection, *, household_id: int, code_hash: str, created_by: int,
                      now: datetime, expires_at: datetime) -> int:
    return conn.execute(
        "INSERT INTO invitations (household_id, code_hash, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (household_id, code_hash, created_by, to_utc_text(now), to_utc_text(expires_at)),
    ).lastrowid


def invitation_by_hash(conn: sqlite3.Connection, code_hash: str) -> sqlite3.Row | None:
    return conn.execute("SELECT id, household_id, expires_at, used_by, revoked_at FROM invitations WHERE code_hash = ?",
                        (code_hash,)).fetchone()


def use_invitation(conn: sqlite3.Connection, *, invitation_id: int, user_id: int, now: datetime) -> int:
    stamp = to_utc_text(now)
    return conn.execute("UPDATE invitations SET used_by = ?, used_at = ? WHERE id = ? AND used_by IS NULL"
                        " AND revoked_at IS NULL AND expires_at > ?",
                        (user_id, stamp, invitation_id, stamp)).rowcount


def revoke_invitation(conn: sqlite3.Connection, *, household_id: int, invitation_id: int, now: datetime) -> int:
    return conn.execute("UPDATE invitations SET revoked_at = ? WHERE id = ? AND household_id = ?"
                        " AND used_by IS NULL AND revoked_at IS NULL",
                        (to_utc_text(now), invitation_id, household_id)).rowcount


def active_invitations(conn: sqlite3.Connection, *, household_id: int, now: datetime) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, created_by, created_at, expires_at FROM invitations WHERE household_id = ? AND used_by IS NULL"
        " AND revoked_at IS NULL AND expires_at > ? ORDER BY id",
        (household_id, to_utc_text(now)),
    ).fetchall()


# Balances inputs (SRS §4.4) -------------------------------------------------------------------------

def expense_totals(conn: sqlite3.Connection, *, household_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, payer_user_id, amount_cents FROM shared_expenses WHERE household_id = ?",
                        (household_id,)).fetchall()


def expense_splits(conn: sqlite3.Connection, *, household_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT sp.expense_id, sp.user_id, sp.share_cents FROM shared_expense_splits AS sp"
        " JOIN shared_expenses AS e ON e.id = sp.expense_id WHERE e.household_id = ?",
        (household_id,),
    ).fetchall()


def confirmed_settlements(conn: sqlite3.Connection, *, household_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT payer_user_id, payee_user_id, amount_cents FROM settlements"
                        " WHERE household_id = ? AND status = 'confirmed'", (household_id,)).fetchall()


def has_pending_settlement(conn: sqlite3.Connection, *, household_id: int, user_id: int | None = None) -> bool:
    if user_id is None:
        query, args = "SELECT 1 FROM settlements WHERE household_id = ? AND status = 'pending' LIMIT 1", (household_id,)
    else:
        query = ("SELECT 1 FROM settlements WHERE household_id = ? AND status = 'pending'"
                 " AND ? IN (payer_user_id, payee_user_id) LIMIT 1")
        args = (household_id, user_id)
    return conn.execute(query, args).fetchone() is not None


def active_bill_names(conn: sqlite3.Connection, *, household_id: int, user_id: int) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT s.name FROM household_bill_series AS s JOIN household_bill_participants AS p ON p.series_id = s.id"
        " WHERE s.household_id = ? AND p.user_id = ? AND s.ended_at IS NULL ORDER BY s.name",
        (household_id, user_id),
    )]
