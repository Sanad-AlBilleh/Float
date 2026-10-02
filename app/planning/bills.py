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
from app.shared.errors import NotFoundError, ValidationError
from app.shared.recurrence import Rule, expand

SQLITE_MAX_ID = 2**63 - 1


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
    reserved = tuple(open_occurrences_due_before(conn, user_id=user_id, before=cycle.next_allowance))
    return PlanningObligations(sum(o.amount_cents for o in reserved), 0, 0, reserved)
