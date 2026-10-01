"""Ledger use cases on an open connection: settings, transactions, balance, and queries (FR-05–08).

Manual transactions belong to their owner and carry a version for stale-edit detection. Linked
transactions (bill payments, shared expenses, settlements) are changed only by the workflow
that owns them, through the ``*_linked`` functions (FR-07).
"""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from app.ledger import repository
from app.ledger.rules import (
    DIRECTLY_EDITABLE,
    LINKED_ORIGINS,
    TransactionDraft,
    validate_draft,
    validate_occurred_on,
    validate_settings,
)
from app.shared.errors import ConflictError, NotFoundError

LINKED_MESSAGE = "This transaction is managed by its bill, shared expense, or settlement."
STALE_MESSAGE = "This transaction changed since you opened it. Reload the page and try again."
SETUP_MESSAGE = "Complete setup first."


@dataclass(frozen=True)
class LedgerSettings:
    user_id: int
    tracking_start: date
    opening_balance_cents: int


@dataclass(frozen=True)
class Category:
    id: int
    slug: str
    name: str


@dataclass(frozen=True)
class Transaction:
    id: int
    user_id: int
    kind: str
    amount_cents: int
    occurred_on: date
    category_id: int | None
    income_source: str | None
    origin: str
    one_off: bool
    note: str
    version: int

    @property
    def directly_editable(self) -> bool:
        return self.origin in DIRECTLY_EDITABLE


@dataclass(frozen=True)
class ExpenseRow:
    id: int
    amount_cents: int
    occurred_on: date
    category_id: int | None
    origin: str
    one_off: bool


def _transaction(row: sqlite3.Row) -> Transaction:
    return Transaction(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        amount_cents=row["amount_cents"],
        occurred_on=date.fromisoformat(row["occurred_on"]),
        category_id=row["category_id"],
        income_source=row["income_source"],
        origin=row["origin"],
        one_off=bool(row["one_off"]),
        note=row["note"],
        version=row["version"],
    )


def save_settings(conn: sqlite3.Connection, *, user_id: int, tracking_start: date, opening_balance_cents: int,
                  today: date) -> LedgerSettings:
    if repository.get_settings(conn, user_id) is not None:
        raise ConflictError("Setup is already complete.")
    validate_settings(tracking_start=tracking_start, opening_balance_cents=opening_balance_cents, today=today)
    repository.insert_settings(
        conn, user_id=user_id, tracking_start=tracking_start, opening_balance_cents=opening_balance_cents
    )
    return LedgerSettings(user_id, tracking_start, opening_balance_cents)


def get_settings(conn: sqlite3.Connection, user_id: int) -> LedgerSettings | None:
    row = repository.get_settings(conn, user_id)
    if row is None:
        return None
    return LedgerSettings(row["user_id"], date.fromisoformat(row["tracking_start_date"]), row["opening_balance_cents"])


def _require_settings(conn: sqlite3.Connection, user_id: int) -> LedgerSettings:
    settings = get_settings(conn, user_id)
    if settings is None:
        raise ConflictError(SETUP_MESSAGE)
    return settings


def list_categories(conn: sqlite3.Connection) -> list[Category]:
    return [Category(row["id"], row["slug"], row["name"]) for row in repository.list_categories(conn)]


def _category_ids(conn: sqlite3.Connection) -> set[int]:
    return {category.id for category in list_categories(conn)}


def get_transaction(conn: sqlite3.Connection, *, user_id: int, transaction_id: int) -> Transaction:
    row = repository.get_transaction(conn, transaction_id)
    if row is None or row["user_id"] != user_id:
        raise NotFoundError("No such transaction.")
    return _transaction(row)


def create_manual(conn: sqlite3.Connection, *, user_id: int, draft: TransactionDraft, today: date,
                  now: datetime) -> Transaction:
    settings = _require_settings(conn, user_id)
    validate_draft(draft, tracking_start=settings.tracking_start, today=today, category_ids=_category_ids(conn))
    transaction_id = repository.insert_transaction(
        conn,
        user_id=user_id,
        kind=draft.kind,
        amount_cents=draft.amount_cents,
        occurred_on=draft.occurred_on,
        category_id=draft.category_id,
        income_source=draft.income_source,
        origin="manual",
        one_off=draft.one_off,
        note=draft.note,
        now=now,
    )
    return get_transaction(conn, user_id=user_id, transaction_id=transaction_id)


def update_manual(conn: sqlite3.Connection, *, user_id: int, transaction_id: int, version: int,
                  draft: TransactionDraft, today: date, now: datetime) -> Transaction:
    current = get_transaction(conn, user_id=user_id, transaction_id=transaction_id)
    if not current.directly_editable:
        raise ConflictError(LINKED_MESSAGE)
    settings = _require_settings(conn, user_id)
    validate_draft(draft, tracking_start=settings.tracking_start, today=today, category_ids=_category_ids(conn))
    changed = repository.update_manual(
        conn,
        transaction_id=transaction_id,
        user_id=user_id,
        version=version,
        kind=draft.kind,
        amount_cents=draft.amount_cents,
        occurred_on=draft.occurred_on,
        category_id=draft.category_id,
        income_source=draft.income_source,
        one_off=draft.one_off,
        note=draft.note,
        now=now,
    )
    if changed == 0:
        raise ConflictError(STALE_MESSAGE)
    return get_transaction(conn, user_id=user_id, transaction_id=transaction_id)


def delete_manual(conn: sqlite3.Connection, *, user_id: int, transaction_id: int, version: int) -> Transaction:
    current = get_transaction(conn, user_id=user_id, transaction_id=transaction_id)
    if not current.directly_editable:
        raise ConflictError(LINKED_MESSAGE)
    if repository.delete_transaction(conn, transaction_id=transaction_id, user_id=user_id, version=version) == 0:
        raise ConflictError(STALE_MESSAGE)
    return current


def list_transactions(conn: sqlite3.Connection, *, user_id: int, limit: int = 50,
                      before: tuple[date, int] | None = None) -> list[Transaction]:
    rows = repository.list_transactions(conn, user_id=user_id, limit=limit, before=before)
    return [_transaction(row) for row in rows]


def get_balance(conn: sqlite3.Connection, *, user_id: int, as_of: date) -> int:
    """Opening balance + income − expenses from the tracking start date through ``as_of``."""
    value = repository.balance(conn, user_id=user_id, as_of=as_of)
    if value is None:
        raise ConflictError(SETUP_MESSAGE)
    return value


def _linked(conn: sqlite3.Connection, *, user_id: int, transaction_id: int, origin: str) -> Transaction:
    current = get_transaction(conn, user_id=user_id, transaction_id=transaction_id)
    if current.origin != origin:
        raise ConflictError(f"Transaction {transaction_id} is not managed by a {origin} workflow.")
    return current


def create_linked(conn: sqlite3.Connection, *, user_id: int, kind: str, origin: str, amount_cents: int,
                  occurred_on: date, category_id: int | None, income_source: str | None, note: str,
                  today: date, now: datetime) -> int:
    """Record a money movement owned by a workflow (bill payment, shared expense, settlement)."""
    if origin not in LINKED_ORIGINS:
        raise ValueError(f"create_linked cannot create {origin!r} transactions")
    settings = _require_settings(conn, user_id)
    validate_occurred_on(occurred_on, tracking_start=settings.tracking_start, today=today)
    return repository.insert_transaction(
        conn,
        user_id=user_id,
        kind=kind,
        amount_cents=amount_cents,
        occurred_on=occurred_on,
        category_id=category_id,
        income_source=income_source,
        origin=origin,
        one_off=False,
        note=note,
        now=now,
    )


def update_linked(conn: sqlite3.Connection, *, user_id: int, transaction_id: int, origin: str, amount_cents: int,
                  occurred_on: date, category_id: int | None, today: date, now: datetime) -> None:
    _linked(conn, user_id=user_id, transaction_id=transaction_id, origin=origin)
    settings = _require_settings(conn, user_id)
    validate_occurred_on(occurred_on, tracking_start=settings.tracking_start, today=today)
    repository.update_linked(
        conn, transaction_id=transaction_id, amount_cents=amount_cents, occurred_on=occurred_on,
        category_id=category_id, now=now,
    )


def delete_linked(conn: sqlite3.Connection, *, user_id: int, transaction_id: int, origin: str) -> None:
    _linked(conn, user_id=user_id, transaction_id=transaction_id, origin=origin)
    repository.delete_transaction(conn, transaction_id=transaction_id, user_id=user_id)


def has_allowance_income(conn: sqlite3.Connection, *, user_id: int, start: date, end_inclusive: date) -> bool:
    return repository.has_income(conn, user_id=user_id, source="allowance", start=start, end_inclusive=end_inclusive)


def get_expense_rows(conn: sqlite3.Connection, *, user_id: int, start: date, end_exclusive: date) -> list[ExpenseRow]:
    return [
        ExpenseRow(
            id=row["id"],
            amount_cents=row["amount_cents"],
            occurred_on=date.fromisoformat(row["occurred_on"]),
            category_id=row["category_id"],
            origin=row["origin"],
            one_off=bool(row["one_off"]),
        )
        for row in repository.expense_rows(conn, user_id=user_id, start=start, end_exclusive=end_exclusive)
    ]
