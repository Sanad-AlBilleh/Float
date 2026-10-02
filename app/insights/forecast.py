"""Pace, runway, the day-by-day cash projection, and the next-cycle outlook (SRS §4.7). Pure."""

from dataclasses import dataclass
from datetime import date, timedelta

from app.shared.dates import Cycle, allowance_dates

MAX_WINDOW_DAYS = 28
MIN_WINDOW_DAYS = 7


@dataclass(frozen=True)
class ForecastInputs:
    cycle: Cycle
    tracking_start: date
    allowance_day: int
    discretionary_cents: int
    daily_cents: int
    recorded_balance_cents: int
    protected_savings_cents: int
    household_payables_cents: int
    planned_allowance_cents: int
    commitments: tuple[tuple[date, int], ...]  # (due date, cents) of unpaid, unskipped bills and bill shares
    variable_consumption_cents: int  # over the pace window
    next_cycle_goal_plan_cents: int = 0


@dataclass(frozen=True)
class DayProjection:
    day: date
    conservative_cents: int  # if the allowance never arrives
    expected_cents: int  # if the planned allowance arrives on its scheduled date


@dataclass(frozen=True)
class Forecast:
    pace_cents: int | None  # None: under 7 days of history
    effective_pace_cents: int
    runway_days: int | None  # None: unlimited
    run_out_date: date | None
    status: str  # "on_track" or "at_risk"
    carry_over_cents: int
    lowest_expected: DayProjection
    conservative_goes_negative: bool
    dips_into_savings: bool
    next_free_cents: int
    next_daily_cents: int
    next_shortfall_cents: int
    timeline: tuple[DayProjection, ...]


def pace_window_days(today: date, tracking_start: date) -> int:
    """Complete days of history before today, at most 28."""
    return min(MAX_WINDOW_DAYS, (today - tracking_start).days)


def compute_forecast(inputs: ForecastInputs) -> Forecast:
    cycle, today = inputs.cycle, inputs.cycle.today
    window = pace_window_days(today, inputs.tracking_start)
    pace = inputs.variable_consumption_cents // window if window >= MIN_WINDOW_DAYS else None
    effective = pace if pace is not None else inputs.daily_cents
    if inputs.discretionary_cents < 0:
        runway = 0
    elif effective == 0:
        runway = None  # unlimited
    else:
        runway = inputs.discretionary_cents // effective
    run_out = today + timedelta(days=runway) if runway is not None else None
    status = "on_track" if runway is None or runway >= cycle.days_remaining else "at_risk"
    carry_over = max(0, inputs.discretionary_cents - effective * cycle.days_remaining)
    paydays = allowance_dates(today + timedelta(days=1), cycle.horizon_end, inputs.allowance_day)
    timeline, day = [], today
    while day < cycle.horizon_end:
        committed = sum(cents for due, cents in inputs.commitments if due <= day) + inputs.household_payables_cents
        conservative = inputs.recorded_balance_cents - committed - effective * ((day - today).days + 1)
        expected = conservative + inputs.planned_allowance_cents * sum(1 for payday in paydays if payday <= day)
        timeline.append(DayProjection(day, conservative, expected))
        day += timedelta(days=1)
    lowest = min(timeline, key=lambda point: (point.expected_cents, point.day))
    next_commitments = inputs.next_cycle_goal_plan_cents + sum(
        cents for due, cents in inputs.commitments if cycle.next_allowance <= due < cycle.horizon_end
    )
    next_free = carry_over + inputs.planned_allowance_cents - next_commitments
    next_days = (cycle.horizon_end - cycle.next_allowance).days
    return Forecast(
        pace, effective, runway, run_out, status, carry_over, lowest,
        any(point.conservative_cents < 0 for point in timeline),
        lowest.expected_cents < inputs.protected_savings_cents,
        next_free, max(0, next_free) // next_days, max(0, -next_free), tuple(timeline),
    )
