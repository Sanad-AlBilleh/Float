"""Settlements: transfers made outside Float, confirmed by the other party (FR-24, SRS §5).

Status changes are ``UPDATE … WHERE status = 'pending' AND version = ?``, so a repeated or racing
request can apply a transition at most once. The application layer writes both ledgers and the
transition in one transaction.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from app.households import repository
from app.households.rules import REASON_LIMIT, simplify
from app.households.service import active_member_ids, balances, require_open
from app.shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.shared.money import MAX_CENTS

SQLITE_MAX_ID = 2**63 - 1
CHANGED_MESSAGE = "This settlement is no longer pending, or it changed since you opened it. Reload the page."


@dataclass(frozen=True)
class Settlement:
    id: int
    household_id: int
    payer_user_id: int
    payee_user_id: int
    initiated_by: int
    amount_cents: int
    paid_on: date
    status: str  # pending, confirmed, rejected, or cancelled
    reason: str
    payer_transaction_id: int | None
    payee_transaction_id: int | None
    version: int

    @property
    def counterparty(self) -> int:
        return self.payee_user_id if self.initiated_by == self.payer_user_id else self.payer_user_id


def _settlement(row: sqlite3.Row) -> Settlement:
    return Settlement(row["id"], row["household_id"], row["payer_user_id"], row["payee_user_id"],
                      row["initiated_by"], row["amount_cents"], date.fromisoformat(row["paid_on"]), row["status"],
                      row["reason"], row["payer_transaction_id"], row["payee_transaction_id"], row["version"])


def get_settlement(conn: sqlite3.Connection, *, settlement_id: int) -> Settlement:
    row = repository.get_settlement(conn, settlement_id) if 1 <= settlement_id <= SQLITE_MAX_ID else None
    if row is None:
        raise NotFoundError("No such settlement.")
    return _settlement(row)


def list_settlements(conn: sqlite3.Connection, *, household_id: int) -> list[Settlement]:
    return [_settlement(row) for row in repository.list_settlements(conn, household_id=household_id)]


def suggested_amount(conn: sqlite3.Connection, *, household_id: int, payer_id: int, payee_id: int) -> int:
    """What the settle-up plan says ``payer_id`` should pay ``payee_id`` (0 if nothing)."""
    plan = simplify(balances(conn, household_id=household_id))
    return sum(t.amount_cents for t in plan if (t.from_user, t.to_user) == (payer_id, payee_id))


def create_settlement(conn: sqlite3.Connection, *, household_id: int, initiated_by: int, payer_id: int,
                      payee_id: int, amount_cents: int, paid_on: date, today: date,
                      now: datetime) -> tuple[Settlement, bool]:
    """Record a pending transfer. Also returns whether it is more than the settle-up plan suggests."""
    require_open(conn, household_id=household_id)
    if initiated_by not in (payer_id, payee_id):
        raise PermissionDeniedError("You can only record a transfer you paid or received.")
    errors: dict[str, str] = {}
    members = set(active_member_ids(conn, household_id=household_id))
    if payer_id == payee_id or not {payer_id, payee_id} <= members:
        errors["counterparty"] = "Choose another current member of the household."
    if not 1 <= amount_cents <= MAX_CENTS:
        errors["amount"] = "Enter an amount between €0.01 and €1,000,000.00."
    if paid_on > today:
        errors["paid_on"] = "A transfer cannot be dated in the future."
    if errors:
        raise ValidationError(errors)
    over = amount_cents > suggested_amount(conn, household_id=household_id, payer_id=payer_id, payee_id=payee_id)
    settlement_id = repository.insert_settlement(conn, household_id=household_id, payer_id=payer_id,
                                                 payee_id=payee_id, initiated_by=initiated_by,
                                                 amount_cents=amount_cents, paid_on=paid_on, now=now)
    return get_settlement(conn, settlement_id=settlement_id), over


def pending(conn: sqlite3.Connection, *, settlement_id: int, version: int, user_id: int,
            role: str) -> Settlement:
    """The settlement, if it is still pending at ``version`` and ``user_id`` may act as ``role``."""
    settlement = get_settlement(conn, settlement_id=settlement_id)
    if role == "counterparty" and user_id != settlement.counterparty:
        raise PermissionDeniedError("Only the other person in this transfer can confirm or reject it.")
    if role == "initiator" and user_id != settlement.initiated_by:
        raise PermissionDeniedError("Only the person who recorded this transfer can cancel it.")
    if settlement.status != "pending" or settlement.version != version:
        raise ConflictError(CHANGED_MESSAGE)
    return settlement


def resolve(conn: sqlite3.Connection, *, settlement_id: int, version: int, status: str, reason: str = "",
            payer_transaction_id: int | None = None, payee_transaction_id: int | None = None,
            now: datetime) -> Settlement:
    if len(reason) > REASON_LIMIT:
        raise ValidationError.single("reason", f"Keep the reason to {REASON_LIMIT} characters.")
    if repository.resolve_settlement(conn, settlement_id=settlement_id, version=version, status=status, reason=reason,
                                     payer_transaction_id=payer_transaction_id,
                                     payee_transaction_id=payee_transaction_id, now=now) != 1:
        raise ConflictError(CHANGED_MESSAGE)
    return get_settlement(conn, settlement_id=settlement_id)


def awaiting(conn: sqlite3.Connection, *, user_id: int) -> list[Settlement]:
    """Pending settlements this user is asked to confirm or reject (for alerts)."""
    return [_settlement(row) for row in repository.pending_for_counterparty(conn, user_id=user_id)]
