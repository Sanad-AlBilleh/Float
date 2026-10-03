"""Shared expenses: who paid, how it was split, and the link to the payer's ledger expense (FR-20–22).

The application layer creates the payer's ``shared`` ledger expense first and passes its ID in, so
both rows are written in one transaction.
"""

import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime

from app.households import repository
from app.households.rules import DESCRIPTION_LIMIT, SplitEntry, allocate
from app.households.service import active_member_ids, require_open
from app.shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.shared.money import MAX_CENTS

SQLITE_MAX_ID = 2**63 - 1
STALE_MESSAGE = "This expense changed since you opened it. Reload the page and try again."
BILL_MESSAGE = "This expense pays a household bill. Undo that payment on the Bills tab instead."


@dataclass(frozen=True)
class ExpenseDraft:
    amount_cents: int
    spent_on: date
    category_id: int | None
    description: str
    one_off: bool
    split_method: str
    entries: tuple[SplitEntry, ...]


@dataclass(frozen=True)
class SharedExpense:
    id: int
    household_id: int
    payer_user_id: int
    amount_cents: int
    category_id: int
    description: str
    spent_on: date
    split_method: str
    one_off: bool
    payer_transaction_id: int
    version: int
    shares: dict[int, int]
    weights: dict[int, int | None]


def _expense(conn: sqlite3.Connection, row: sqlite3.Row) -> SharedExpense:
    splits = repository.splits_of(conn, row["id"])
    return SharedExpense(row["id"], row["household_id"], row["payer_user_id"], row["amount_cents"], row["category_id"],
                         row["description"], date.fromisoformat(row["spent_on"]), row["split_method"],
                         bool(row["one_off"]), row["payer_transaction_id"], row["version"],
                         {s["user_id"]: s["share_cents"] for s in splits}, {s["user_id"]: s["weight"] for s in splits})


def get_expense(conn: sqlite3.Connection, *, expense_id: int) -> SharedExpense:
    row = repository.get_expense(conn, expense_id) if 1 <= expense_id <= SQLITE_MAX_ID else None
    if row is None:
        raise NotFoundError("No such expense.")
    return _expense(conn, row)


def list_expenses(conn: sqlite3.Connection, *, household_id: int) -> list[SharedExpense]:
    return [_expense(conn, row) for row in repository.list_expenses(conn, household_id=household_id)]


def check_draft(conn: sqlite3.Connection, *, household_id: int, draft: ExpenseDraft,
                category_ids: Collection[int]) -> dict[int, int]:
    """Every problem with the draft, at once; returns the allocated shares when it is valid."""
    errors: dict[str, str] = {}
    if not 1 <= draft.amount_cents <= MAX_CENTS:
        errors["amount"] = "Enter an amount between €0.01 and €1,000,000.00."
    if draft.category_id not in category_ids:
        errors["category_id"] = "Choose a category."
    if not 1 <= len(draft.description) <= DESCRIPTION_LIMIT:
        errors["description"] = f"Describe it in 1 to {DESCRIPTION_LIMIT} characters."
    members = set(active_member_ids(conn, household_id=household_id))
    if any(entry.user_id not in members for entry in draft.entries):
        errors["participants"] = "Choose participants from the household's current members."
    shares: dict[int, int] = {}
    if "amount" not in errors and "participants" not in errors:
        try:
            shares = allocate(draft.amount_cents, draft.split_method, draft.entries)
        except ValidationError as error:
            errors.update(error.errors)
    if errors:
        raise ValidationError(errors)
    return shares


def create_expense(conn: sqlite3.Connection, *, household_id: int, payer_id: int, draft: ExpenseDraft,
                   category_ids: Collection[int], payer_transaction_id: int, now: datetime) -> SharedExpense:
    require_open(conn, household_id=household_id)
    shares = check_draft(conn, household_id=household_id, draft=draft, category_ids=category_ids)
    expense_id = repository.insert_expense(
        conn, household_id=household_id, payer_id=payer_id, amount_cents=draft.amount_cents,
        category_id=draft.category_id, description=draft.description, spent_on=draft.spent_on,
        split_method=draft.split_method, one_off=draft.one_off, payer_transaction_id=payer_transaction_id, now=now,
    )
    repository.replace_splits(conn, expense_id=expense_id, weights={e.user_id: e.value for e in draft.entries},
                              shares=shares)
    return get_expense(conn, expense_id=expense_id)


def editable(conn: sqlite3.Connection, *, expense_id: int, user_id: int, version: int | None = None) -> SharedExpense:
    """The expense, if ``user_id`` paid it, it is not a bill payment, and (when given) the version is current."""
    expense = get_expense(conn, expense_id=expense_id)
    require_open(conn, household_id=expense.household_id)
    if expense.payer_user_id != user_id:
        raise PermissionDeniedError("Only the person who paid can change this expense.")
    if repository.is_bill_payment(conn, expense_id):
        raise ConflictError(BILL_MESSAGE)
    if version is not None and expense.version != version:
        raise ConflictError(STALE_MESSAGE)
    return expense


def update_expense(conn: sqlite3.Connection, *, expense_id: int, user_id: int, version: int, draft: ExpenseDraft,
                   category_ids: Collection[int], now: datetime) -> SharedExpense:
    expense = editable(conn, expense_id=expense_id, user_id=user_id, version=version)
    shares = check_draft(conn, household_id=expense.household_id, draft=draft, category_ids=category_ids)
    if repository.update_expense(conn, expense_id=expense_id, version=version, amount_cents=draft.amount_cents,
                                 category_id=draft.category_id, description=draft.description,
                                 spent_on=draft.spent_on, split_method=draft.split_method, one_off=draft.one_off,
                                 now=now) != 1:
        raise ConflictError(STALE_MESSAGE)
    repository.replace_splits(conn, expense_id=expense_id, weights={e.user_id: e.value for e in draft.entries},
                              shares=shares)
    return get_expense(conn, expense_id=expense_id)


def delete_expense(conn: sqlite3.Connection, *, expense_id: int, user_id: int, version: int) -> SharedExpense:
    """Delete the expense and its splits; the caller then deletes the linked ledger expense."""
    expense = editable(conn, expense_id=expense_id, user_id=user_id, version=version)
    if repository.delete_expense(conn, expense_id=expense_id, version=version) != 1:
        raise ConflictError(STALE_MESSAGE)
    return expense


@dataclass(frozen=True)
class ShareRow:
    expense_id: int
    spent_on: date
    category_id: int
    share_cents: int
    one_off: bool
    from_household_bill: bool


def share_rows(conn: sqlite3.Connection, *, user_id: int, start: date, end_exclusive: date) -> list[ShareRow]:
    return [ShareRow(row["id"], date.fromisoformat(row["spent_on"]), row["category_id"], row["share_cents"],
                     bool(row["one_off"]), bool(row["from_bill"]))
            for row in repository.share_rows(conn, user_id=user_id, start=start, end_exclusive=end_exclusive)]
