"""What the personal service needs from households, for one user (Assignment 2, ADR-6).

In A1 the dashboard and the alerts read these tables directly. They now ask this service, through
/internal, and these functions build the answers. Each one is read-only apart from materializing
household bill dates, which A1 also did on read (FR-10).
"""

import json
from dataclasses import dataclass
from datetime import date

from app.db.connection import Connection
from app.db.unit_of_work import transaction
from app.households import api as households

# Audit events that tell other members "someone added an expense you share" (FR-32).
EXPENSE_EVENTS = (("shared_expense", "create"), ("shared_expense", "update"), ("household_bill_occurrence", "pay"))


@dataclass(frozen=True)
class OpenBill:
    occurrence_id: int
    household_id: int
    name: str
    due_date: date
    share_cents: int


@dataclass(frozen=True)
class PositionView:
    in_household: bool
    bill_shares_cents: int
    payables_cents: int
    receivables_cents: int
    commitments: list[dict]
    open_bills: list[OpenBill]


def position(conn: Connection, *, user_id: int, window_end: date, horizon_end: date) -> PositionView:
    with transaction(conn):  # idempotent bookkeeping, as on the A1 dashboard
        households.materialize_for_user(conn, user_id=user_id, horizon_end=horizon_end)
    terms = households.get_position(conn, user_id=user_id, window_end=window_end, horizon_end=horizon_end)
    memberships = households.user_households(conn, user_id=user_id)
    open_bills = []
    for household, active in memberships:
        if not active or household.archived:
            continue
        series = {s.id: s for s in households.list_bill_series(conn, household_id=household.id)}
        for o in households.list_bill_occurrences(conn, household_id=household.id, end_exclusive=horizon_end):
            share = households.share_of(series[o.series_id], o, user_id)
            if o.shared_expense_id is None and not o.skipped and share:
                open_bills.append(OpenBill(o.id, household.id, f"{o.name} ({household.name})", o.due_date, share))
    return PositionView(
        in_household=bool(memberships),
        bill_shares_cents=terms.bill_shares_cents,
        payables_cents=terms.payables_cents,
        receivables_cents=terms.receivables_cents,
        commitments=[{"due_date": due, "amount_cents": cents} for due, cents in terms.commitments],
        open_bills=open_bills,
    )


def shares(conn: Connection, *, user_id: int, start: date, end_exclusive: date) -> list[dict]:
    return [{"amount_cents": r.share_cents, "occurred_on": r.spent_on, "category_id": r.category_id,
             "from_household_bill": r.from_household_bill, "one_off": r.one_off}
            for r in households.share_rows(conn, user_id=user_id, start=start, end_exclusive=end_exclusive)]


def events(conn: Connection, *, user_id: int, after: int) -> dict:
    """Shared-expense events after the caller's cursor, in households the user is in, and settlements
    waiting for the user. ``last_id`` is the new cursor, even when no event concerned the user."""
    active = [h.id for h, is_active in households.user_households(conn, user_id=user_id) if is_active]
    expenses, last = [], after
    if active:
        rows = conn.execute(
            f"SELECT id, actor_user_id, household_id, entity_type, action, after_json FROM audit_events"
            f" WHERE id > ? AND household_id IN ({','.join('?' * len(active))}) ORDER BY id",
            (after, *active),
        ).fetchall()
        for row in rows:
            last = row["id"]
            if (row["entity_type"], row["action"]) not in EXPENSE_EVENTS or row["actor_user_id"] == user_id:
                continue
            data = json.loads(row["after_json"] or "{}")
            share = int(data.get("shares", {}).get(str(user_id), 0))
            if share > 0:
                expenses.append({"audit_event_id": row["id"], "household_id": row["household_id"],
                                 "actor_user_id": row["actor_user_id"],
                                 "description": data.get("description", "an expense"), "share_cents": share})
    settlements = []
    for s in households.awaiting(conn, user_id=user_id):
        other = s.initiated_by
        settlements.append({"settlement_id": s.id, "household_id": s.household_id, "other_user_id": other,
                            "amount_cents": s.amount_cents,
                            "verb": "paid you" if s.payer_user_id == other else "received from you"})
    return {"last_id": last, "expenses": expenses, "settlements": settlements}
