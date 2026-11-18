from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.shared.dates import (
    Cycle,
    add_months,
    allowance_dates,
    cycle_for,
    parse_iso_date,
    scheduled_date,
)
from app.shared.errors import ValidationError


def test_fixture_a_cycle():
    cycle = cycle_for(date(2026, 9, 20), 1)
    assert cycle == Cycle(
        today=date(2026, 9, 20),
        start=date(2026, 9, 1),
        next_allowance=date(2026, 10, 1),
        horizon_end=date(2026, 11, 1),
    )
    assert cycle.days_remaining == 11


@pytest.mark.parametrize(
    "today, day, start, next_allowance, horizon_end",
    [
        (date(2027, 1, 31), 31, date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)),
        (date(2028, 1, 31), 31, date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31)),
        (date(2027, 2, 28), 31, date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)),
        (date(2027, 3, 1), 31, date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)),
        (date(2026, 10, 1), 1, date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)),
        (date(2026, 12, 15), 20, date(2026, 11, 20), date(2026, 12, 20), date(2027, 1, 20)),
    ],
)
def test_cycle_boundaries(today, day, start, next_allowance, horizon_end):
    cycle = cycle_for(today, day)
    assert (cycle.start, cycle.next_allowance, cycle.horizon_end) == (start, next_allowance, horizon_end)


def test_payday_starts_a_new_cycle_and_never_divides_by_zero():
    assert cycle_for(date(2026, 10, 1), 1).days_remaining == 31


def test_scheduled_date_clamps_to_the_last_day_of_the_month():
    assert scheduled_date(2027, 2, 31) == date(2027, 2, 28)
    assert scheduled_date(2028, 2, 30) == date(2028, 2, 29)
    assert scheduled_date(2026, 4, 31) == date(2026, 4, 30)


def test_add_months_carries_the_year():
    assert add_months(2026, 11, 3) == (2027, 2)
    assert add_months(2027, 1, -1) == (2026, 12)
    assert add_months(2026, 9, 0) == (2026, 9)


def test_fixture_b_counts_six_cycles_before_march():
    assert allowance_dates(date(2026, 9, 1), date(2027, 3, 1), 1) == [
        date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1),
        date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1),
    ]


@pytest.mark.parametrize("day", [0, 32, -1])
def test_rejects_an_invalid_allowance_day(day):
    with pytest.raises(ValidationError) as error:
        cycle_for(date(2026, 9, 20), day)
    assert "allowance_day" in error.value.errors


def test_parses_strict_iso_dates():
    assert parse_iso_date("2026-09-30") == date(2026, 9, 30)
    assert parse_iso_date(" 2026-09-30 ") == date(2026, 9, 30)


@pytest.mark.parametrize("text", [None, "", "30/09/2026", "2026-W40-3", "20260930", "2026-02-30", "2026-9-3"])
def test_rejects_other_date_formats(text):
    with pytest.raises(ValidationError) as error:
        parse_iso_date(text, field="occurred_on")
    assert error.value.errors == {"occurred_on": "Enter a date as YYYY-MM-DD."}


@given(
    today=st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)),
    day=st.integers(min_value=1, max_value=31),
)
def test_cycle_properties(today, day):
    cycle = cycle_for(today, day)
    assert cycle.start <= today < cycle.next_allowance < cycle.horizon_end
    assert cycle.days_remaining >= 1
    assert allowance_dates(cycle.start, cycle.horizon_end, day) == [cycle.start, cycle.next_allowance]
