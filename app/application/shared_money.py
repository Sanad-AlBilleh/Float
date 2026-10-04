"""Shared expenses, settlements, and household bills: workflows that write Households rows and personal Ledger
rows in one transaction, with an audit event carrying the household's ID (FR-20–26, FR-33, SRS §6.3)."""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date

from app.application import audit
from app.application.authz import require_member, require_owner, require_viewer
from app.application.context import Actor
from app.application.households import display_names
from app.db.unit_of_work import transaction
from app.households import api as households
from app.ledger import api as ledger
from app.planning import api as planning
from app.shared.clock import Clock
from app.shared.dates import Cycle, cycle_for
from app.shared.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.shared.recurrence import Rule

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


# Settlements (FR-24) -----------------------------------------------------------------------------------

def _check_paid_on(conn: sqlite3.Connection, paid_on: date, *user_ids: int) -> None:
    for user_id in user_ids:
        settings = ledger.get_settings(conn, user_id)
        if settings is not None and paid_on < settings.tracking_start:
            raise ValidationError.single(
                "paid_on", f"Choose a date on or after {settings.tracking_start.isoformat()}: both people must have "
                           "been tracking by then.")


def record_settlement(conn: sqlite3.Connection, actor: Actor, household_id: int, payer_id: int, payee_id: int,
                      amount_cents: int, paid_on: date, clock: Clock) -> tuple[households.Settlement, bool]:
    """Record a pending transfer; nothing moves until the other person confirms. Also returns the over-plan warning."""
    with transaction(conn):
        require_member(conn, actor.user_id, household_id)
        settlement, over = households.create_settlement(
            conn, household_id=household_id, initiated_by=actor.user_id, payer_id=payer_id, payee_id=payee_id,
            amount_cents=amount_cents, paid_on=paid_on, today=clock.today(), now=clock.now_utc())
        _check_paid_on(conn, paid_on, payer_id, payee_id)
        _audit(conn, actor, household_id, "settlement", settlement.id, "create", clock, after=asdict(settlement))
    return settlement, over


def _settlement_for(conn: sqlite3.Connection, actor: Actor, settlement_id: int) -> households.Settlement:
    settlement = households.get_settlement(conn, settlement_id=settlement_id)
    require_member(conn, actor.user_id, settlement.household_id)
    return settlement


def confirm_settlement(conn: sqlite3.Connection, actor: Actor, settlement_id: int, version: int,
                       clock: Clock) -> households.Settlement:
    """FR-24: the counterparty confirms; both ledgers and the status change together, or nothing does."""
    with transaction(conn):
        _settlement_for(conn, actor, settlement_id)
        settlement = households.pending(conn, settlement_id=settlement_id, version=version, user_id=actor.user_id,
                                        role="counterparty")
        names = display_names(conn, [settlement.payer_user_id, settlement.payee_user_id])
        common = {"origin": "settlement", "amount_cents": settlement.amount_cents, "occurred_on": settlement.paid_on,
                  "category_id": None, "today": clock.today(), "now": clock.now_utc()}
        try:
            paid = ledger.create_linked(conn, user_id=settlement.payer_user_id, kind="expense", income_source=None,
                                        note=f"Settlement to {names[settlement.payee_user_id]}", **common)
            received = ledger.create_linked(conn, user_id=settlement.payee_user_id, kind="income",
                                            income_source="settlement",
                                            note=f"Settlement from {names[settlement.payer_user_id]}", **common)
        except ValidationError as error:
            raise _renamed(error, "paid_on") from None
        after = households.resolve(conn, settlement_id=settlement_id, version=version, status="confirmed",
                                   payer_transaction_id=paid, payee_transaction_id=received, now=clock.now_utc())
        _audit(conn, actor, settlement.household_id, "settlement", settlement_id, "confirm", clock,
               asdict(settlement), asdict(after))
    return after


def _close(conn: sqlite3.Connection, actor: Actor, settlement_id: int, version: int, clock: Clock, *, status: str,
           role: str, action: str, reason: str = "") -> households.Settlement:
    with transaction(conn):
        _settlement_for(conn, actor, settlement_id)
        settlement = households.pending(conn, settlement_id=settlement_id, version=version, user_id=actor.user_id,
                                        role=role)
        after = households.resolve(conn, settlement_id=settlement_id, version=version, status=status, reason=reason,
                                   now=clock.now_utc())
        _audit(conn, actor, settlement.household_id, "settlement", settlement_id, action, clock,
               asdict(settlement), asdict(after))
    return after


def reject_settlement(conn: sqlite3.Connection, actor: Actor, settlement_id: int, version: int, reason: str,
                      clock: Clock) -> households.Settlement:
    return _close(conn, actor, settlement_id, version, clock, status="rejected", role="counterparty", action="reject",
                  reason=reason)


def cancel_settlement(conn: sqlite3.Connection, actor: Actor, settlement_id: int, version: int,
                      clock: Clock) -> households.Settlement:
    return _close(conn, actor, settlement_id, version, clock, status="cancelled", role="initiator", action="cancel")


def settlement_household(conn: sqlite3.Connection, settlement_id: int) -> int:
    return households.get_settlement(conn, settlement_id=settlement_id).household_id


# Household bills (FR-25–26) ------------------------------------------------------------------------------

@dataclass(frozen=True)
class HouseholdBillInput:
    name: str
    amount_cents: int
    category_id: int | None
    rule: Rule
    split_method: str
    entries: tuple[households.SplitEntry, ...]


@dataclass(frozen=True)
class HouseholdBillRow:
    id: int
    series_id: int
    name: str
    category_id: int
    scheduled_date: date
    due_date: date
    amount_cents: int
    skipped: bool
    shared_expense_id: int | None
    version: int
    status: str  # paid, skipped, overdue, reserved, or upcoming, from the viewer's cycle
    my_share_cents: int
    participant: bool
    payer_user_id: int | None


@dataclass(frozen=True)
class HouseholdBillsView:
    series: list[households.HouseholdBillSeries]
    occurrences: list[HouseholdBillRow]


def _viewer_cycle(conn: sqlite3.Connection, user_id: int, clock: Clock) -> Cycle:
    settings = planning.get_settings(conn, user_id)
    return cycle_for(clock.today(), settings.allowance_day if settings else 1)


def household_bills(conn: sqlite3.Connection, actor: Actor, household_id: int, clock: Clock) -> HouseholdBillsView:
    """The household's bills as the viewer sees them: status from their own cycle, and their share.

    Former members see none: current bills are for current members only (review finding 6).
    """
    if require_viewer(conn, actor.user_id, household_id).status != "active":
        return HouseholdBillsView([], [])
    cycle = _viewer_cycle(conn, actor.user_id, clock)
    if not households.get_household(conn, household_id=household_id).archived:
        with transaction(conn):
            households.ensure_materialized(conn, household_id=household_id, horizon_end=cycle.horizon_end)
    series = households.list_bill_series(conn, household_id=household_id)
    by_id = {s.id: s for s in series}
    rows = []
    for o in households.list_bill_occurrences(conn, household_id=household_id, end_exclusive=cycle.horizon_end):
        payer = None
        if o.shared_expense_id is not None:
            payer = households.get_expense(conn, expense_id=o.shared_expense_id).payer_user_id
        status = planning.occurrence_status(
            planning.Occurrence(o.id, o.series_id, o.name, o.category_id, o.scheduled_date, o.due_date, o.amount_cents,
                                o.skipped, o.shared_expense_id, o.version),
            today=cycle.today, next_allowance=cycle.next_allowance)
        rows.append(HouseholdBillRow(o.id, o.series_id, o.name, o.category_id, o.scheduled_date, o.due_date,
                                     o.amount_cents, o.skipped, o.shared_expense_id, o.version, status,
                                     households.share_of(by_id[o.series_id], o, actor.user_id),
                                     actor.user_id in by_id[o.series_id].weights, payer))
    return HouseholdBillsView(series, rows)


def _participant_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int) -> households.HouseholdOccurrence:
    occurrence = households.get_bill_occurrence(conn, occurrence_id=occurrence_id)
    require_member(conn, actor.user_id, occurrence.household_id)
    series = households.get_bill_series(conn, series_id=occurrence.series_id)
    if actor.user_id not in series.weights:
        raise PermissionDeniedError("Only the people who share this bill can change or pay it.")
    return occurrence


def get_household_occurrence(conn: sqlite3.Connection, actor: Actor,
                             occurrence_id: int) -> households.HouseholdOccurrence:
    occurrence = households.get_bill_occurrence(conn, occurrence_id=occurrence_id)
    require_viewer(conn, actor.user_id, occurrence.household_id)
    return occurrence


def household_bill_problems(conn: sqlite3.Connection, actor: Actor, household_id: int, data: HouseholdBillInput,
                            clock: Clock) -> dict[str, str]:
    return households.bill_problems(conn, household_id=household_id, name=data.name, amount_cents=data.amount_cents,
                                    category_id=data.category_id, rule=data.rule, split_method=data.split_method,
                                    entries=data.entries, category_ids=_category_ids(conn), today=clock.today())


def add_household_bill(conn: sqlite3.Connection, actor: Actor, household_id: int, data: HouseholdBillInput,
                       clock: Clock) -> households.HouseholdBillSeries:
    with transaction(conn):
        require_owner(conn, actor.user_id, household_id)
        series = households.create_bill_series(
            conn, household_id=household_id, name=data.name, amount_cents=data.amount_cents,
            category_id=data.category_id, rule=data.rule, split_method=data.split_method, entries=data.entries,
            category_ids=_category_ids(conn), today=clock.today(), now=clock.now_utc())
        horizon = _viewer_cycle(conn, actor.user_id, clock).horizon_end
        households.ensure_materialized(conn, household_id=household_id, horizon_end=horizon)
        _audit(conn, actor, household_id, "household_bill", series.id, "create", clock,
               after={**asdict(series), "rule": asdict(series.rule)})
    return series


def end_household_bill(conn: sqlite3.Connection, actor: Actor, series_id: int, version: int, clock: Clock) -> None:
    with transaction(conn):
        series = households.get_bill_series(conn, series_id=series_id)
        require_owner(conn, actor.user_id, series.household_id)
        households.end_bill_series(conn, series_id=series_id, version=version, today=clock.today(),
                                   now=clock.now_utc())
        _audit(conn, actor, series.household_id, "household_bill", series_id, "end", clock)


def edit_household_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int,
                              amount_cents: int, due_date: date, clock: Clock) -> None:
    with transaction(conn):
        before = _participant_occurrence(conn, actor, occurrence_id)
        after = households.edit_bill_occurrence(conn, occurrence_id=occurrence_id, version=version,
                                                amount_cents=amount_cents, due_date=due_date)
        _audit(conn, actor, before.household_id, "household_bill_occurrence", occurrence_id, "update", clock,
               asdict(before), asdict(after))


def skip_household_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int,
                              clock: Clock, *, skipped: bool) -> None:
    with transaction(conn):
        before = _participant_occurrence(conn, actor, occurrence_id)
        households.set_bill_skipped(conn, occurrence_id=occurrence_id, version=version, skipped=skipped,
                                    now=clock.now_utc())
        _audit(conn, actor, before.household_id, "household_bill_occurrence", occurrence_id,
               "skip" if skipped else "unskip", clock)


def pay_household_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int,
                             paid_on: date, clock: Clock) -> households.SharedExpense:
    """FR-26: one shared expense split by the template, the payer's ledger expense, and the link, together."""
    with transaction(conn):
        occurrence = _participant_occurrence(conn, actor, occurrence_id)
        draft = households.payment_draft(conn, occurrence_id=occurrence_id, version=version, paid_on=paid_on)
        errors = expense_problems(conn, actor, occurrence.household_id, draft, clock)
        if errors:
            raise ValidationError({"paid_on" if field == "spent_on" else field: message
                                   for field, message in errors.items()})
        transaction_id = ledger.create_linked(
            conn, user_id=actor.user_id, kind="expense", origin="shared", amount_cents=draft.amount_cents,
            occurred_on=paid_on, category_id=draft.category_id, income_source=None, note=draft.description,
            today=clock.today(), now=clock.now_utc())
        expense = households.create_expense(conn, household_id=occurrence.household_id, payer_id=actor.user_id,
                                            draft=draft, category_ids=_category_ids(conn),
                                            payer_transaction_id=transaction_id, now=clock.now_utc())
        households.link_bill_payment(conn, occurrence_id=occurrence_id, version=version, expense_id=expense.id)
        _audit(conn, actor, occurrence.household_id, "household_bill_occurrence", occurrence_id, "pay", clock,
               before=asdict(occurrence), after=asdict(expense))
    return expense


def undo_household_payment(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int,
                           clock: Clock) -> None:
    """Only the payer, from the current version: link, shared expense, and ledger expense go together."""
    with transaction(conn):
        occurrence = households.get_bill_occurrence(conn, occurrence_id=occurrence_id)
        require_member(conn, actor.user_id, occurrence.household_id)
        if occurrence.shared_expense_id is None:
            raise ConflictError("This bill is not paid.")
        expense = households.get_expense(conn, expense_id=occurrence.shared_expense_id)
        if expense.payer_user_id != actor.user_id:
            raise PermissionDeniedError("Only the person who paid this bill can undo the payment.")
        households.unlink_bill_payment(conn, occurrence_id=occurrence_id, version=version)
        households.delete_expense(conn, expense_id=expense.id, user_id=actor.user_id, version=expense.version)
        ledger.delete_linked(conn, user_id=actor.user_id, transaction_id=expense.payer_transaction_id,
                             origin="shared")
        _audit(conn, actor, occurrence.household_id, "household_bill_occurrence", occurrence_id, "undo_payment",
               clock, before=asdict(expense))


def household_bill_series(conn: sqlite3.Connection, actor: Actor, series_id: int) -> households.HouseholdBillSeries:
    series = households.get_bill_series(conn, series_id=series_id)
    require_viewer(conn, actor.user_id, series.household_id)
    return series
