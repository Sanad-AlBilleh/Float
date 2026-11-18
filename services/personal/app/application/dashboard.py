"""The dashboard's numbers: recorded balance, the cycle, the allowance reminder, and safe-to-spend with every
term of SRS §4.5 (FR-27–29).

Household terms come from the households service over HTTP (Assignment 2). If it does not answer, the
dashboard is still shown, without household terms and with ``households_available`` false, so the UI can
say "household balances unavailable" instead of failing the whole page (ADR-6).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.application.setup import current_settings
from app.clients.households import (
    EMPTY_POSITION,
    NO_POSITION,
    HouseholdsClient,
    HouseholdsUnavailable,
    Position,
)
from app.db.connection import Connection
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
    household_receivables_cents: int = 0  # owed to the user: shown, never counted (SRS §4.5)
    in_household: bool = False
    household_commitments: tuple[tuple[date, int], ...] = ()
    households_available: bool = True
    household_open_bills: tuple = ()


def needs_allowance_reminder(*, cycle: Cycle, first_cycle_start: date, counted_at_setup: bool,
                             allowance_recorded: bool) -> bool:
    """FR-28: remind until this cycle's allowance is recorded.

    The one exception is the cycle in which tracking began, when setup recorded that its allowance is
    already in the opening balance; recording it again would count it twice.
    """
    if allowance_recorded:
        return False
    return not (counted_at_setup and cycle.start == first_cycle_start)


def household_position(households: HouseholdsClient | None, user_id: int, cycle: Cycle) -> Position:
    """The households service materializes its bills and sums the user's terms; NO_POSITION if it is down."""
    if households is None:
        return EMPTY_POSITION
    try:
        return households.position(user_id, window_end=cycle.next_allowance, horizon_end=cycle.horizon_end)
    except HouseholdsUnavailable:
        return NO_POSITION


def dashboard(conn: Connection, user_id: int, clock: Clock, households: HouseholdsClient | None = None,
              position: Position | None = None) -> DashboardView:
    today = clock.today()
    with transaction(conn):  # materializing bills is idempotent bookkeeping, allowed on GET (FR-10)
        ledger_settings, planning_settings = current_settings(conn, user_id)
        cycle = cycle_for(today, planning_settings.allowance_day)
        planning.ensure_materialized(conn, user_id=user_id, horizon_end=cycle.horizon_end)
    recorded = ledger.has_allowance_income(conn, user_id=user_id, start=cycle.start, end_inclusive=today)
    first_cycle_start = cycle_for(ledger_settings.tracking_start, planning_settings.allowance_day).start
    balance = ledger.get_balance(conn, user_id=user_id, as_of=today)
    obligations = planning.get_obligations(conn, user_id=user_id, cycle=cycle)
    if position is None:
        position = household_position(households, user_id, cycle)
    inputs = insights.SafeToSpendInputs(
        recorded_balance_cents=balance,
        personal_bills_cents=obligations.personal_bills_cents,
        household_bill_shares_cents=position.bill_shares_cents,
        protected_savings_cents=obligations.protected_savings_cents,
        household_payables_cents=position.payables_cents,
        goal_plan_reserve_cents=obligations.goal_plan_reserve_cents,
    )
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
        household_receivables_cents=position.receivables_cents,
        in_household=position.in_household,
        household_commitments=position.commitments,
        households_available=position.available,
        household_open_bills=position.open_bills,
    )


@dataclass(frozen=True)
class ForecastView:
    dashboard: DashboardView
    forecast: insights.Forecast
    window_days: int


def forecast(conn: Connection, user_id: int, clock: Clock, households: HouseholdsClient | None = None,
             position: Position | None = None, shares: list | None = None) -> ForecastView:
    """FR-30: personal and household spending, bills, and payables (SRS §4.7)."""
    view = dashboard(conn, user_id, clock, households, position)
    _, planning_settings = current_settings(conn, user_id)
    today = view.cycle.today
    window = insights.pace_window_days(today, view.tracking_start)
    rows = ledger.get_expense_rows(conn, user_id=user_id, start=today - timedelta(days=window), end_exclusive=today)
    open_bills = planning.open_occurrences_due_before(conn, user_id=user_id, before=view.cycle.horizon_end)
    inputs = insights.ForecastInputs(
        cycle=view.cycle,
        tracking_start=view.tracking_start,
        allowance_day=planning_settings.allowance_day,
        discretionary_cents=view.safe.discretionary_cents,
        daily_cents=view.safe.daily_cents,
        recorded_balance_cents=view.recorded_balance_cents,
        protected_savings_cents=view.safe.inputs.protected_savings_cents,
        household_payables_cents=view.safe.inputs.household_payables_cents,
        planned_allowance_cents=view.planned_allowance_cents,
        commitments=tuple((o.due_date, o.amount_cents) for o in open_bills) + view.household_commitments,
        variable_consumption_cents=insights.variable_consumption(
            rows, shares if shares is not None else share_rows(households, user_id, today - timedelta(days=window),
                                                               today)),
        next_cycle_goal_plan_cents=planning.next_cycle_goal_plan(conn, user_id=user_id, cycle=view.cycle),
    )
    return ForecastView(view, insights.compute_forecast(inputs), window)


def share_rows(households: HouseholdsClient | None, user_id: int, start: date,
               end_exclusive: date) -> list[insights.ShareRow]:
    """The user's shares of shared expenses, as Insights expects them (SRS §4.7). None if unavailable."""
    if households is None:
        return []
    try:
        rows = households.shares(user_id, start=start, end_exclusive=end_exclusive)
    except HouseholdsUnavailable:
        return []
    return [insights.ShareRow(r.amount_cents, r.occurred_on, r.category_id, r.from_household_bill, r.one_off)
            for r in rows]
