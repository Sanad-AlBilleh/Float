"""Household bills: shared recurring series with a split template, and each member's position (FR-25–26, §4.5).

A household bill is paid by turning its occurrence into an ordinary shared expense, so balances,
settlements, and consumption need no special cases. The application layer creates that expense and
the payer's ledger row, then links the occurrence, in one transaction.
"""

import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.households import repository
from app.households.expenses import ExpenseDraft
from app.households.rules import TEMPLATE_METHODS, SplitEntry, allocate
from app.households.service import active_member_ids, balances, require_open
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.shared.money import MAX_CENTS
from app.shared.recurrence import Rule, expand

SQLITE_MAX_ID = 2**63 - 1
BILL_NAME_LIMIT = 100
STALE_MESSAGE = "This bill changed since you opened it. Reload the page and try again."
PAID_MESSAGE = "This bill is paid. Undo the payment first."


@dataclass(frozen=True)
class HouseholdBillSeries:
    id: int
    household_id: int
    name: str
    amount_cents: int
    category_id: int
    rule: Rule
    split_method: str
    weights: dict[int, int]  # participant → weight (1 for equal, basis points, or shares)
    materialized_through: date | None
    ended: bool
    version: int

    def entries(self) -> tuple[SplitEntry, ...]:
        return tuple(SplitEntry(user, None if self.split_method == "equal" else weight)
                     for user, weight in self.weights.items())


@dataclass(frozen=True)
class HouseholdOccurrence:
    id: int
    series_id: int
    household_id: int
    name: str
    category_id: int
    scheduled_date: date
    due_date: date
    amount_cents: int
    skipped: bool
    shared_expense_id: int | None  # set when paid: the payment is an ordinary shared expense
    version: int


@dataclass(frozen=True)
class HouseholdPosition:
    """One user's household terms for safe-to-spend and the forecast (SRS §4.5, §4.7)."""

    bill_shares_cents: int  # their share of open household bills due before ``window_end``
    payables_cents: int  # Σ max(0, −net) over their active households
    receivables_cents: int  # Σ max(0, net): owed to them, never counted as spendable
    commitments: tuple[tuple[date, int], ...]  # (due date, their share) of open bills before ``horizon_end``


def _series(conn: sqlite3.Connection, row: sqlite3.Row) -> HouseholdBillSeries:
    rule = Rule(row["freq"], row["interval"], date.fromisoformat(row["anchor_date"]),
                until=None if row["until_date"] is None else date.fromisoformat(row["until_date"]),
                count=row["max_count"])
    through = row["materialized_through"]
    return HouseholdBillSeries(row["id"], row["household_id"], row["name"], row["amount_cents"], row["category_id"],
                               rule, row["split_method"], repository.participants(conn, row["id"]),
                               None if through is None else date.fromisoformat(through), row["ended_at"] is not None,
                               row["version"])


def _occurrence(row: sqlite3.Row) -> HouseholdOccurrence:
    return HouseholdOccurrence(row["id"], row["series_id"], row["household_id"], row["name"], row["category_id"],
                               date.fromisoformat(row["scheduled_date"]), date.fromisoformat(row["due_date"]),
                               row["amount_cents"], row["skipped_at"] is not None, row["shared_expense_id"],
                               row["version"])


def get_bill_series(conn: sqlite3.Connection, *, series_id: int) -> HouseholdBillSeries:
    row = repository.get_bill_series(conn, series_id) if 1 <= series_id <= SQLITE_MAX_ID else None
    if row is None:
        raise NotFoundError("No such bill.")
    return _series(conn, row)


def list_bill_series(conn: sqlite3.Connection, *, household_id: int) -> list[HouseholdBillSeries]:
    return [_series(conn, row) for row in repository.list_bill_series(conn, household_id=household_id,
                                                                       active_only=False)]


def bill_problems(conn: sqlite3.Connection, *, household_id: int, name: str, amount_cents: int,
                  category_id: int | None, rule: Rule, split_method: str, entries: tuple[SplitEntry, ...],
                  category_ids: Collection[int], today: date) -> dict[str, str]:
    """Every rule a new household bill breaks (FR-25), as field messages."""
    errors: dict[str, str] = {}
    if not 1 <= len(name) <= BILL_NAME_LIMIT:
        errors["name"] = f"Enter a name of 1 to {BILL_NAME_LIMIT} characters."
    if not 1 <= amount_cents <= MAX_CENTS:
        errors["amount"] = "Enter an amount between €0.01 and €1,000,000.00."
    if category_id not in category_ids:
        errors["category_id"] = "Choose a category."
    if rule.anchor < today:
        errors["anchor_date"] = ("Choose a first due date from today on. Record a cost that is already due as a "
                                 "shared expense instead.")
    if split_method not in TEMPLATE_METHODS:
        errors["split_method"] = "Choose equal, percentage, or shares. The amount may vary, so exact is not allowed."
    members = set(active_member_ids(conn, household_id=household_id))
    if not entries or any(entry.user_id not in members for entry in entries):
        errors["participants"] = "Choose participants from the household's current members."
    if not errors:
        try:
            allocate(amount_cents, split_method, entries)
        except ValidationError as error:
            errors.update(error.errors)
    return errors


def create_bill_series(conn: sqlite3.Connection, *, household_id: int, name: str, amount_cents: int,
                       category_id: int | None, rule: Rule, split_method: str, entries: tuple[SplitEntry, ...],
                       category_ids: Collection[int], today: date, now: datetime) -> HouseholdBillSeries:
    """FR-25: a template of equal, percentage, or shares (never exact), anchored today or later."""
    require_open(conn, household_id=household_id)
    errors = bill_problems(conn, household_id=household_id, name=name, amount_cents=amount_cents,
                           category_id=category_id, rule=rule, split_method=split_method, entries=entries,
                           category_ids=category_ids, today=today)
    if errors:
        raise ValidationError(errors)
    series_id = repository.insert_bill_series(
        conn, household_id=household_id, name=name, amount_cents=amount_cents, category_id=category_id,
        freq=rule.freq, interval=rule.interval, anchor=rule.anchor, until=rule.until, count=rule.count,
        split_method=split_method, now=now)
    repository.insert_participants(conn, series_id=series_id,
                                   weights={e.user_id: 1 if e.value is None else e.value for e in entries})
    return get_bill_series(conn, series_id=series_id)


def ensure_materialized(conn: sqlite3.Connection, *, household_id: int, horizon_end: date) -> int:
    """Generate every active series' occurrences before ``horizon_end``, idempotently (FR-10, FR-25)."""
    inserted = 0
    for row in repository.list_bill_series(conn, household_id=household_id, active_only=True):
        series = _series(conn, row)
        start = series.materialized_through + timedelta(days=1) if series.materialized_through else series.rule.anchor
        if start >= horizon_end:
            continue
        for day in expand(series.rule, start, horizon_end):
            inserted += repository.insert_bill_occurrence_if_absent(conn, series_id=series.id, scheduled_date=day,
                                                                    amount_cents=series.amount_cents)
        repository.advance_bill_watermark(conn, series_id=series.id, through=horizon_end - timedelta(days=1))
    return inserted


def get_bill_occurrence(conn: sqlite3.Connection, *, occurrence_id: int) -> HouseholdOccurrence:
    row = repository.get_bill_occurrence(conn, occurrence_id) if 1 <= occurrence_id <= SQLITE_MAX_ID else None
    if row is None:
        raise NotFoundError("No such bill.")
    return _occurrence(row)


def list_bill_occurrences(conn: sqlite3.Connection, *, household_id: int,
                          end_exclusive: date) -> list[HouseholdOccurrence]:
    return [_occurrence(row) for row in repository.list_bill_occurrences(conn, household_id=household_id,
                                                                         end_exclusive=end_exclusive)]


def share_of(series: HouseholdBillSeries, occurrence: HouseholdOccurrence, user_id: int) -> int:
    """``user_id``'s template share of the occurrence's current amount (0 if not a participant)."""
    if user_id not in series.weights:
        return 0
    return allocate(occurrence.amount_cents, series.split_method, series.entries())[user_id]


def _current(conn: sqlite3.Connection, occurrence_id: int, version: int) -> HouseholdOccurrence:
    occurrence = get_bill_occurrence(conn, occurrence_id=occurrence_id)
    require_open(conn, household_id=occurrence.household_id)
    if occurrence.version != version:
        raise ConflictError(STALE_MESSAGE)
    return occurrence


def edit_bill_occurrence(conn: sqlite3.Connection, *, occurrence_id: int, version: int, amount_cents: int,
                         due_date: date) -> HouseholdOccurrence:
    """Any participant may correct an unpaid occurrence, for example when the real invoice arrives (FR-25)."""
    if not 1 <= amount_cents <= MAX_CENTS:
        raise ValidationError.single("amount", "Enter an amount between €0.01 and €1,000,000.00.")
    occurrence = _current(conn, occurrence_id, version)
    if occurrence.shared_expense_id is not None:
        raise ConflictError(PAID_MESSAGE)
    if repository.update_bill_occurrence(conn, occurrence_id=occurrence_id, version=version,
                                         amount_cents=amount_cents, due_date=due_date) != 1:
        raise ConflictError(STALE_MESSAGE)
    return get_bill_occurrence(conn, occurrence_id=occurrence_id)


def set_bill_skipped(conn: sqlite3.Connection, *, occurrence_id: int, version: int, skipped: bool,
                     now: datetime) -> HouseholdOccurrence:
    occurrence = _current(conn, occurrence_id, version)
    if occurrence.shared_expense_id is not None:
        raise ConflictError(PAID_MESSAGE)
    if occurrence.skipped == skipped:
        raise ConflictError("This bill is already skipped." if skipped else "This bill is not skipped.")
    if repository.set_bill_skipped(conn, occurrence_id=occurrence_id, version=version,
                                   skipped_at=now if skipped else None) != 1:
        raise ConflictError(STALE_MESSAGE)
    return get_bill_occurrence(conn, occurrence_id=occurrence_id)


def payment_draft(conn: sqlite3.Connection, *, occurrence_id: int, version: int, paid_on: date) -> ExpenseDraft:
    """The shared expense a payment creates: the template's split of the current amount (FR-26)."""
    occurrence = _current(conn, occurrence_id, version)
    if occurrence.shared_expense_id is not None:
        raise ConflictError("This bill is already paid.")
    if occurrence.skipped:
        raise ConflictError("This bill is skipped. Unskip it before paying.")
    series = get_bill_series(conn, series_id=occurrence.series_id)
    return ExpenseDraft(occurrence.amount_cents, paid_on, occurrence.category_id, occurrence.name, False,
                        series.split_method, series.entries())


def link_bill_payment(conn: sqlite3.Connection, *, occurrence_id: int, version: int, expense_id: int) -> None:
    if repository.link_bill_payment(conn, occurrence_id=occurrence_id, version=version, expense_id=expense_id) != 1:
        raise ConflictError(STALE_MESSAGE)


def unlink_bill_payment(conn: sqlite3.Connection, *, occurrence_id: int, version: int) -> int:
    """Clear the link and return the shared expense it pointed to, for the caller to delete."""
    occurrence = _current(conn, occurrence_id, version)
    if occurrence.shared_expense_id is None:
        raise ConflictError("This bill is not paid.")
    if repository.unlink_bill_payment(conn, occurrence_id=occurrence_id, version=version) != 1:
        raise ConflictError(STALE_MESSAGE)
    return occurrence.shared_expense_id


def end_bill_series(conn: sqlite3.Connection, *, series_id: int, version: int, today: date,
                    now: datetime) -> HouseholdBillSeries:
    series = get_bill_series(conn, series_id=series_id)
    require_open(conn, household_id=series.household_id)
    if series.ended:
        raise ConflictError("This bill has already ended.")
    if repository.end_bill_series(conn, series_id=series_id, version=version, now=now) != 1:
        raise ConflictError(STALE_MESSAGE)
    repository.delete_open_bill_occurrences_from(conn, series_id=series_id, day=today)
    return get_bill_series(conn, series_id=series_id)


def materialize_for_user(conn: sqlite3.Connection, *, user_id: int, horizon_end: date) -> None:
    for household_id in repository.active_household_ids(conn, user_id=user_id):
        ensure_materialized(conn, household_id=household_id, horizon_end=horizon_end)


def get_position(conn: sqlite3.Connection, *, user_id: int, window_end: date, horizon_end: date) -> HouseholdPosition:
    """The user's household terms across their active households. Callers materialize first."""
    shares = payables = receivables = 0
    commitments: list[tuple[date, int]] = []
    for household_id in repository.active_household_ids(conn, user_id=user_id):
        net = balances(conn, household_id=household_id).get(user_id, 0)
        payables += max(0, -net)
        receivables += max(0, net)
        series_by_id = {s.id: s for s in list_bill_series(conn, household_id=household_id)}
        for occurrence in list_bill_occurrences(conn, household_id=household_id, end_exclusive=horizon_end):
            if occurrence.shared_expense_id is not None or occurrence.skipped:
                continue
            share = share_of(series_by_id[occurrence.series_id], occurrence, user_id)
            if share == 0:
                continue
            commitments.append((occurrence.due_date, share))
            if occurrence.due_date < window_end:
                shares += share
    return HouseholdPosition(shares, payables, receivables, tuple(commitments))
