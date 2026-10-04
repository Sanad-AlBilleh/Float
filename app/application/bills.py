"""Bill workflows: each opens one transaction, crosses Planning and the Ledger through their APIs, and audits
itself (FR-09–13, FR-33, SRS §6.3)."""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date

from app.application import audit
from app.application.context import Actor
from app.application.setup import current_settings
from app.db.unit_of_work import transaction
from app.ledger import api as ledger
from app.planning import api as planning
from app.shared.clock import Clock
from app.shared.dates import Cycle, cycle_for
from app.shared.errors import ValidationError
from app.shared.recurrence import Rule


@dataclass(frozen=True)
class SeriesInput:
    name: str
    amount_cents: int
    category_id: int
    rule: Rule


@dataclass(frozen=True)
class BillRow:
    id: int
    series_id: int
    name: str
    category_id: int
    scheduled_date: date
    due_date: date
    amount_cents: int
    skipped: bool
    paid_transaction_id: int | None
    version: int
    status: str


@dataclass(frozen=True)
class BillsView:
    cycle: Cycle
    tracking_start: date
    occurrences: tuple[BillRow, ...]  # from tracking start to the end of the horizon, by due date
    series: tuple[planning.BillSeries, ...]
    reserved_cents: int  # what safe-to-spend sets aside for personal bills this cycle

    def in_range(self, start: date | None, end_exclusive: date | None) -> list[BillRow]:
        return [o for o in self.occurrences
                if (start is None or o.due_date >= start) and (end_exclusive is None or o.due_date < end_exclusive)]


def _context(conn: sqlite3.Connection, actor: Actor, clock: Clock) -> tuple[date, Cycle]:
    ledger_settings, planning_settings = current_settings(conn, actor.user_id)
    return ledger_settings.tracking_start, cycle_for(clock.today(), planning_settings.allowance_day)


def _category_ids(conn: sqlite3.Connection, user_id: int) -> set[int]:
    return {category.id for category in ledger.list_categories(conn, user_id)}


def materialize(conn: sqlite3.Connection, actor: Actor, clock: Clock) -> Cycle:
    """Idempotent bookkeeping before any read that depends on bills (FR-10); allowed on GET."""
    with transaction(conn):
        _, cycle = _context(conn, actor, clock)
        planning.ensure_materialized(conn, user_id=actor.user_id, horizon_end=cycle.horizon_end)
    return cycle


def overview(conn: sqlite3.Connection, actor: Actor, clock: Clock) -> BillsView:
    cycle = materialize(conn, actor, clock)
    tracking_start, _ = _context(conn, actor, clock)
    rows = planning.list_occurrences(conn, user_id=actor.user_id, start=tracking_start,
                                     end_exclusive=cycle.horizon_end)
    occurrences = tuple(
        BillRow(**asdict(o), status=planning.occurrence_status(o, today=cycle.today,
                                                                next_allowance=cycle.next_allowance))
        for o in rows
    )
    reserved = planning.get_obligations(conn, user_id=actor.user_id, cycle=cycle).personal_bills_cents
    return BillsView(cycle, tracking_start, occurrences, tuple(planning.list_series(conn, user_id=actor.user_id)),
                     reserved)


def series_problems(conn: sqlite3.Connection, actor: Actor, *, name: str, amount_cents: int,
                    category_id: int | None, anchor: date) -> dict[str, str]:
    tracking_start = ledger.get_settings(conn, actor.user_id).tracking_start
    return planning.series_problems(name=name, amount_cents=amount_cents, category_id=category_id, anchor=anchor,
                                    tracking_start=tracking_start, category_ids=_category_ids(conn, actor.user_id))


def _series_record(series: planning.BillSeries) -> dict:
    return {**asdict(series), "rule": asdict(series.rule)}


def add_series(conn: sqlite3.Connection, actor: Actor, data: SeriesInput, clock: Clock) -> planning.BillSeries:
    with transaction(conn):
        tracking_start, cycle = _context(conn, actor, clock)
        created = planning.create_series(
            conn, user_id=actor.user_id, name=data.name, amount_cents=data.amount_cents,
            category_id=data.category_id, rule=data.rule, tracking_start=tracking_start,
            category_ids=_category_ids(conn, actor.user_id), now=clock.now_utc(),
        )
        planning.ensure_materialized(conn, user_id=actor.user_id, horizon_end=cycle.horizon_end)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="bill_series", entity_id=created.id,
                     action="create", now=clock.now_utc(), after=_series_record(created),
                     request_id=actor.request_id)
    return created


def get_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int) -> planning.Occurrence:
    return planning.get_occurrence(conn, user_id=actor.user_id, occurrence_id=occurrence_id)


def get_series(conn: sqlite3.Connection, actor: Actor, series_id: int) -> planning.BillSeries:
    return planning.get_series(conn, user_id=actor.user_id, series_id=series_id)


def pay_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int, paid_on: date,
                   clock: Clock) -> int:
    """Create exactly one ``bill`` expense and link it, in one transaction (FR-12). Returns its ID."""
    with transaction(conn):
        occurrence = planning.check_payable(conn, user_id=actor.user_id, occurrence_id=occurrence_id,
                                            version=version)
        try:
            transaction_id = ledger.create_linked(
                conn, user_id=actor.user_id, kind="expense", origin="bill", amount_cents=occurrence.amount_cents,
                occurred_on=paid_on, category_id=occurrence.category_id, income_source=None, note=occurrence.name,
                today=clock.today(), now=clock.now_utc(),
            )
        except ValidationError as error:
            raise ValidationError({"paid_on" if field == "occurred_on" else field: message
                                   for field, message in error.errors.items()}) from None
        paid = planning.link_payment(conn, user_id=actor.user_id, occurrence_id=occurrence_id, version=version,
                                     transaction_id=transaction_id)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="bill_occurrence", entity_id=occurrence_id,
                     action="pay", now=clock.now_utc(), before=asdict(occurrence), after=asdict(paid),
                     request_id=actor.request_id)
    return transaction_id


def undo_payment(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int, clock: Clock) -> None:
    """Clear the link, then delete the expense it pointed to, atomically (FR-12)."""
    with transaction(conn):
        before = planning.get_occurrence(conn, user_id=actor.user_id, occurrence_id=occurrence_id)
        transaction_id = planning.unlink_payment(conn, user_id=actor.user_id, occurrence_id=occurrence_id,
                                                 version=version)
        ledger.delete_linked(conn, user_id=actor.user_id, transaction_id=transaction_id, origin="bill")
        after = planning.get_occurrence(conn, user_id=actor.user_id, occurrence_id=occurrence_id)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="bill_occurrence", entity_id=occurrence_id,
                     action="undo_payment", now=clock.now_utc(), before=asdict(before), after=asdict(after),
                     request_id=actor.request_id)


def _skip(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int, clock: Clock,
          skipped: bool) -> None:
    with transaction(conn):
        before = planning.get_occurrence(conn, user_id=actor.user_id, occurrence_id=occurrence_id)
        after = planning.set_skipped(conn, user_id=actor.user_id, occurrence_id=occurrence_id, version=version,
                                     skipped=skipped, now=clock.now_utc())
        audit.record(conn, actor_user_id=actor.user_id, entity_type="bill_occurrence", entity_id=occurrence_id,
                     action="skip" if skipped else "unskip", now=clock.now_utc(), before=asdict(before),
                     after=asdict(after), request_id=actor.request_id)


def skip_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int, clock: Clock) -> None:
    _skip(conn, actor, occurrence_id, version, clock, True)


def unskip_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int,
                      clock: Clock) -> None:
    _skip(conn, actor, occurrence_id, version, clock, False)


def edit_occurrence(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int, amount_cents: int,
                    due_date: date, clock: Clock) -> None:
    with transaction(conn):
        tracking_start, _ = _context(conn, actor, clock)
        before = planning.get_occurrence(conn, user_id=actor.user_id, occurrence_id=occurrence_id)
        after = planning.edit_occurrence(conn, user_id=actor.user_id, occurrence_id=occurrence_id, version=version,
                                         amount_cents=amount_cents, due_date=due_date, tracking_start=tracking_start)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="bill_occurrence", entity_id=occurrence_id,
                     action="update", now=clock.now_utc(), before=asdict(before), after=asdict(after),
                     request_id=actor.request_id)


def end_series(conn: sqlite3.Connection, actor: Actor, series_id: int, version: int, clock: Clock) -> None:
    with transaction(conn):
        before = planning.get_series(conn, user_id=actor.user_id, series_id=series_id)
        after = planning.end_series(conn, user_id=actor.user_id, series_id=series_id, version=version,
                                    today=clock.today(), now=clock.now_utc())
        audit.record(conn, actor_user_id=actor.user_id, entity_type="bill_series", entity_id=series_id,
                     action="end", now=clock.now_utc(), before=_series_record(before), after=_series_record(after),
                     request_id=actor.request_id)


def split_series(conn: sqlite3.Connection, actor: Actor, occurrence_id: int, version: int, data: SeriesInput,
                 clock: Clock) -> planning.BillSeries:
    """*This and future* (FR-13, SRS §4.2): all five steps and their audit events in one transaction."""
    with transaction(conn):
        tracking_start, cycle = _context(conn, actor, clock)
        occurrence = planning.get_occurrence(conn, user_id=actor.user_id, occurrence_id=occurrence_id)
        before = planning.get_series(conn, user_id=actor.user_id, series_id=occurrence.series_id)
        result = planning.split_series(
            conn, user_id=actor.user_id, occurrence_id=occurrence_id, version=version, name=data.name,
            amount_cents=data.amount_cents, category_id=data.category_id, rule=data.rule,
            tracking_start=tracking_start, category_ids=_category_ids(conn, actor.user_id), horizon_end=cycle.horizon_end,
            now=clock.now_utc(),
        )
        old = planning.get_series(conn, user_id=actor.user_id, series_id=before.id)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="bill_series", entity_id=before.id,
                     action="split" if result.id != before.id else "update", now=clock.now_utc(),
                     before=_series_record(before), after=_series_record(old), request_id=actor.request_id)
        if result.id != before.id:
            audit.record(conn, actor_user_id=actor.user_id, entity_type="bill_series", entity_id=result.id,
                         action="create", now=clock.now_utc(), after=_series_record(result),
                         request_id=actor.request_id)
    return result
