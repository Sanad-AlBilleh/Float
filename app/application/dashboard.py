"""The dashboard's numbers. Day 1: recorded balance, the cycle, and the allowance reminder (FR-27, FR-28)."""

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.application.setup import current_settings
from app.ledger import api as ledger
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
    ledger_settings, planning_settings = current_settings(conn, user_id)
    cycle = cycle_for(today, planning_settings.allowance_day)
    recorded = ledger.has_allowance_income(conn, user_id=user_id, start=cycle.start, end_inclusive=today)
    first_cycle_start = cycle_for(ledger_settings.tracking_start, planning_settings.allowance_day).start
    balance = ledger.get_balance(conn, user_id=user_id, as_of=today)
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
    )
