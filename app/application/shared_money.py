"""Shared expenses, settlements, and household bills: workflows that write Households rows and personal Ledger
rows in one transaction, with an audit event carrying the household's ID (FR-20–26, FR-33, SRS §6.3)."""

import sqlite3
from dataclasses import asdict
from datetime import date

from app.application import audit
from app.application.authz import require_member, require_viewer
from app.application.context import Actor
from app.db.unit_of_work import transaction
from app.households import api as households
from app.insights import api as insights
from app.ledger import api as ledger
from app.shared.clock import Clock
from app.shared.errors import NotFoundError, ValidationError

ExpenseDraft = households.ExpenseDraft


def _audit(conn, actor: Actor, household_id: int, entity_type: str, entity_id: int, action: str, clock: Clock,
           before=None, after=None) -> None:
    audit.record(conn, actor_user_id=actor.user_id, household_id=household_id, entity_type=entity_type,
                 entity_id=entity_id, action=action, now=clock.now_utc(), before=before, after=after,
                 request_id=actor.request_id)


def _category_ids(conn: sqlite3.Connection) -> set[int]:
    return {category.id for category in ledger.list_categories(conn)}


def _renamed(error: ValidationError, field: str) -> ValidationError:
    """The Ledger calls its date ``occurred_on``; forms here call it something else."""
    return ValidationError({field if name == "occurred_on" else name: message for name, message in error.errors.items()})


# Shared expenses (FR-20–22) --------------------------------------------------------------------------

def expense_problems(conn: sqlite3.Connection, actor: Actor, household_id: int, draft: ExpenseDraft,
                     clock: Clock) -> dict[str, str]:
    """Both domains' rules for a draft, as field messages (empty when valid)."""
    errors: dict[str, str] = {}
    try:
        households.check_draft(conn, household_id=household_id, draft=draft, category_ids=_category_ids(conn))
    except ValidationError as error:
        errors.update(error.errors)
    settings = ledger.get_settings(conn, actor.user_id)
    if draft.spent_on > clock.today():
        errors["spent_on"] = "Future expenses cannot be recorded yet."
    elif settings is not None and draft.spent_on < settings.tracking_start:
        errors["spent_on"] = f"Choose a date on or after {settings.tracking_start.isoformat()}, when your tracking started."
    return errors


def list_expenses(conn: sqlite3.Connection, actor: Actor, household_id: int) -> list[households.SharedExpense]:
    require_viewer(conn, actor.user_id, household_id)
    return households.list_expenses(conn, household_id=household_id)


def get_expense(conn: sqlite3.Connection, actor: Actor, household_id: int,
                expense_id: int) -> households.SharedExpense:
    require_viewer(conn, actor.user_id, household_id)
    expense = households.get_expense(conn, expense_id=expense_id)
    if expense.household_id != household_id:
        raise NotFoundError("No such expense.")
    return expense


def check_editable(conn: sqlite3.Connection, actor: Actor, expense_id: int) -> households.SharedExpense:
    """403 for anyone but the payer, 409 for a bill payment, before a form is shown or read."""
    return households.editable(conn, expense_id=expense_id, user_id=actor.user_id)


def record_expense(conn: sqlite3.Connection, actor: Actor, household_id: int, draft: ExpenseDraft,
                   clock: Clock) -> households.SharedExpense:
    """FR-20: the expense, its splits, and the payer's ``shared`` ledger expense for the full amount, together."""
    with transaction(conn):
        require_member(conn, actor.user_id, household_id)
        errors = expense_problems(conn, actor, household_id, draft, clock)
        if errors:
            raise ValidationError(errors)
        transaction_id = ledger.create_linked(
            conn, user_id=actor.user_id, kind="expense", origin="shared", amount_cents=draft.amount_cents,
            occurred_on=draft.spent_on, category_id=draft.category_id, income_source=None, note=draft.description,
            today=clock.today(), now=clock.now_utc(),
        )
        expense = households.create_expense(conn, household_id=household_id, payer_id=actor.user_id, draft=draft,
                                            category_ids=_category_ids(conn), payer_transaction_id=transaction_id,
                                            now=clock.now_utc())
        _audit(conn, actor, household_id, "shared_expense", expense.id, "create", clock, after=asdict(expense))
    return expense


def edit_expense(conn: sqlite3.Connection, actor: Actor, expense_id: int, version: int, draft: ExpenseDraft,
                 clock: Clock) -> households.SharedExpense:
    """FR-22: only the payer, only from the current version; the ledger expense changes in the same transaction."""
    with transaction(conn):
        before = households.get_expense(conn, expense_id=expense_id)
        require_member(conn, actor.user_id, before.household_id)
        households.editable(conn, expense_id=expense_id, user_id=actor.user_id, version=version)
        errors = expense_problems(conn, actor, before.household_id, draft, clock)
        if errors:
            raise ValidationError(errors)
        after = households.update_expense(conn, expense_id=expense_id, user_id=actor.user_id, version=version,
                                          draft=draft, category_ids=_category_ids(conn), now=clock.now_utc())
        try:
            ledger.update_linked(conn, user_id=actor.user_id, transaction_id=after.payer_transaction_id,
                                 origin="shared", amount_cents=after.amount_cents, occurred_on=after.spent_on,
                                 category_id=after.category_id, today=clock.today(), now=clock.now_utc())
        except ValidationError as error:
            raise _renamed(error, "spent_on") from None
        _audit(conn, actor, before.household_id, "shared_expense", expense_id, "update", clock,
               asdict(before), asdict(after))
    return after


def delete_expense(conn: sqlite3.Connection, actor: Actor, expense_id: int, version: int, clock: Clock) -> None:
    with transaction(conn):
        before = households.get_expense(conn, expense_id=expense_id)
        require_member(conn, actor.user_id, before.household_id)
        removed = households.delete_expense(conn, expense_id=expense_id, user_id=actor.user_id, version=version)
        ledger.delete_linked(conn, user_id=actor.user_id, transaction_id=removed.payer_transaction_id, origin="shared")
        _audit(conn, actor, before.household_id, "shared_expense", expense_id, "delete", clock, before=asdict(removed))


def share_rows(conn: sqlite3.Connection, user_id: int, start: date, end_exclusive: date):
    """The user's shares of shared expenses, for consumption (SRS §4.7)."""
    return [insights.ShareRow(row.share_cents, row.spent_on, row.category_id, row.from_household_bill, row.one_off)
            for row in households.share_rows(conn, user_id=user_id, start=start, end_exclusive=end_exclusive)]
