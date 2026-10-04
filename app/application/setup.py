"""Setup: Ledger and Planning settings written together, once (FR-05)."""

import sqlite3
from dataclasses import asdict, dataclass
from datetime import date

from app.application import audit
from app.application.context import Actor
from app.db.unit_of_work import transaction
from app.ledger import api as ledger
from app.planning import api as planning
from app.shared.clock import Clock
from app.shared.dates import add_months, cycle_for, scheduled_date
from app.shared.errors import ConflictError, ValidationError
from app.shared.money import MAX_CENTS


@dataclass(frozen=True)
class SetupInput:
    tracking_start: date
    opening_balance_cents: int
    allowance_day: int
    planned_allowance_cents: int = 75000
    allowance_included: bool = False  # the opening balance already holds the current cycle's allowance
    monthly_savings_cents: int = 0  # optional: reserved every cycle through an automatic goal


def is_setup_complete(conn: sqlite3.Connection, user_id: int) -> bool:
    return ledger.get_settings(conn, user_id) is not None and planning.get_settings(conn, user_id) is not None


def current_settings(conn: sqlite3.Connection, user_id: int) -> tuple[ledger.LedgerSettings, planning.PlanningSettings]:
    ledger_settings, planning_settings = ledger.get_settings(conn, user_id), planning.get_settings(conn, user_id)
    if ledger_settings is None or planning_settings is None:
        raise ConflictError("Complete setup first.")
    return ledger_settings, planning_settings


def setup_problems(*, tracking_start: date | None, opening_balance_cents: int | None, allowance_day: int | None,
                   planned_allowance_cents: int | None, today: date,
                   monthly_savings_cents: int | None = None) -> dict[str, str]:
    """Both domains' rules for whichever fields are present, so a form can show every problem at once.

    Missing fields get a harmless placeholder; their own parse errors are reported by the caller.
    """
    errors: dict[str, str] = {}
    checks = (
        lambda: ledger.validate_settings(
            tracking_start=today if tracking_start is None else tracking_start,
            opening_balance_cents=0 if opening_balance_cents is None else opening_balance_cents,
            today=today,
        ),
        lambda: planning.validate_settings(
            allowance_day=1 if allowance_day is None else allowance_day,
            planned_allowance_cents=1 if planned_allowance_cents is None else planned_allowance_cents,
        ),
    )
    for check in checks:
        try:
            check()
        except ValidationError as error:
            errors.update(error.errors)
    if monthly_savings_cents is not None and not 0 <= monthly_savings_cents <= MAX_CENTS:
        errors["monthly_savings"] = "Enter an amount between €0.00 and €1,000,000.00."  # the form's range
    return errors


def complete_setup(conn: sqlite3.Connection, actor: Actor, data: SetupInput, clock: Clock) -> None:
    """Validate both domains' fields together, then save both in one transaction."""
    today = clock.today()
    errors = setup_problems(tracking_start=data.tracking_start, opening_balance_cents=data.opening_balance_cents,
                            allowance_day=data.allowance_day, planned_allowance_cents=data.planned_allowance_cents,
                            today=today, monthly_savings_cents=data.monthly_savings_cents)
    if errors:
        raise ValidationError(errors)
    with transaction(conn):
        ledger.save_settings(
            conn,
            user_id=actor.user_id,
            tracking_start=data.tracking_start,
            opening_balance_cents=data.opening_balance_cents,
            today=today,
        )
        planning.save_settings(
            conn,
            user_id=actor.user_id,
            allowance_day=data.allowance_day,
            planned_allowance_cents=data.planned_allowance_cents,
            opening_includes_allowance=data.allowance_included,
        )
        audit.record(conn, actor_user_id=actor.user_id, entity_type="setup", entity_id=actor.user_id,
                     action="complete", now=clock.now_utc(), after=asdict(data), request_id=actor.request_id)
        if data.monthly_savings_cents > 0:
            _start_savings_plan(conn, actor, data, clock)


SAVINGS_CYCLES = 12


def _start_savings_plan(conn: sqlite3.Connection, actor: Actor, data: SetupInput, clock: Clock) -> None:
    """Monthly savings become an auto-reserve goal over the next 12 cycles, so the goal plan (SRS §4.6)
    reserves exactly that amount each cycle and safe-to-spend never counts it."""
    cycle = cycle_for(clock.today(), data.allowance_day)
    year, month = add_months(cycle.start.year, cycle.start.month, SAVINGS_CYCLES)
    goal = planning.create_goal(conn, user_id=actor.user_id, name="Monthly savings",
                                target_cents=data.monthly_savings_cents * SAVINGS_CYCLES,
                                target_date=scheduled_date(year, month, data.allowance_day), priority=1,
                                auto_reserve=True, now=clock.now_utc())
    audit.record(conn, actor_user_id=actor.user_id, entity_type="savings_goal", entity_id=goal.id, action="create",
                 now=clock.now_utc(), after=asdict(goal), request_id=actor.request_id)


def update_planned_allowance(conn: sqlite3.Connection, actor: Actor, cents: int, clock: Clock) -> None:
    with transaction(conn):
        before = planning.get_settings(conn, actor.user_id)
        after = planning.update_planned_allowance(conn, user_id=actor.user_id, planned_allowance_cents=cents)
        audit.record(conn, actor_user_id=actor.user_id, entity_type="planning_settings", entity_id=actor.user_id,
                     action="update", now=clock.now_utc(), before=asdict(before), after=asdict(after),
                     request_id=actor.request_id)
