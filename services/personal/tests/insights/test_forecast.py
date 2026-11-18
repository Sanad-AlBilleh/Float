"""Pace, runway, the cash projection, and the next-cycle outlook (SRS §4.7, Fixtures A and C, AT-22)."""

from datetime import date, timedelta

import pytest

from app.insights.api import ForecastInputs, compute_forecast, pace_window_days
from app.shared.dates import cycle_for

FIXTURE_A = ForecastInputs(
    cycle=cycle_for(date(2026, 9, 20), 1), tracking_start=date(2026, 9, 1), allowance_day=1,
    discretionary_cents=30800, daily_cents=2800, recorded_balance_cents=50000, protected_savings_cents=5000,
    household_payables_cents=1000, planned_allowance_cents=75000,
    commitments=((date(2026, 9, 25), 12000), (date(2026, 10, 25), 12000), (date(2026, 9, 28), 1200),
                 (date(2026, 10, 28), 1200)),
    variable_consumption_cents=22800,
)


def with_(**changes) -> ForecastInputs:
    return ForecastInputs(**{**FIXTURE_A.__dict__, **changes})


def test_fixture_a_pace_runway_and_carry_over():
    forecast = compute_forecast(FIXTURE_A)
    assert pace_window_days(date(2026, 9, 20), date(2026, 9, 1)) == 19
    assert (forecast.pace_cents, forecast.effective_pace_cents, forecast.runway_days) == (1200, 1200, 25)
    assert (forecast.run_out_date, forecast.status, forecast.carry_over_cents) == (date(2026, 10, 15), "on_track", 17600)


def test_fixture_a_cash_projection():
    forecast = compute_forecast(FIXTURE_A)
    assert (forecast.lowest_expected.day, forecast.lowest_expected.expected_cents) == (date(2026, 9, 30), 22600)
    assert forecast.timeline[0].day == date(2026, 9, 20) and forecast.timeline[-1].day == date(2026, 10, 31)
    assert forecast.timeline[-1].conservative_cents == -27800
    assert forecast.conservative_goes_negative and not forecast.dips_into_savings


def test_fixture_a_next_cycle_outlook():
    forecast = compute_forecast(FIXTURE_A)
    assert (forecast.next_free_cents, forecast.next_daily_cents, forecast.next_shortfall_cents) == (79400, 2561, 0)
    assert compute_forecast(with_(next_cycle_goal_plan_cents=79500)).next_shortfall_cents == 100


def test_fixture_c_pace_at_risk():
    forecast = compute_forecast(with_(cycle=cycle_for(date(2026, 9, 21), 1), discretionary_cents=10000,
                                      daily_cents=1000, variable_consumption_cents=1500 * 20))
    assert (forecast.pace_cents, forecast.runway_days, forecast.status, forecast.carry_over_cents) == (
        1500, 6, "at_risk", 0)


def test_under_seven_days_of_history_uses_the_daily_amount():
    forecast = compute_forecast(with_(tracking_start=date(2026, 9, 14)))
    assert forecast.pace_cents is None and forecast.effective_pace_cents == 2800
    assert compute_forecast(with_(tracking_start=date(2026, 9, 13))).pace_cents == 22800 // 7


def test_the_window_is_at_most_28_days():
    assert pace_window_days(date(2026, 12, 1), date(2026, 1, 1)) == 28


def test_a_deficit_has_no_runway():
    forecast = compute_forecast(with_(discretionary_cents=-1))
    assert (forecast.runway_days, forecast.run_out_date, forecast.status) == (0, date(2026, 9, 20), "at_risk")


def test_no_spending_means_an_unlimited_runway():
    forecast = compute_forecast(with_(variable_consumption_cents=0))
    assert (forecast.runway_days, forecast.run_out_date, forecast.status) == (None, None, "on_track")


def test_a_plan_that_dips_into_savings_is_flagged():
    assert compute_forecast(with_(protected_savings_cents=22601)).dips_into_savings


@pytest.mark.parametrize("offset", [0, 10, 11, 41])
def test_expected_adds_the_allowance_from_payday(offset):
    point = compute_forecast(FIXTURE_A).timeline[offset]
    assert point.day == date(2026, 9, 20) + timedelta(days=offset)
    assert point.expected_cents - point.conservative_cents == (75000 if point.day >= date(2026, 10, 1) else 0)


def test_boundaries_of_status_and_savings():
    assert compute_forecast(with_(discretionary_cents=13200)).status == "on_track"  # runway 11 = days remaining
    assert compute_forecast(with_(discretionary_cents=13199)).status == "at_risk"
    assert not compute_forecast(with_(protected_savings_cents=22600)).dips_into_savings


def test_a_bill_counts_from_its_due_date():
    timeline = compute_forecast(FIXTURE_A).timeline
    assert (timeline[4].day, timeline[4].conservative_cents) == (date(2026, 9, 24), 50000 - 1000 - 1200 * 5)
    assert (timeline[5].day, timeline[5].conservative_cents) == (date(2026, 9, 25), 50000 - 13000 - 1200 * 6)


def test_ties_for_the_lowest_point_take_the_earliest_day():
    flat = compute_forecast(with_(variable_consumption_cents=0, commitments=(), household_payables_cents=0))
    assert flat.lowest_expected.day == date(2026, 9, 20)


def test_a_bill_due_on_payday_belongs_to_the_next_cycle():
    forecast = compute_forecast(with_(commitments=FIXTURE_A.commitments + ((date(2026, 10, 1), 5000),)))
    assert forecast.next_free_cents == 79400 - 5000


def test_nothing_left_and_no_spending_is_not_a_deficit():
    forecast = compute_forecast(with_(discretionary_cents=0, daily_cents=0, variable_consumption_cents=0))
    assert (forecast.runway_days, forecast.status) == (None, "on_track")
