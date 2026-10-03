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
    """Every membership row, newest first, so the first row per user is their current one."""
    return conn.execute(
        "SELECT id, user_id, role, status, joined_at, ended_at FROM memberships WHERE household_id = ?"
        " ORDER BY id DESC",
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


# Shared expenses (FR-20–22) -----------------------------------------------------------------------

EXPENSE_COLUMNS = ("id, household_id, payer_user_id, amount_cents, category_id, description, spent_on, split_method,"
                   " one_off, payer_transaction_id, version")


def insert_expense(conn: sqlite3.Connection, *, household_id: int, payer_id: int, amount_cents: int, category_id: int,
                   description: str, spent_on: date, split_method: str, one_off: bool, payer_transaction_id: int,
                   now: datetime) -> int:
    stamp = to_utc_text(now)
    return conn.execute(
        "INSERT INTO shared_expenses (household_id, payer_user_id, amount_cents, category_id, description, spent_on,"
        " split_method, one_off, payer_transaction_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (household_id, payer_id, amount_cents, category_id, description, spent_on.isoformat(), split_method,
         int(one_off), payer_transaction_id, stamp, stamp),
    ).lastrowid


def replace_splits(conn: sqlite3.Connection, *, expense_id: int, weights: dict[int, int | None],
                   shares: dict[int, int]) -> None:
    conn.execute("DELETE FROM shared_expense_splits WHERE expense_id = ?", (expense_id,))
    conn.executemany("INSERT INTO shared_expense_splits (expense_id, user_id, weight, share_cents) VALUES (?, ?, ?, ?)",
                     [(expense_id, user, weights.get(user), share) for user, share in shares.items()])


def get_expense(conn: sqlite3.Connection, expense_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {EXPENSE_COLUMNS} FROM shared_expenses WHERE id = ?", (expense_id,)).fetchone()


def list_expenses(conn: sqlite3.Connection, *, household_id: int) -> list[sqlite3.Row]:
    return conn.execute(f"SELECT {EXPENSE_COLUMNS} FROM shared_expenses WHERE household_id = ?"
                        " ORDER BY spent_on DESC, id DESC", (household_id,)).fetchall()


def splits_of(conn: sqlite3.Connection, expense_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT user_id, weight, share_cents FROM shared_expense_splits WHERE expense_id = ?"
                        " ORDER BY user_id", (expense_id,)).fetchall()


def update_expense(conn: sqlite3.Connection, *, expense_id: int, version: int, amount_cents: int, category_id: int,
                   description: str, spent_on: date, split_method: str, one_off: bool, now: datetime) -> int:
    return conn.execute(
        "UPDATE shared_expenses SET amount_cents = ?, category_id = ?, description = ?, spent_on = ?,"
        " split_method = ?, one_off = ?, updated_at = ?, version = version + 1 WHERE id = ? AND version = ?",
        (amount_cents, category_id, description, spent_on.isoformat(), split_method, int(one_off), to_utc_text(now),
         expense_id, version),
    ).rowcount


def delete_expense(conn: sqlite3.Connection, *, expense_id: int, version: int) -> int:
    return conn.execute("DELETE FROM shared_expenses WHERE id = ? AND version = ?", (expense_id, version)).rowcount


def is_bill_payment(conn: sqlite3.Connection, expense_id: int) -> bool:
    return conn.execute("SELECT 1 FROM household_bill_occurrences WHERE shared_expense_id = ?",
                        (expense_id,)).fetchone() is not None


def share_rows(conn: sqlite3.Connection, *, user_id: int, start: date, end_exclusive: date) -> list[sqlite3.Row]:
    """The user's own shares of shared expenses dated in the range, in any household they belong or belonged to."""
    return conn.execute(
        "SELECT e.id, e.spent_on, e.category_id, e.one_off, sp.share_cents,"
        " EXISTS (SELECT 1 FROM household_bill_occurrences AS o WHERE o.shared_expense_id = e.id) AS from_bill"
        " FROM shared_expense_splits AS sp JOIN shared_expenses AS e ON e.id = sp.expense_id"
        " WHERE sp.user_id = ? AND sp.share_cents > 0 AND e.spent_on >= ? AND e.spent_on < ? ORDER BY e.spent_on, e.id",
        (user_id, start.isoformat(), end_exclusive.isoformat()),
    ).fetchall()


# Settlements (FR-24) --------------------------------------------------------------------------------

SETTLEMENT_COLUMNS = ("id, household_id, payer_user_id, payee_user_id, initiated_by, amount_cents, paid_on, status,"
                      " reason, payer_transaction_id, payee_transaction_id, version, created_at")


def insert_settlement(conn: sqlite3.Connection, *, household_id: int, payer_id: int, payee_id: int,
                      initiated_by: int, amount_cents: int, paid_on: date, now: datetime) -> int:
    return conn.execute(
        "INSERT INTO settlements (household_id, payer_user_id, payee_user_id, initiated_by, amount_cents, paid_on,"
        " status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (household_id, payer_id, payee_id, initiated_by, amount_cents, paid_on.isoformat(), to_utc_text(now)),
    ).lastrowid


def get_settlement(conn: sqlite3.Connection, settlement_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {SETTLEMENT_COLUMNS} FROM settlements WHERE id = ?", (settlement_id,)).fetchone()


def list_settlements(conn: sqlite3.Connection, *, household_id: int) -> list[sqlite3.Row]:
    return conn.execute(f"SELECT {SETTLEMENT_COLUMNS} FROM settlements WHERE household_id = ?"
                        " ORDER BY status = 'pending' DESC, paid_on DESC, id DESC", (household_id,)).fetchall()


def resolve_settlement(conn: sqlite3.Connection, *, settlement_id: int, version: int, status: str, reason: str,
                       payer_transaction_id: int | None, payee_transaction_id: int | None, now: datetime) -> int:
    """Move a pending settlement to a final state; 0 rows means it was no longer pending at that version."""
    return conn.execute(
        "UPDATE settlements SET status = ?, reason = ?, payer_transaction_id = ?, payee_transaction_id = ?,"
        " resolved_at = ?, version = version + 1 WHERE id = ? AND status = 'pending' AND version = ?",
        (status, reason, payer_transaction_id, payee_transaction_id, to_utc_text(now), settlement_id, version),
    ).rowcount


def pending_for_counterparty(conn: sqlite3.Connection, *, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        f"SELECT {SETTLEMENT_COLUMNS} FROM settlements WHERE status = 'pending' AND initiated_by <> ?"
        " AND ? IN (payer_user_id, payee_user_id) ORDER BY id", (user_id, user_id),
    ).fetchall()
