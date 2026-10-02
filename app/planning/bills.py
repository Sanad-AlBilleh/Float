"""Recurring personal bills: series, materialized occurrences, and what they reserve (FR-09–13, SRS §4.2).

Every function runs on the caller's open connection, inside the caller's transaction.
"""

import sqlite3
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.planning import repository
from app.planning.rules import validate_anchor, validate_bill
from app.shared.dates import Cycle
from app.shared.errors import ConflictError, NotFoundError, ValidationError
from app.shared.money import MAX_CENTS
from app.shared.recurrence import Rule, expand, split_rule

SQLITE_MAX_ID = 2**63 - 1
PAID_MESSAGE = "This bill is paid. Undo the payment first."
STALE_MESSAGE = "This bill changed since you opened it. Reload the page and try again."


@dataclass(frozen=True)
class BillSeries:
    id: int
    user_id: int
    name: str
    amount_cents: int
    category_id: int
    rule: Rule
    materialized_through: date | None
    ended: bool
    version: int


@dataclass(frozen=True)
class Occurrence:
    id: int
    series_id: int
    name: str
    category_id: int
    scheduled_date: date  # immutable: the uniqueness key the rule generated
    due_date: date  # editable for this occurrence only
    amount_cents: int
    skipped: bool
    paid_transaction_id: int | None  # the payment link is the only record of paid status
    version: int


@dataclass(frozen=True)
class PlanningObligations:
    personal_bills_cents: int
    protected_savings_cents: int
    goal_plan_reserve_cents: int
    occurrences: tuple[Occurrence, ...]  # the reserved occurrences behind personal_bills_cents


def _date(text: str | None) -> date | None:
    return None if text is None else date.fromisoformat(text)


def _series(row: sqlite3.Row) -> BillSeries:
    rule = Rule(row["freq"], row["interval"], date.fromisoformat(row["anchor_date"]),
                until=_date(row["until_date"]), count=row["max_count"])
    return BillSeries(row["id"], row["user_id"], row["name"], row["amount_cents"], row["category_id"], rule,
                      _date(row["materialized_through"]), row["ended_at"] is not None, row["version"])


def _occurrence(row: sqlite3.Row) -> Occurrence:
    return Occurrence(
        id=row["id"], series_id=row["series_id"], name=row["name"], category_id=row["category_id"],
        scheduled_date=date.fromisoformat(row["scheduled_date"]), due_date=date.fromisoformat(row["due_date"]),
        amount_cents=row["amount_cents"], skipped=row["skipped_at"] is not None,
        paid_transaction_id=row["paid_transaction_id"], version=row["version"],
    )


def series_problems(*, name: str, amount_cents: int, category_id: int | None, anchor: date, tracking_start: date,
                    category_ids: Collection[int]) -> dict[str, str]:
    """Every rule a new series breaks, as field messages, so a form can show them all at once."""
    errors: dict[str, str] = {}
    for check in (
        lambda: validate_bill(name=name, amount_cents=amount_cents, category_id=category_id,
                              category_ids=category_ids),
        lambda: validate_anchor(anchor, tracking_start=tracking_start),
    ):
        try:
            check()
        except ValidationError as error:
            errors.update(error.errors)
    return errors


def create_series(conn: sqlite3.Connection, *, user_id: int, name: str, amount_cents: int, category_id: int,
                  rule: Rule, tracking_start: date, category_ids: Collection[int], now: datetime) -> BillSeries:
    errors = series_problems(name=name, amount_cents=amount_cents, category_id=category_id, anchor=rule.anchor,
                             tracking_start=tracking_start, category_ids=category_ids)
    if errors:
        raise ValidationError(errors)
    series_id = repository.insert_series(
        conn, user_id=user_id, name=name, amount_cents=amount_cents, category_id=category_id, freq=rule.freq,
        interval=rule.interval, anchor=rule.anchor, until=rule.until, count=rule.count, now=now,
    )
    return get_series(conn, user_id=user_id, series_id=series_id)


def get_series(conn: sqlite3.Connection, *, user_id: int, series_id: int) -> BillSeries:
    row = repository.get_series(conn, series_id) if 1 <= series_id <= SQLITE_MAX_ID else None
    if row is None or row["user_id"] != user_id:
        raise NotFoundError("No such bill.")
    return _series(row)


def list_series(conn: sqlite3.Connection, *, user_id: int) -> list[BillSeries]:
    return [_series(row) for row in repository.list_series(conn, user_id=user_id, active_only=False)]


def _materialize(conn: sqlite3.Connection, series: BillSeries, horizon_end: date) -> int:
    start = series.materialized_through + timedelta(days=1) if series.materialized_through else series.rule.anchor
    if start >= horizon_end:
        return 0
    inserted = 0
    for day in expand(series.rule, start, horizon_end):
        inserted += repository.insert_occurrence_if_absent(
            conn, series_id=series.id, user_id=series.user_id, scheduled_date=day, amount_cents=series.amount_cents,
        )
    repository.advance_watermark(conn, series_id=series.id, through=horizon_end - timedelta(days=1))
    return inserted


def ensure_materialized(conn: sqlite3.Connection, *, user_id: int, horizon_end: date) -> int:
    """Generate every active series' occurrences before ``horizon_end``; returns the rows inserted (FR-10).

    Idempotent: ``ON CONFLICT DO NOTHING`` on (series, scheduled date) means repeating it, concurrently
    or after a lost watermark, never duplicates an occurrence.
    """
    return sum(
        _materialize(conn, _series(row), horizon_end)
        for row in repository.list_series(conn, user_id=user_id, active_only=True)
    )


def get_occurrence(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int) -> Occurrence:
    row = repository.get_occurrence(conn, occurrence_id) if 1 <= occurrence_id <= SQLITE_MAX_ID else None
    if row is None or row["user_id"] != user_id:
        raise NotFoundError("No such bill.")
    return _occurrence(row)


def list_occurrences(conn: sqlite3.Connection, *, user_id: int, start: date, end_exclusive: date) -> list[Occurrence]:
    return [_occurrence(row) for row in repository.list_occurrences(conn, user_id=user_id, start=start,
                                                                    end_exclusive=end_exclusive)]


def open_occurrences_due_before(conn: sqlite3.Connection, *, user_id: int, before: date) -> list[Occurrence]:
    return [_occurrence(row) for row in repository.open_occurrences_due_before(conn, user_id=user_id, before=before)]


def get_obligations(conn: sqlite3.Connection, *, user_id: int, cycle: Cycle) -> PlanningObligations:
    """What Planning reserves this cycle (SRS §4.5). Callers materialize first."""
    from app.planning.goals import goal_plan_reserve  # goals never import bills, so this cannot cycle

    reserved = tuple(open_occurrences_due_before(conn, user_id=user_id, before=cycle.next_allowance))
    return PlanningObligations(sum(o.amount_cents for o in reserved), repository.protected_total(conn, user_id=user_id),
                               goal_plan_reserve(conn, user_id=user_id, cycle=cycle), reserved)


def _current(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int, version: int) -> Occurrence:
    """The occurrence, if it is still the version the caller saw; otherwise a conflict (SRS §6.4)."""
    occurrence = get_occurrence(conn, user_id=user_id, occurrence_id=occurrence_id)
    if occurrence.version != version:
        raise ConflictError(STALE_MESSAGE)
    return occurrence


def check_payable(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int, version: int) -> Occurrence:
    occurrence = _current(conn, user_id=user_id, occurrence_id=occurrence_id, version=version)
    if occurrence.paid_transaction_id is not None:
        raise ConflictError("This bill is already paid.")
    if occurrence.skipped:
        raise ConflictError("This bill is skipped. Unskip it before paying.")
    return occurrence


def link_payment(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int, version: int,
                 transaction_id: int) -> Occurrence:
    check_payable(conn, user_id=user_id, occurrence_id=occurrence_id, version=version)
    if repository.link_payment(conn, occurrence_id=occurrence_id, version=version, transaction_id=transaction_id) != 1:
        raise ConflictError(STALE_MESSAGE)
    return get_occurrence(conn, user_id=user_id, occurrence_id=occurrence_id)


def unlink_payment(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int, version: int) -> int:
    """Clear the payment link and return the transaction it pointed to, for the caller to delete."""
    occurrence = _current(conn, user_id=user_id, occurrence_id=occurrence_id, version=version)
    if occurrence.paid_transaction_id is None:
        raise ConflictError("This bill is not paid.")
    if repository.unlink_payment(conn, occurrence_id=occurrence_id, version=version) != 1:
        raise ConflictError(STALE_MESSAGE)
    return occurrence.paid_transaction_id


def _unpaid(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int, version: int) -> Occurrence:
    occurrence = _current(conn, user_id=user_id, occurrence_id=occurrence_id, version=version)
    if occurrence.paid_transaction_id is not None:
        raise ConflictError(PAID_MESSAGE)
    return occurrence


def set_skipped(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int, version: int,
                skipped: bool, now: datetime) -> Occurrence:
    occurrence = _unpaid(conn, user_id=user_id, occurrence_id=occurrence_id, version=version)
    if occurrence.skipped == skipped:
        raise ConflictError("This bill is already skipped." if skipped else "This bill is not skipped.")
    if repository.set_skipped(conn, occurrence_id=occurrence_id, version=version,
                              skipped_at=now if skipped else None) != 1:
        raise ConflictError(STALE_MESSAGE)
    return get_occurrence(conn, user_id=user_id, occurrence_id=occurrence_id)


def edit_occurrence(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int, version: int, amount_cents: int,
                    due_date: date, tracking_start: date) -> Occurrence:
    """*This occurrence only*: change an unpaid occurrence's amount or due date (FR-13)."""
    errors: dict[str, str] = {}
    if not 1 <= amount_cents <= MAX_CENTS:
        errors["amount"] = "Enter an amount between €0.01 and €1,000,000.00."
    if due_date < tracking_start:
        errors["due_date"] = f"Choose a date on or after {tracking_start.isoformat()}, when tracking started."
    if errors:
        raise ValidationError(errors)
    _unpaid(conn, user_id=user_id, occurrence_id=occurrence_id, version=version)
    if repository.update_occurrence(conn, occurrence_id=occurrence_id, version=version, amount_cents=amount_cents,
                                    due_date=due_date) != 1:
        raise ConflictError(STALE_MESSAGE)
    return get_occurrence(conn, user_id=user_id, occurrence_id=occurrence_id)


def end_series(conn: sqlite3.Connection, *, user_id: int, series_id: int, version: int, today: date,
               now: datetime) -> BillSeries:
    """Stop generating and delete open occurrences due today or later; overdue ones stay (FR-13)."""
    series = get_series(conn, user_id=user_id, series_id=series_id)
    if series.ended:
        raise ConflictError("This bill has already ended.")
    if repository.end_series(conn, series_id=series_id, version=version, now=now) != 1:
        raise ConflictError(STALE_MESSAGE)
    repository.delete_open_occurrences_due_from(conn, series_id=series_id, day=today)
    return get_series(conn, user_id=user_id, series_id=series_id)


def split_series(conn: sqlite3.Connection, *, user_id: int, occurrence_id: int, version: int, name: str,
                 amount_cents: int, category_id: int, rule: Rule, tracking_start: date,
                 category_ids: Collection[int], horizon_end: date, now: datetime) -> BillSeries:
    """*This and future* at an occurrence, following SRS §4.2 steps 1–5 in the caller's transaction."""
    occurrence = _current(conn, user_id=user_id, occurrence_id=occurrence_id, version=version)
    series = get_series(conn, user_id=user_id, series_id=occurrence.series_id)
    if series.ended:
        raise ConflictError("This bill has ended.")
    split_on = occurrence.scheduled_date
    errors = series_problems(name=name, amount_cents=amount_cents, category_id=category_id, anchor=rule.anchor,
                             tracking_start=tracking_start, category_ids=category_ids)
    if rule.anchor < split_on:
        errors["anchor_date"] = f"Choose a first date on or after {split_on.isoformat()}, the bill you are changing."
    if errors:
        raise ValidationError(errors)
    if repository.has_paid_from(conn, series_id=series.id, scheduled_date=split_on):  # step 1
        raise ConflictError("A bill on or after this date is paid. Undo that payment first.")
    if split_on == series.rule.anchor:  # nothing before the split point: change the series in place
        repository.delete_unpaid_from(conn, series_id=series.id, scheduled_date=split_on)
        repository.rewrite_series(conn, series_id=series.id, name=name, amount_cents=amount_cents,
                                  category_id=category_id, freq=rule.freq, interval=rule.interval,
                                  anchor=rule.anchor, until=rule.until, count=rule.count)
        target = get_series(conn, user_id=user_id, series_id=series.id)
    else:
        shortened, remaining = split_rule(series.rule, split_on)  # step 2
        repository.rewrite_series(conn, series_id=series.id, name=series.name, amount_cents=series.amount_cents,
                                  category_id=series.category_id, freq=shortened.freq, interval=shortened.interval,
                                  anchor=shortened.anchor, until=shortened.until, count=None)
        repository.delete_unpaid_from(conn, series_id=series.id, scheduled_date=split_on)  # step 3
        if remaining is not None and rule.until is None and rule.count is None:
            rule = Rule(rule.freq, rule.interval, rule.anchor, count=max(1, remaining))
        target = create_series(conn, user_id=user_id, name=name, amount_cents=amount_cents,  # step 4
                               category_id=category_id, rule=rule, tracking_start=tracking_start,
                               category_ids=category_ids, now=now)
        _materialize(conn, get_series(conn, user_id=user_id, series_id=series.id), horizon_end)
    _materialize(conn, target, horizon_end)  # step 5
    return get_series(conn, user_id=user_id, series_id=target.id)
