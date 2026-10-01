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


def needs_allowance_reminder(*, cycle: Cycle, tracking_start: date, allowance_recorded: bool) -> bool:
    """FR-28: remind until an allowance is recorded in this cycle.

    In a first, partial cycle (tracking began after the cycle started) that cycle's allowance is
    already inside the opening balance, so there is nothing to remind about.
    """
    return tracking_start <= cycle.start and not allowance_recorded


def dashboard(conn: sqlite3.Connection, user_id: int, clock: Clock) -> DashboardView:
    today = clock.today()
    ledger_settings, planning_settings = current_settings(conn, user_id)
    cycle = cycle_for(today, planning_settings.allowance_day)
    recorded = ledger.has_allowance_income(conn, user_id=user_id, start=cycle.start, end_inclusive=today)
    return DashboardView(
        recorded_balance_cents=ledger.get_balance(conn, user_id=user_id, as_of=today),
        planned_allowance_cents=planning_settings.planned_allowance_cents,
        cycle=cycle,
        tracking_start=ledger_settings.tracking_start,
        allowance_reminder=needs_allowance_reminder(
            cycle=cycle, tracking_start=ledger_settings.tracking_start, allowance_recorded=recorded
        ),
    )
