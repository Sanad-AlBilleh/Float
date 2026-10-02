"""The dashboard's numbers: recorded balance, the cycle, the allowance reminder, and safe-to-spend with every
term of SRS §4.5 (FR-27–29)."""

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.application.setup import current_settings
from app.db.unit_of_work import transaction
from app.insights import api as insights
from app.ledger import api as ledger
from app.planning import api as planning
from app.shared.clock import Clock
from app.shared.dates import Cycle, cycle_for


@dataclass(frozen=True)
class DashboardView:
    recorded_balance_cents: int
    planned_allowance_cents: int
    cycle: Cycle
    tracking_start: date
    allowance_reminder: bool
    below_zero: bool  # FR-06: an expense may push cash below zero; it is accepted and shown with a warning
    safe: insights.SafeToSpend
    reserved_bills: tuple[planning.Occurrence, ...] = ()


def needs_allowance_reminder(*, cycle: Cycle, first_cycle_start: date, counted_at_setup: bool,
                             allowance_recorded: bool) -> bool:
    """FR-28: remind until this cycle's allowance is recorded.

    The one exception is the cycle in which tracking began, when setup recorded that its allowance is
    already in the opening balance; recording it again would count it twice.
    """
    if allowance_recorded:
        return False
    return not (counted_at_setup and cycle.start == first_cycle_start)


def dashboard(conn: sqlite3.Connection, user_id: int, clock: Clock) -> DashboardView:
    today = clock.today()
    with transaction(conn):  # materializing bills is idempotent bookkeeping, allowed on GET (FR-10)
        ledger_settings, planning_settings = current_settings(conn, user_id)
        cycle = cycle_for(today, planning_settings.allowance_day)
        planning.ensure_materialized(conn, user_id=user_id, horizon_end=cycle.horizon_end)
    recorded = ledger.has_allowance_income(conn, user_id=user_id, start=cycle.start, end_inclusive=today)
    first_cycle_start = cycle_for(ledger_settings.tracking_start, planning_settings.allowance_day).start
    balance = ledger.get_balance(conn, user_id=user_id, as_of=today)
    obligations = planning.get_obligations(conn, user_id=user_id, cycle=cycle)
    inputs = insights.SafeToSpendInputs(
        recorded_balance_cents=balance,
        personal_bills_cents=obligations.personal_bills_cents,
        protected_savings_cents=obligations.protected_savings_cents,
        goal_plan_reserve_cents=obligations.goal_plan_reserve_cents,
    )  # household terms stay zero until households exist
    return DashboardView(
        recorded_balance_cents=balance,
        planned_allowance_cents=planning_settings.planned_allowance_cents,
        cycle=cycle,
        tracking_start=ledger_settings.tracking_start,
        allowance_reminder=needs_allowance_reminder(
            cycle=cycle,
            first_cycle_start=first_cycle_start,
            counted_at_setup=planning_settings.opening_includes_allowance,
            allowance_recorded=recorded,
        ),
        below_zero=balance < 0,
        safe=insights.compute(inputs, cycle),
        reserved_bills=obligations.occurrences,
    )
