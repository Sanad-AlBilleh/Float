"""Safe-to-spend composition and the purchase preview (SRS §4.5, Fixture A, AT-19)."""

from datetime import date

import pytest

from app.insights.api import SafeToSpendInputs, compute, preview
from app.shared.dates import cycle_for
from app.shared.errors import ValidationError

CYCLE = cycle_for(date(2026, 9, 20), 1)  # 11 days to 1 October
PERSONAL = SafeToSpendInputs(recorded_balance_cents=50000, personal_bills_cents=12000, protected_savings_cents=5000)
FULL = SafeToSpendInputs(50000, 12000, 1200, 5000, 1000)


def test_fixture_a_without_the_household():
    result = compute(PERSONAL, CYCLE)
    assert (result.discretionary_cents, result.daily_cents, result.shortfall_cents) == (33000, 3000, 0)


def test_fixture_a_previews():
    result = compute(PERSONAL, CYCLE)
    assert preview(result, 11000).after_cents == 22000 and preview(result, 11000).after_daily_cents == 2000
    big = preview(result, 35000)
    assert (big.after_cents, big.after_daily_cents, big.after_shortfall_cents) == (-2000, 0, 2000)


def test_the_full_fixture_a_inputs():
    result = compute(FULL, CYCLE)
    assert FULL.reserved_cents == 19200
    assert (result.discretionary_cents, result.daily_cents) == (30800, 2800)
    assert (preview(result, 11000).after_daily_cents, preview(result, 35000).after_shortfall_cents) == (1800, 4200)


def test_the_daily_amount_rounds_down_to_whole_cents():
    result = compute(SafeToSpendInputs(1000), cycle_for(date(2026, 9, 28), 1))  # 3 days left
    assert result.daily_cents == 333


def test_a_deficit_shows_zero_per_day_and_the_exact_shortfall():
    result = compute(SafeToSpendInputs(10000, personal_bills_cents=12345), CYCLE)
    assert (result.discretionary_cents, result.daily_cents, result.shortfall_cents) == (-2345, 0, 2345)


@pytest.mark.parametrize("cost", [0, -1, 100_000_001])
def test_a_preview_needs_a_positive_cost(cost):
    with pytest.raises(ValidationError) as error:
        preview(compute(PERSONAL, CYCLE), cost)
    assert "cost" in error.value.errors


def test_every_reservation_is_subtracted_exactly_once():
    inputs = SafeToSpendInputs(100000, 1, 20, 300, 4000, 50000)
    assert inputs.reserved_cents == 54321
    assert compute(inputs, CYCLE).discretionary_cents == 45679
